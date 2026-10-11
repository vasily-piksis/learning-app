import threading
import unicodedata

import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select, text, update

from .ai import AIError
from .auth import require_user
from .library import get_or_404
from .models import Card, CardSource, Document, Explanation, Job, SourcePage, Topic, now
from .quiz import prepare_options, save_options, validate_preparation
from .schemas import CardEdit, GenerateBody, GeneratedCard, SaveCards
from .sources import source_data
from .youtube import ingest_youtube

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


def question_key(topic_id, question, answer, language):
    return (
        topic_id,
        *(
            " ".join(unicodedata.normalize("NFKC", value).casefold().split())
            for value in (question, answer)
        ),
        language,
    )


def job_data(job):
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "error": job.error,
        "result": job.result,
        "created": job.created.isoformat(),
        "updated": job.updated.isoformat(),
        "session_card_id": job.payload.get("session_card_id") if job.kind == "explain" else None,
        "topic_ids": job.payload.get("topic_ids")
        or [t["id"] for t in job.payload.get("topics", [])],
    }


def recover_jobs(database):
    with database.session() as db:
        for job in db.scalars(select(Job).where(Job.status == "running")):
            job.status = "failed"
            job.error = "Задача прервана перезапуском. Можно повторить вручную"
            if job.kind in {"ingest", "youtube"}:
                document = db.get(Document, job.payload["document_id"])
                if document:
                    document.status = "failed"


def check_refs(refs, sources):
    allowed = {(s["document_id"], s["page"]) for s in sources}
    if not refs or any((r.document_id, r.page) not in allowed for r in refs):
        raise ValueError("Модель указала недопустимый источник")


def ingest(database, ai, payload):
    with database.session() as db:
        document = db.get(Document, payload["document_id"])
        path = database.settings.data_dir / "files" / document.filename
        document.status = "processing"
        mime, count, identifier = document.mime, document.page_count, document.id
    for number in range(1, count + 1):
        with database.session() as db:
            if db.scalar(
                select(SourcePage).where(
                    SourcePage.document_id == identifier, SourcePage.number == number
                )
            ):
                continue
        local = ""
        if mime == "application/pdf":
            with pymupdf.open(path) as pdf:
                local = pdf[number - 1].get_text()
        result = ai.extract(path, mime, number, local)
        if result.page != number or (not result.text.strip() and not result.is_blank):
            raise ValueError("Страница не распознана. Проверьте качество изображения")
        if result.is_blank and result.text.strip():
            raise ValueError("Страница не может быть одновременно пустой и содержать текст")
        with database.session() as db:
            db.add(
                SourcePage(
                    document_id=identifier,
                    number=number,
                    text=result.text,
                    language=getattr(result, "language", None),
                    warnings=result.warnings or (["Пустая страница"] if result.is_blank else []),
                )
            )
    with database.session() as db:
        db.get(Document, identifier).status = "ready"
    return {"document_id": identifier, "pages": count}


def generate(database, ai, payload):
    results, reasons = [], []
    topics = payload["topics"]
    for index, topic in enumerate(topics):
        count = payload["count"] // len(topics) + int(index < payload["count"] % len(topics))
        generated = ai.generate(
            topic["id"],
            topic["sources"],
            payload["mode"],
            count,
            target_language=payload.get("target_language"),
            existing=topic.get("existing", []),
        )
        if len(generated.cards) > count:
            raise ValueError("Модель превысила запрошенное число карточек")
        if generated.insufficient_reason:
            reasons.append(generated.insufficient_reason)
        for card in generated.cards:
            if card.topic_id != topic["id"] or card.mode != payload["mode"]:
                raise ValueError("Модель смешала темы или форматы карточек")
            check_refs(card.sources, topic["sources"])
            languages = {
                s.get("language")
                for s in topic["sources"]
                if (s["document_id"], s["page"]) in {(r.document_id, r.page) for r in card.sources}
                and s.get("language")
            }
            target = payload.get("target_language")
            if target and card.language and card.language != target:
                raise ValueError("Модель вернула неверный язык перевода")
            if (
                not target
                and len(languages) == 1
                and card.language
                and card.language not in languages
            ):
                raise ValueError("Модель изменила язык исходного материала")
            card.language = (
                target or card.language or (next(iter(languages)) if len(languages) == 1 else None)
            )
            results.append((card, topic["sources"]))
    return results, reasons


def run_job(database, ai, identifier):
    with database.session() as db:
        claimed = db.execute(
            update(Job)
            .where(Job.id == identifier, Job.status == "queued")
            .values(status="running", error=None, updated=now())
        )
        if claimed.rowcount != 1:
            return
        job = db.get(Job, identifier)
        kind, payload, user_id = job.kind, job.payload, job.user_id
    try:
        if kind == "ingest":
            result = ingest(database, ai, payload)
        elif kind == "youtube":
            result = ingest_youtube(database, payload)
        elif kind == "generate":
            cards, reasons = generate(database, ai, payload)
            result = {"card_ids": [], "warnings": reasons}
        elif kind == "prepare_quiz":
            with database.session() as db:
                validate_preparation(db, payload)
            options = prepare_options(ai, payload)
            result = {"card_ids": [item.card_id for item in options]}
        elif kind == "explain":
            explanation = ai.explain(payload["snapshot"], payload["question"], payload["history"])
            check_refs(explanation.sources, payload["snapshot"]["sources"])
            if not explanation.text.strip():
                raise ValueError("Модель вернула пустое объяснение")
            explanation_data = explanation.model_dump()
            source_map = {
                (source["document_id"], source["page"]): source
                for source in payload["snapshot"]["sources"]
            }
            explanation_data["sources"] = [
                {k: v for k, v in source_map[(ref.document_id, ref.page)].items() if k != "text"}
                for ref in explanation.sources
            ]
            result = {}
        else:
            raise ValueError("Неизвестный тип задачи")
        with database.session() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            job = db.get(Job, identifier)
            if kind == "generate":
                existing = {
                    question_key(c.topic_id, c.question, c.answer, c.language)
                    for c in db.scalars(select(Card))
                }
                skipped = 0
                for generated, sources in cards:
                    key = question_key(
                        generated.topic_id, generated.question, generated.answer, generated.language
                    )
                    if key in existing:
                        skipped += 1
                        continue
                    existing.add(key)
                    card = Card(
                        topic_id=generated.topic_id,
                        job_id=identifier,
                        question=generated.question,
                        answer=generated.answer,
                        language=generated.language,
                        target_language=payload.get("target_language"),
                        mode=generated.mode,
                        options=generated.options,
                        correct_index=generated.correct_index,
                    )
                    db.add(card)
                    db.flush()
                    result["card_ids"].append(card.id)
                    page_map = {(s["document_id"], s["page"]): s["page_id"] for s in sources}
                    for key in {(r.document_id, r.page) for r in generated.sources}:
                        db.add(CardSource(card_id=card.id, page_id=page_map[key]))
                if skipped:
                    result["warnings"].append(f"Пропущено повторных вопросов: {skipped}")
            elif kind == "prepare_quiz":
                save_options(db, payload, options)
            elif kind == "explain":
                value = Explanation(
                    user_id=user_id,
                    session_card_id=payload["session_card_id"],
                    parent_id=payload["parent_id"],
                    question=payload["question"],
                    result=explanation_data,
                )
                db.add(value)
                db.flush()
                result = {"explanation_id": value.id, **explanation_data}
            job.status = "succeeded"
            job.result = result
    except Exception as error:
        if isinstance(error, (AIError, ValueError)) and not isinstance(error, ValidationError):
            message = str(error)[:600]
        else:
            message = "Не удалось обработать задачу. Проверьте материалы и повторите"
        with database.session() as db:
            job = db.get(Job, identifier)
            job.status, job.error = "failed", message
            if kind in {"ingest", "youtube"}:
                db.get(Document, payload["document_id"]).status = "failed"


def worker_loop(database, ai, stop: threading.Event):
    while not stop.is_set():
        with database.session() as db:
            identifier = db.scalar(
                select(Job.id).where(Job.status == "queued").order_by(Job.id).limit(1)
            )
        if identifier is None:
            stop.wait(1)
        else:
            run_job(database, ai, identifier)


@router.get("/jobs")
def jobs(request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        return [
            job_data(job)
            for job in db.scalars(
                select(Job).where(Job.user_id == user.id).order_by(Job.id.desc()).limit(100)
            )
        ]


@router.get("/jobs/{identifier}")
def job(identifier: int, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        value = get_or_404(db, Job, identifier)
        if value.kind in {"explain", "prepare_quiz"} and value.user_id != user.id:
            raise HTTPException(404, "Не найдено")
        return job_data(value)


@router.post("/jobs/{identifier}/retry")
def retry(identifier: int, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        value = get_or_404(db, Job, identifier)
        if value.kind in {"explain", "prepare_quiz"} and value.user_id != user.id:
            raise HTTPException(404, "Не найдено")
        if value.status != "failed":
            raise HTTPException(409, "Повторить можно только неудачную задачу")
        if value.kind == "prepare_quiz":
            try:
                validate_preparation(db, value.payload)
            except ValueError as error:
                raise HTTPException(409, str(error)) from error
        value.status, value.error = "queued", None
        if value.kind in {"ingest", "youtube"}:
            db.get(Document, value.payload["document_id"]).status = "queued"
        return job_data(value)


@router.post("/generate")
def start_generation(body: GenerateBody, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        if body.document_ids is not None:
            chosen = list(db.scalars(select(Document).where(Document.id.in_(body.document_ids))))
            if len(chosen) != len(body.document_ids) or any(
                d.topic_id not in body.topic_ids for d in chosen
            ):
                raise HTTPException(422, "Документы должны принадлежать выбранным темам")
        else:
            chosen = list(db.scalars(select(Document).where(Document.topic_id.in_(body.topic_ids))))
        if any(d.status != "ready" for d in chosen) and not body.allow_partial:
            raise HTTPException(
                409, "Есть неготовые материалы. Дождитесь обработки или явно выберите готовые"
            )
        topics, length = [], 0
        for identifier in body.topic_ids:
            get_or_404(db, Topic, identifier)
            sources = []
            for document in chosen:
                if document.topic_id != identifier or document.status != "ready":
                    continue
                for page in db.scalars(
                    select(SourcePage)
                    .where(SourcePage.document_id == document.id)
                    .order_by(SourcePage.number)
                ):
                    if not page.text.strip():
                        continue
                    sources.append(source_data(document, page, include_text=True))
                    length += len(page.text)
            if not sources:
                raise HTTPException(422, "В каждой выбранной теме нужны готовые материалы")
            existing = [
                {"question": c.question, "answer": c.answer, "language": c.language}
                for c in db.scalars(select(Card).where(Card.topic_id == identifier))
            ]
            length += sum(len(c["question"]) + len(c["answer"]) for c in existing)
            topics.append({"id": identifier, "sources": sources, "existing": existing})
        if length > 100000:
            raise HTTPException(
                422, "Материалы превышают 100 000 символов. Выберите меньше документов"
            )
        value = Job(
            user_id=user.id,
            kind="generate",
            payload={
                "topics": topics,
                "mode": body.mode,
                "count": body.count,
                "target_language": body.target_language,
            },
        )
        db.add(value)
        db.flush()
        return job_data(value)


def card_data(db, card, include_text=False):
    refs = list(db.scalars(select(CardSource).where(CardSource.card_id == card.id)))
    sources = []
    for ref in refs:
        page = db.get(SourcePage, ref.page_id)
        document = db.get(Document, page.document_id)
        sources.append(source_data(document, page, include_text))
    return {
        "id": card.id,
        "job_id": card.job_id,
        "topic_id": card.topic_id,
        "question": card.question,
        "answer": card.answer,
        "language": card.language,
        "target_language": card.target_language,
        "mode": card.mode,
        "options": card.options,
        "correct_index": card.correct_index,
        "version": card.version,
        "status": card.status,
        "sources": sources,
    }


@router.get("/cards")
def list_cards(
    request: Request,
    topic_id: int | None = None,
    job_id: int | None = None,
    status: str | None = None,
):
    with request.app.state.db.session() as db:
        query = select(Card).order_by(Card.id)
        if topic_id is not None:
            query = query.where(Card.topic_id == topic_id)
        if job_id is not None:
            query = query.where(Card.job_id == job_id)
        if status is not None:
            query = query.where(Card.status == status)
        return [card_data(db, card) for card in db.scalars(query)]


@router.patch("/cards/{identifier}")
def edit_card(identifier: int, body: CardEdit, request: Request):
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        card = get_or_404(db, Card, identifier)
        if card.version != body.version:
            raise HTTPException(409, "Карточка изменена в другой вкладке. Обновите список")
        original = card_data(db, card)
        try:
            validated = GeneratedCard.model_validate(
                {
                    **{k: original[k] for k in ["topic_id", "mode"]},
                    **body.model_dump(exclude={"version"}),
                    "sources": [
                        {"document_id": s["document_id"], "page": s["page"]}
                        for s in original["sources"]
                    ],
                }
            )
        except ValidationError:
            raise HTTPException(
                422, "Проверьте вопрос, ответ и единственный правильный вариант"
            ) from None
        card.question, card.answer = validated.question, validated.answer
        card.options, card.correct_index = validated.options, validated.correct_index
        card.version += 1
        return card_data(db, card)


@router.post("/cards/save")
def save_cards(body: SaveCards, request: Request):
    with request.app.state.db.session() as db:
        cards = list(db.scalars(select(Card).where(Card.id.in_(body.card_ids))))
        if len(cards) != len(set(body.card_ids)):
            raise HTTPException(404, "Карточка не найдена")
        for card in cards:
            card.status = "saved"
        return {"saved": len(cards)}

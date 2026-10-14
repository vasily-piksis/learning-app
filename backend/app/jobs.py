import hashlib
import json
import threading
from collections import Counter

import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select, text, update

from .ai import AIError
from .auth import require_user
from .deletion import cleanup_deleted_files
from .exercises import normalize_text
from .library import get_or_404
from .models import Card, CardSource, Document, Explanation, Job, SourcePage, Topic, now
from .quiz import (
    correct_indices,
    preparation_job,
    prepare_options,
    quiz_ready,
    save_options,
    validate_preparation,
)
from .schemas import (
    CardEdit,
    GenerateBody,
    GeneratedCard,
    PrepareOptionsBody,
    QuizOptions,
    SaveCards,
    SavePreparationBody,
)
from .sources import available_sources, source_data
from .youtube import ingest_youtube

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


def question_key(topic_id, question, answer, language, question_type="choice", exercise=None):
    return (
        topic_id,
        normalize_text(question),
        normalize_text(answer),
        language,
        question_type,
        json.dumps(exercise, sort_keys=True, ensure_ascii=False),
    )


def generation_quotas(topic_ids, question_types, count):
    pairs = [(topic, kind) for topic in topic_ids for kind in question_types]
    if not pairs or count < len(pairs):
        raise ValueError("Нужен хотя бы один вопрос для каждой темы и типа")
    return {
        topic: {
            kind: count // len(pairs) + int(index < count % len(pairs))
            for index, (t, kind) in enumerate(pairs)
            if t == topic
        }
        for topic in topic_ids
    }


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def request_replay(db, user_id, kind, key, body_fingerprint):
    if key is None:
        return None
    for row in db.scalars(select(Job).where(Job.user_id == user_id).order_by(Job.id.desc())):
        for entry in row.payload.get("request_keys", []):
            if entry["key"] == key:
                if row.kind != kind or entry["fingerprint"] != body_fingerprint:
                    raise HTTPException(409, "Идентификатор уже использован для другого запроса")
                return row
    return None


def bind_request(job, key, body_fingerprint):
    if key is not None:
        entries = job.payload.get("request_keys", [])
        if len(entries) >= 100:
            raise HTTPException(409, "Слишком много повторов. Дождитесь текущей задачи")
        job.payload = {
            **job.payload,
            "request_keys": [*entries, {"key": key, "fingerprint": body_fingerprint}],
        }


def job_data(job, db=None):
    result = job.result
    if db is not None and job.kind == "explain" and result:
        result = {**result, "sources": available_sources(db, result["sources"])}
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "error": job.error,
        "result": result,
        "created": job.created.isoformat(),
        "updated": job.updated.isoformat(),
        "session_card_id": job.payload.get("session_card_id") if job.kind == "explain" else None,
        "topic_ids": job.payload.get("topic_ids")
        or [t["id"] for t in job.payload.get("topics", [])],
    }


def recover_jobs(database):
    cleanup_deleted_files(database)
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
        db.execute(text("BEGIN IMMEDIATE"))
        document = get_or_404(db, Document, payload["document_id"])
        path = database.settings.data_dir / "files" / document.filename
        document.status = "processing"
        mime, count, identifier = document.mime, document.page_count, document.id
    for number in range(1, count + 1):
        with database.session() as db:
            get_or_404(db, Document, identifier)
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
            db.execute(text("BEGIN IMMEDIATE"))
            get_or_404(db, Document, identifier)
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
        db.execute(text("BEGIN IMMEDIATE"))
        get_or_404(db, Document, identifier).status = "ready"
    return {"document_id": identifier, "pages": count}


def generate(database, ai, payload, job_id=None):
    if payload.get("target_language"):
        raise ValueError("Перевод отключён. Создайте новую задачу на исходном языке")
    results, reasons, unsupported = [], [], []
    topics = payload["topics"]
    kinds = payload.get("question_types", ["choice"])
    quotas = generation_quotas([t["id"] for t in topics], kinds, payload["count"])
    for topic in topics:
        with database.session() as db:
            if job_id is not None and db.get(Job, job_id).status != "running":
                raise ValueError("Задача отменена")
            get_or_404(db, Topic, topic["id"])
            for source in topic["sources"]:
                get_or_404(db, Document, source["document_id"])
        count = sum(quotas[topic["id"]].values())
        arguments = dict(target_language=None, existing=topic.get("existing", []))
        if kinds != ["choice"] or payload.get("practice_goal", "content") != "content":
            arguments.update(
                question_types=kinds,
                type_counts=quotas[topic["id"]],
                practice_goal=payload.get("practice_goal", "content"),
            )
        generated = ai.generate(topic["id"], topic["sources"], payload["mode"], count, **arguments)
        counts = Counter(card.question_type for card in generated.cards)
        if any(
            kind not in kinds or amount > quotas[topic["id"]].get(kind, 0)
            for kind, amount in counts.items()
        ):
            raise ValueError("Модель нарушила типы или квоты вопросов")
        rejected = set()
        for item in getattr(generated, "unsupported_types", []):
            if (
                item.question_type not in kinds
                or item.question_type in rejected
                or counts[item.question_type]
                or not item.reason.strip()
            ):
                raise ValueError("Модель вернула противоречивый неподходящий тип")
            rejected.add(item.question_type)
            unsupported.append({"question_type": item.question_type, "reason": item.reason.strip()})
            reasons.append(item.reason.strip())
        if generated.insufficient_reason:
            reasons.append(generated.insufficient_reason)
        for card in generated.cards:
            if card.topic_id != topic["id"] or card.mode != payload["mode"]:
                raise ValueError("Модель смешала темы или форматы карточек")
            check_refs(card.sources, topic["sources"])
            refs = {(r.document_id, r.page) for r in card.sources}
            languages = {
                s.get("language")
                for s in topic["sources"]
                if (s["document_id"], s["page"]) in refs and s.get("language")
            }
            if len(languages) > 1:
                raise ValueError("Один вопрос должен использовать источники одного языка")
            if len(languages) == 1 and card.language and card.language not in languages:
                raise ValueError("Модель изменила язык исходного материала")
            card.language = card.language or (next(iter(languages)) if languages else None)
            results.append((card, topic["sources"]))
    return results, reasons, unsupported


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
            cards, reasons, unsupported = generate(database, ai, payload, identifier)
            result = {"card_ids": [], "warnings": reasons, "unsupported_types": unsupported}
        elif kind == "prepare_quiz":
            with database.session() as db:
                validate_preparation(db, payload)

            def check_preparation():
                with database.session() as db:
                    if db.get(Job, identifier).status != "running":
                        raise ValueError("Задача отменена")
                    validate_preparation(db, payload)

            options = prepare_options(ai, payload, before_each=check_preparation)
            versions = {c["id"]: c["version"] for c in payload["cards"]}
            result = {
                "card_ids": [item.card_id for item in options],
                "candidates": [
                    {**item.model_dump(), "version": versions[item.card_id]} for item in options
                ],
                "applied_card_ids": [],
            }
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
            if job.status != "running":
                return
            if kind == "generate":
                existing = {
                    question_key(
                        c.topic_id, c.question, c.answer, c.language, c.question_type, c.exercise
                    )
                    for c in db.scalars(select(Card).where(Card.status != "deleted"))
                }
                skipped = 0
                for generated, sources in cards:
                    key = question_key(
                        generated.topic_id,
                        generated.question,
                        generated.answer,
                        generated.language,
                        generated.question_type,
                        generated.exercise.model_dump() if generated.exercise else None,
                    )
                    if key in existing:
                        skipped += 1
                        continue
                    existing.add(key)
                    card = Card(
                        topic_id=generated.topic_id,
                        question_type=generated.question_type,
                        exercise=generated.exercise.model_dump() if generated.exercise else None,
                        job_id=identifier,
                        question=generated.question,
                        answer=generated.answer,
                        language=generated.language,
                        target_language=payload.get("target_language"),
                        mode=generated.mode,
                        options=generated.options,
                        correct_index=generated.correct_index,
                        correct_indices=generated.correct_indices,
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
                validate_preparation(db, payload)
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
            db.execute(text("BEGIN IMMEDIATE"))
            job = db.get(Job, identifier)
            if job.status != "running":
                return
            job.status, job.error = "failed", message
            if kind in {"ingest", "youtube"}:
                db.get(Document, payload["document_id"]).status = "failed"

    finally:
        # Caption-cache writes can finish after deletion cancelled an in-flight download.
        # Check outside the job transaction before cleaning any unreferenced transcript.
        if kind == "youtube":
            with database.session() as db:
                cancelled = db.get(Job, identifier).status == "cancelled"
            if cancelled:
                cleanup_deleted_files(database)


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
            job_data(job, db)
            for job in db.scalars(
                select(Job)
                .where(Job.user_id == user.id, Job.status != "deleted")
                .order_by(Job.id.desc())
                .limit(100)
            )
        ]


@router.get("/jobs/{identifier}")
def job(identifier: int, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        value = get_or_404(db, Job, identifier)
        if value.kind in {"explain", "prepare_quiz"} and value.user_id != user.id:
            raise HTTPException(404, "Не найдено")
        return job_data(value, db)


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
        return job_data(value, db)


@router.post("/generate")
def start_generation(body: GenerateBody, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        body_signature = fingerprint(body.model_dump(exclude={"idempotency_key"}))
        replay = request_replay(db, user.id, "generate", body.idempotency_key, body_signature)
        if replay is not None:
            return job_data(replay, db)
        if body.document_ids is not None:
            chosen = list(
                db.scalars(
                    select(Document).where(
                        Document.id.in_(body.document_ids), Document.status != "deleted"
                    )
                )
            )
            if len(chosen) != len(body.document_ids) or any(
                d.topic_id not in body.topic_ids for d in chosen
            ):
                raise HTTPException(422, "Документы должны принадлежать выбранным темам")
        else:
            chosen = list(
                db.scalars(
                    select(Document).where(
                        Document.topic_id.in_(body.topic_ids), Document.status != "deleted"
                    )
                )
            )
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
                {
                    "question": c.question,
                    "answer": c.answer,
                    "language": c.language,
                    "question_type": c.question_type,
                    "exercise": c.exercise,
                }
                for c in db.scalars(
                    select(Card).where(Card.topic_id == identifier, Card.status != "deleted")
                )
            ]
            length += sum(len(c["question"]) + len(c["answer"]) for c in existing)
            topics.append({"id": identifier, "sources": sources, "existing": existing})
        if length > 100000:
            raise HTTPException(
                422, "Материалы превышают 100 000 символов. Выберите меньше документов"
            )
        scope = fingerprint(
            {
                "body": body.model_dump(exclude={"idempotency_key"}),
                "sources": [{"id": t["id"], "sources": t["sources"]} for t in topics],
            }
        )
        active = db.scalar(
            select(Job).where(
                Job.user_id == user.id,
                Job.kind == "generate",
                Job.status.in_(["queued", "running"]),
                Job.payload["scope"].as_string() == scope,
            )
        )
        if active is not None:
            bind_request(active, body.idempotency_key, body_signature)
            return job_data(active, db)
        value = Job(
            user_id=user.id,
            kind="generate",
            payload={
                "topics": topics,
                "mode": body.mode,
                "count": body.count,
                "target_language": None,
                "question_types": body.question_types,
                "practice_goal": body.practice_goal,
                "scope": scope,
            },
        )
        bind_request(value, body.idempotency_key, body_signature)
        db.add(value)
        db.flush()
        return job_data(value, db)


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
        "question_type": card.question_type,
        "exercise": card.exercise,
        "question": card.question,
        "answer": card.answer,
        "language": card.language,
        "target_language": card.target_language,
        "mode": card.mode,
        "options": card.options,
        "correct_index": card.correct_index,
        "correct_indices": correct_indices(card),
        "multiple_answers": len(correct_indices(card)) > 1,
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
        query = select(Card).where(Card.status != "deleted").order_by(Card.id)
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
        supplied = body.model_dump(exclude={"version"}, exclude_unset=True)
        exercise = supplied.get("exercise", original["exercise"])
        try:
            validated = GeneratedCard.model_validate(
                {
                    **{
                        k: original[k]
                        for k in (
                            "topic_id",
                            "mode",
                            "question_type",
                            "language",
                            "question",
                            "answer",
                            "options",
                            "correct_index",
                            "correct_indices",
                        )
                    },
                    **supplied,
                    "exercise": exercise,
                    "sources": [
                        {"document_id": s["document_id"], "page": s["page"]}
                        for s in original["sources"]
                    ],
                }
            )
            if (
                card.question_type != "choice"
                and body.answer is not None
                and body.answer != validated.answer
            ):
                raise ValueError("Решение должно соответствовать упражнению")
        except (ValidationError, ValueError):
            raise HTTPException(422, "Проверьте вопрос, ответ и параметры задания") from None
        card.question, card.answer = validated.question, validated.answer
        card.options, card.correct_index = validated.options, validated.correct_index
        card.correct_indices = validated.correct_indices
        card.exercise = validated.exercise.model_dump() if validated.exercise else None
        card.version += 1
        return card_data(db, card)


@router.post("/cards/save")
def save_cards(body: SaveCards, request: Request):
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        cards = list(
            db.scalars(select(Card).where(Card.id.in_(body.card_ids), Card.status != "deleted"))
        )
        if len(cards) != len(set(body.card_ids)):
            raise HTTPException(404, "Карточка не найдена")
        for card in cards:
            card.status = "saved"
        return {"saved": len(cards)}


@router.post("/study/prepare-options")
def prepare_quiz_options(body: PrepareOptionsBody, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        signature = fingerprint(body.model_dump(exclude={"idempotency_key"}))
        previous = request_replay(db, user.id, "prepare_quiz", body.idempotency_key, signature)
        if previous is not None:
            return job_data(previous, db)
        for topic_id in body.topic_ids:
            get_or_404(db, Topic, topic_id)
        cards = list(
            db.scalars(
                select(Card)
                .where(
                    Card.topic_id.in_(body.topic_ids),
                    Card.status == "saved",
                    Card.question_type == "choice",
                )
                .order_by(Card.id)
            )
        )
        missing = [card_data(db, card, include_text=True) for card in cards if not quiz_ready(card)]
        if not missing:
            raise HTTPException(422, "Нет сохранённых вопросов, которым нужны варианты")
        value = preparation_job(db, user.id, sorted(body.topic_ids), missing)
        bind_request(value, body.idempotency_key, signature)
        return job_data(value, db)


@router.post("/jobs/{identifier}/save-preparation")
def accept_preparation(identifier: int, body: SavePreparationBody, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        job = get_or_404(db, Job, identifier)
        if job.user_id != user.id or job.kind != "prepare_quiz":
            raise HTTPException(404, "Не найдено")
        if job.status != "succeeded" or not job.result or job.result.get("discarded"):
            raise HTTPException(409, "Сначала дождитесь подготовки")
        candidates = {c["card_id"]: c for c in job.result.get("candidates", [])}
        if not set(body.card_ids) <= set(candidates):
            raise HTTPException(422, "Вопросы не принадлежат этому предпросмотру")
        applied = set(job.result.get("applied_card_ids", []))
        selected = set(body.card_ids) - applied
        snapshots = [c for c in job.payload["cards"] if c["id"] in selected]
        options = [
            QuizOptions.model_validate(
                {k: v for k, v in candidates[c["id"]].items() if k != "version"}
            )
            for c in snapshots
        ]
        if selected:
            try:
                save_options(db, {"cards": snapshots}, options)
            except ValueError as error:
                raise HTTPException(409, str(error)) from error
        job.result = {**job.result, "applied_card_ids": sorted(applied | selected)}
        return {"saved": len(body.card_ids), "card_ids": sorted(body.card_ids)}


@router.post("/jobs/{identifier}/discard-preparation")
def discard_preparation(identifier: int, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        job = get_or_404(db, Job, identifier)
        if job.user_id != user.id or job.kind != "prepare_quiz":
            raise HTTPException(404, "Не найдено")
        if job.status in {"queued", "running"}:
            job.status = "cancelled"
        job.payload = {k: v for k, v in job.payload.items() if k in {"request_keys", "topic_ids"}}
        applied = (job.result or {}).get("applied_card_ids", [])
        job.result = {
            "discarded": True,
            "applied_card_ids": applied,
            "candidates": [],
            "card_ids": [],
        }
        return {"discarded": True}

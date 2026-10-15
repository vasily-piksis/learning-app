"""One-question regeneration with a private, explicitly applied candidate."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, StrictInt, model_validator
from sqlalchemy import delete, select, text

from .auth import require_user
from .jobs import (
    bind_request,
    card_data,
    check_refs,
    fingerprint,
    job_data,
    question_key,
    request_replay,
)
from .models import Card, CardSource, Document, Job
from .quiz import free_settings, validate_free_preparation
from .schemas import (
    DeterministicGeneratedCard,
    GeneratedCard,
    ImageUpdate,
    PreparedFreeCard,
    Strict,
)

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


class RegenerateBody(Strict):
    version: StrictInt = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=80)
    another_variant: bool = False


class Regenerated(Strict):
    card: GeneratedCard | None
    insufficient_reason: str | None

    @model_validator(mode="after")
    def one_result(self):
        if (self.card is None) == (
            not self.insufficient_reason or not self.insufficient_reason.strip()
        ):
            raise ValueError("Нужен вопрос либо причина недостаточности")
        return self


class DeterministicRegenerated(Regenerated):
    card: DeterministicGeneratedCard | None


class RegeneratedFreeResponse(Strict):
    card: PreparedFreeCard | None
    insufficient_reason: str | None = Field(max_length=2000)
    source_language_matches: bool

    @model_validator(mode="after")
    def one_result(self):
        if (self.card is None) == (not (self.insufficient_reason or "").strip()):
            raise ValueError("Нужен вопрос либо причина недостаточности")
        if self.card is not None and not self.source_language_matches:
            raise ValueError("Нельзя переводить исходные материалы")
        return self


class ApplyBody(Strict):
    candidate: GeneratedCard
    image_updates: dict[Literal["question", "answer"], ImageUpdate] | None = None


def owned(db, identifier, user_id):
    job = db.get(Job, identifier)
    if not job or job.kind != "regenerate" or job.user_id != user_id or job.status == "deleted":
        raise HTTPException(404, "Не найдено")
    return job


def check_scope(db, payload):
    card = db.get(Card, payload["card_id"])
    if not card or card.status == "deleted":
        raise HTTPException(404, "Вопрос удалён")
    if card.version != payload["base_version"]:
        raise ValueError("Вопрос изменён. Подготовьте новый вариант")
    current = card_data(db, card, include_text=True)
    if fingerprint(current) != payload["source_fingerprint"]:
        raise ValueError("Вопрос или его источники изменились")
    if payload.get("picture_source"):
        from .picture_responses import card_evidence

        evidence = card_evidence(db, card)
        if {"kind": "image", "asset_id": evidence.asset_id, "sha256": evidence.sha256} != payload[
            "picture_source"
        ]:
            raise ValueError("Источник картинки изменён")
        return card
    if not current["sources"] or any(
        db.get(Document, s["document_id"]).status != "ready" for s in current["sources"]
    ):
        raise ValueError("Источники недоступны")
    return card


def validate_candidate(db, payload, candidate):
    snapshot = payload["snapshot"]
    if any(
        getattr(candidate, key) != snapshot[key]
        for key in ("topic_id", "question_type", "language", "mode")
    ):
        raise ValueError("Нельзя изменить тему, тип или язык вопроса")
    if payload.get("picture_source"):
        from .picture_responses import setup_of

        if (
            candidate.sources
            or candidate.exercise.source.model_dump() != payload["picture_source"]
            or setup_of(candidate.exercise.model_dump()).model_dump() != payload["picture_setup"]
        ):
            raise ValueError("Источник или настройки картинки изменены")
    else:
        check_refs(candidate.sources, snapshot["sources"])
    if candidate.question_type == "free_response":
        validate_free_preparation(
            candidate.model_dump(), snapshot["sources"], free_settings(snapshot["exercise"])
        )
    key = question_key(
        candidate.topic_id,
        candidate.question,
        candidate.answer,
        candidate.language,
        candidate.question_type,
        candidate.exercise.model_dump() if candidate.exercise else None,
    )
    for other in db.scalars(
        select(Card).where(
            Card.topic_id == candidate.topic_id,
            Card.id != payload["card_id"],
            Card.status != "deleted",
        )
    ):
        if (
            question_key(
                other.topic_id,
                other.question,
                other.answer,
                other.language,
                other.question_type,
                other.exercise,
            )
            == key
        ):
            raise ValueError("Такой вопрос уже существует")


@router.post("/cards/{identifier}/regenerate")
def start(identifier: int, body: RegenerateBody, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        signature = fingerprint(
            {"card_id": identifier, **body.model_dump(exclude={"idempotency_key"})}
        )
        replay = request_replay(db, user.id, "regenerate", body.idempotency_key, signature)
        if replay is not None:
            return job_data(replay, db)
        card = db.get(Card, identifier)
        if card and card.status != "deleted" and card.question_type == "picture_description":
            from .picture_responses import PreparePicture, prepare_picture, setup_of

            setup = setup_of(card.exercise).model_dump(exclude={"goal", "preparation_state"})
            # Release the transaction before the picture route acquires its write lock.
            db.rollback()
            return prepare_picture(
                identifier,
                PreparePicture(
                    version=body.version,
                    idempotency_key=body.idempotency_key,
                    another_variant=body.another_variant,
                    **setup,
                ),
                request,
                submitted_fingerprint=signature,
            )
        if not card or card.status == "deleted":
            raise HTTPException(404, "Вопрос удалён")
        if card.version != body.version:
            raise HTTPException(409, "Вопрос изменён. Обновите страницу")
        snapshot = card_data(db, card, include_text=True)
        if snapshot.get("target_language"):
            raise HTTPException(422, "Перевод отключён. Создайте вопрос на исходном языке")
        if not snapshot["sources"] or not any(s["text"].strip() for s in snapshot["sources"]):
            raise HTTPException(422, "Для регенерации нужны источники")
        current_fingerprint = fingerprint(snapshot)
        # Illustrations affect version/scope, but are never model evidence.
        snapshot.pop("images", None)
        for active in db.scalars(
            select(Job)
            .where(
                Job.user_id == user.id,
                Job.kind == "regenerate",
                Job.status.in_(["queued", "running", "succeeded"]),
            )
            .order_by(Job.id.desc())
        ):
            if (
                active.payload.get("card_id") != identifier
                or active.payload.get("base_version") != body.version
                or active.payload.get("source_fingerprint") != current_fingerprint
            ):
                continue
            has_candidate = bool((active.result or {}).get("candidate")) and not (
                active.result or {}
            ).get("applied_result")
            if active.status in {"queued", "running"} or has_candidate and not body.another_variant:
                bind_request(active, body.idempotency_key, signature)
                return job_data(active, db)
        languages = {s["language"] for s in snapshot["sources"] if s["language"]}
        if (
            len(languages) > 1
            or snapshot["language"]
            and languages
            and snapshot["language"] not in languages
        ):
            raise HTTPException(422, "Источники должны сохранять язык вопроса")
        snapshot["language"] = snapshot["language"] or (
            next(iter(languages)) if languages else None
        )
        payload = {
            "card_id": identifier,
            "base_version": body.version,
            "topic_ids": [card.topic_id],
            "source_fingerprint": current_fingerprint,
            "snapshot": snapshot,
        }
        try:
            check_scope(db, payload)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        value = Job(user_id=user.id, kind="regenerate", payload=payload)
        bind_request(value, body.idempotency_key, signature)
        db.add(value)
        db.flush()
        return job_data(value, db)


def run_regeneration(database, ai, payload, identifier):
    with database.session() as db:
        check_scope(db, payload)
    if payload.get("picture_source"):
        from .picture_responses import card_evidence, prepare_with_ai

        with database.session() as db:
            card = check_scope(db, payload)
            evidence = card_evidence(db, card)

        def before_request():
            from .evaluations import require_available

            require_available(database.settings, "picture_description")
            with database.session() as db:
                if db.get(Job, identifier).status != "running":
                    raise ValueError("Подготовка отменена")
                check_scope(db, payload)

        candidate = prepare_with_ai(
            ai, payload["snapshot"], payload["picture_setup"], evidence, before_request
        )
        raw = Regenerated(card=candidate, insufficient_reason=None)
    else:
        raw = ai.regenerate(payload["snapshot"], payload["snapshot"]["sources"])
    output = Regenerated.model_validate(
        {
            "card": raw.card.model_dump() if raw.card else None,
            "insufficient_reason": raw.insufficient_reason,
        }
    )
    candidate = (
        GeneratedCard.model_validate(output.card.model_dump()) if output.card is not None else None
    )
    if candidate is None and not (output.insufficient_reason or "").strip():
        raise ValueError("Модель не вернула вопрос или причину")
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        job = db.get(Job, identifier)
        if job.status != "running":
            return
        check_scope(db, payload)
        if candidate:
            validate_candidate(db, payload, candidate)
        job.status = "succeeded"
        job.result = {
            "candidate": candidate.model_dump() if candidate else None,
            "insufficient_reason": output.insufficient_reason,
            "base_version": payload["base_version"],
            "card_id": payload["card_id"],
        }


@router.post("/jobs/{identifier}/apply-regeneration")
def apply(identifier: int, body: ApplyBody, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        job = owned(db, identifier, user.id)
        signature = fingerprint(body.model_dump())
        result = job.result or {}
        if result.get("applied_result"):
            if signature != result["applied_fingerprint"]:
                raise HTTPException(409, "Этот вариант уже применён с другим содержимым")
            return result["applied_result"]
        if job.status != "succeeded" or not result.get("candidate") or result.get("discarded"):
            raise HTTPException(409, "Вариант недоступен для применения")
        try:
            card = check_scope(db, job.payload)
            validate_candidate(db, job.payload, body.candidate)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        from .question_images import apply_updates, cleanup_image_assets

        if (
            job.payload.get("picture_source")
            and body.image_updates
            and "question" in body.image_updates
            and body.image_updates["question"].asset_id != job.payload["picture_source"]["asset_id"]
        ):
            raise HTTPException(409, "Критерии подготовлены для другой картинки")
        apply_updates(db, card, body.image_updates, user.id)
        candidate = body.candidate
        for field in (
            "question",
            "answer",
            "options",
            "correct_index",
            "correct_indices",
            "language",
        ):
            setattr(card, field, getattr(candidate, field))
        card.exercise = candidate.exercise.model_dump() if candidate.exercise else None
        card.version += 1
        source_map = {
            (s["document_id"], s["page"]): s["page_id"] for s in job.payload["snapshot"]["sources"]
        }
        db.execute(delete(CardSource).where(CardSource.card_id == card.id))
        for ref in {(r.document_id, r.page) for r in candidate.sources}:
            db.add(CardSource(card_id=card.id, page_id=source_map[ref]))
        db.flush()
        applied = card_data(db, card)
        job.result = {
            "candidate": None,
            "applied_version": card.version,
            "applied_fingerprint": signature,
            "applied_result": applied,
        }
        result = applied
    cleanup_image_assets(request.app.state.db)
    return result


@router.post("/jobs/{identifier}/discard-regeneration")
def discard(identifier: int, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        job = owned(db, identifier, user.id)
        if (job.result or {}).get("applied_result"):
            raise HTTPException(409, "Применённый вариант нельзя отклонить")
        job.status = "cancelled"
        job.result = {"discarded": True}
        job.payload = {
            k: v
            for k, v in job.payload.items()
            if k in {"card_id", "topic_ids", "base_version", "request_keys"}
        }
        job.error = None
        result = job_data(job, db)
    from .question_images import cleanup_image_assets

    cleanup_image_assets(request.app.state.db)
    return result

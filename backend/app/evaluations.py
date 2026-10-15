"""Private answer lifecycle, per-send family quota, and local-only recovery."""

import hashlib
import json
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from openai import APIConnectionError
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from sqlalchemy import delete, func, select, text

from .auth import require_user
from .evaluation_ai import EvaluationAI
from .free_responses import (
    EvaluationGrade,
    InsufficientContext,
    StoredEvaluationGrade,
    response_exercise,
    validate_evaluation,
)
from .models import Attempt, Evaluation, EvaluationRequest, Job, SessionCard, StudySession, now
from .retry import TransientError

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])
ERRORS = {
    "failed": "Не удалось проверить ответ. Можно явно повторить проверку",
    "unknown": "Результат неизвестен; запрос мог быть оплачен. Автоматического повтора нет",
    "quota_exceeded": "Дневной лимит проверок исчерпан",
    "runtime_unavailable": "Проверка свободных ответов сейчас недоступна",
    "insufficient_context": "Недостаточно сохранённого контекста для проверки",
}


class EvaluationCancelled(Exception):
    pass


class EvaluationQuotaExceeded(Exception):
    pass


class EvaluationUnavailable(Exception):
    pass


def utc_now():
    return datetime.now(UTC)


def runtime_available(settings, question_type="free_response"):
    try:
        ZoneInfo(settings.budget_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return bool(
        (
            settings.picture_description_enabled and settings.openai_vision_enabled
            if question_type == "picture_description"
            else settings.free_response_enabled
        )
        and settings.openai_api_key
        and settings.openai_model
        and len(settings.openai_model) <= 200
        and not any(c.isspace() for c in settings.openai_model)
        and settings.free_response_daily_request_limit > 0
    )


def require_available(settings, question_type="free_response"):
    if not runtime_available(settings, question_type):
        raise HTTPException(
            409, {"code": "runtime_unavailable", "message": ERRORS["runtime_unavailable"]}
        )


def submission_fingerprint(card_id, submission):
    return hashlib.sha256(
        json.dumps([card_id, submission], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def key_used(db, user_id, key):
    # Aliases live only with their private Evaluation. Charged aliases survive in the ledger.
    if db.scalar(
        select(Attempt.id).where(Attempt.user_id == user_id, Attempt.idempotency_key == key)
    ):
        return True
    if db.scalar(
        select(EvaluationRequest.id).where(
            EvaluationRequest.user_id == user_id, EvaluationRequest.request_key == key
        )
    ):
        return True
    return any(
        key in value.request_keys
        for value in db.scalars(select(Evaluation).where(Evaluation.user_id == user_id))
    )


def live_context(db, evaluation, revision=None, statuses=None):
    if evaluation is None or (revision is not None and evaluation.revision != revision):
        raise EvaluationCancelled()
    if statuses is not None and evaluation.status not in statuses:
        raise EvaluationCancelled()
    card = db.get(SessionCard, evaluation.session_card_id)
    job = db.get(Job, evaluation.job_id)
    session = db.get(StudySession, card.session_id) if card else None
    if (
        not session
        or not job
        or session.status != "active"
        or session.position != card.position
        or session.user_id != evaluation.user_id
        or job.user_id != evaluation.user_id
        or job.status not in {"queued", "running"}
        or job.payload.get("revision") != evaluation.revision
    ):
        raise EvaluationCancelled()
    return card, session, job


def evaluation_data(db, evaluation, include_submission=True):
    from .study import feedback

    data = {
        "evaluation_id": evaluation.id,
        "job_id": evaluation.job_id,
        "status": "running" if evaluation.status == "staged" else evaluation.status,
    }
    if include_submission:
        data["submission"] = evaluation.submission
        data["error"] = ERRORS.get(evaluation.error_code)
        data["error_code"] = evaluation.error_code
    if evaluation.status == "completed":
        attempt = db.scalar(
            select(Attempt).where(Attempt.session_card_id == evaluation.session_card_id)
        )
        card = db.get(SessionCard, evaluation.session_card_id)
        result = feedback(attempt, card, card.session_id, db)
        if not include_submission:
            return result
        data["feedback"] = result
    return data


def answer_evaluation(db, settings, session, card, user_id, key, submission):
    existing = db.scalar(select(Evaluation).where(Evaluation.session_card_id == card.id))
    fingerprint = submission_fingerprint(card.id, submission)
    if existing:
        if key not in existing.request_keys or fingerprint != existing.fingerprint:
            raise HTTPException(409, "Этот ответ уже отправлен")
        data = evaluation_data(db, existing, include_submission=False)
        return JSONResponse(data, status_code=200 if existing.status == "completed" else 202)
    require_available(settings, card.snapshot.get("question_type"))
    if (
        session.status != "active"
        or session.position != card.position
        or key_used(db, user_id, key)
    ):
        raise HTTPException(409, "Ответ или идентификатор запроса уже сохранён")
    from .answer_audio import voice_metadata

    voice_metadata(db, card, user_id, submission)
    job = Job(
        user_id=user_id,
        kind="evaluate_response",
        payload={"session_card_id": card.id, "revision": 1, "request_key": key},
    )
    db.add(job)
    db.flush()
    evaluation = Evaluation(
        session_card_id=card.id,
        user_id=user_id,
        job_id=job.id,
        request_key=key,
        request_keys=[key],
        fingerprint=fingerprint,
        submission=submission,
    )
    if card.snapshot.get("question_type") == "picture_description":
        from .picture_responses import get_picture_evidence
        from .question_images import bind_context

        try:
            evidence = get_picture_evidence(db, card.id, user_id)
        except ValueError:
            raise HTTPException(409, "Источник картинки недоступен") from None
        bind_context(db, job.id, evidence.asset_id)
    db.add(evaluation)
    db.flush()
    return JSONResponse(evaluation_data(db, evaluation, False), status_code=202)


def reserve_evaluation_request(database, job_id, request_key):
    """One durable debit immediately before EACH actual send, including retries."""
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        evaluation = db.scalar(select(Evaluation).where(Evaluation.job_id == job_id))
        card, _, job = live_context(db, evaluation, statuses={"running"})
        if job.status != "running" or job.payload.get("request_key") != request_key:
            raise EvaluationCancelled()
        if not runtime_available(database.settings, card.snapshot.get("question_type")):
            raise EvaluationUnavailable()
        current = utc_now()
        zone = ZoneInfo(database.settings.budget_timezone)
        day = current.astimezone(zone).date()
        start = datetime.combine(day, time.min, zone).astimezone(UTC).replace(tzinfo=None)
        end = (
            datetime.combine(day + timedelta(days=1), time.min, zone)
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        used = db.scalar(
            select(func.count(EvaluationRequest.id)).where(
                EvaluationRequest.reserved_at >= start, EvaluationRequest.reserved_at < end
            )
        )
        if used >= database.settings.free_response_daily_request_limit:
            raise EvaluationQuotaExceeded()
        attempt_no = (
            db.scalar(
                select(func.max(EvaluationRequest.attempt_no)).where(
                    EvaluationRequest.job_id == job_id
                )
            )
            or 0
        ) + 1
        record = EvaluationRequest(
            job_id=job_id,
            user_id=evaluation.user_id,
            attempt_no=attempt_no,
            request_key=request_key,
            reserved_at=current.replace(tzinfo=None),
            status="reserved",
            model=database.settings.openai_model,
            usage=None,
        )
        db.add(record)
        db.flush()
        return record.id


def stage_evaluation(database, evaluation_id, revision, result):
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        evaluation = db.get(Evaluation, evaluation_id)
        card, _, _ = live_context(db, evaluation, revision, {"running"})
        grade = validate_evaluation(
            response_exercise(card.snapshot),
            evaluation.submission["free_text"],
            result,
        )
        evaluation.staged_result = grade.model_dump()
        evaluation.status = "staged"
        return evaluation.staged_result


def finalize_evaluation(database, evaluation_id, revision, validated_result):
    """CAS under SQLite's write lock: one stored v2 Attempt and one advance."""
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        evaluation = db.get(Evaluation, evaluation_id)
        if evaluation and evaluation.revision == revision and evaluation.status == "completed":
            return evaluation.applied_result
        card, session, job = live_context(db, evaluation, revision, {"staged"})
        if evaluation.staged_result != validated_result:
            raise EvaluationCancelled()
        grade = EvaluationGrade.model_validate(evaluation.staged_result)
        from .answer_audio import voice_metadata

        voice = voice_metadata(db, card, evaluation.user_id, evaluation.submission)
        stored = StoredEvaluationGrade(
            **grade.model_dump(),
            version=2,
            evaluation_id=evaluation.id,
            input_method="voice" if voice else "text",
            voice=voice,
        ).model_dump(exclude_none=True)
        # Preserve the null academic word limits in the stored, versioned result.
        stored["word_limit"] = grade.word_limit.model_dump()
        db.add(
            Attempt(
                user_id=evaluation.user_id,
                session_card_id=card.id,
                idempotency_key=evaluation.request_key,
                value={**evaluation.submission, "_grading": stored},
                correct=grade.correct,
            )
        )
        session.position += 1
        session.updated = now()
        count = db.scalar(
            select(func.count(SessionCard.id)).where(SessionCard.session_id == session.id)
        )
        if session.position >= count:
            session.status = "completed"
        evaluation.status, evaluation.applied_result, evaluation.error_code = (
            "completed",
            stored,
            None,
        )
        job.status, job.result, job.error = "succeeded", {"evaluation_id": evaluation.id}, None
        return stored


def outcome_unknown(error):
    while error is not None:
        if isinstance(error, (APIConnectionError, TransientError)):
            return True
        error = error.__cause__
    return False


def run_evaluation_job(database, job_id, revision):
    # The generic worker has already claimed this job. Capture only immutable input.
    try:
        with database.session() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            evaluation = db.scalar(select(Evaluation).where(Evaluation.job_id == job_id))
            card, _, job = live_context(db, evaluation, revision, {"queued"})
            evaluation.status = "running"
            identifier, submission, snapshot = evaluation.id, evaluation.submission, card.snapshot
            key = job.payload["request_key"]
    except EvaluationCancelled:
        return
    reservations = []
    outcome, ledger_error = "unknown", None

    def before_request():
        reservations.append(reserve_evaluation_request(database, job_id, key))

    try:
        if not runtime_available(database.settings, card.snapshot.get("question_type")):
            raise EvaluationUnavailable()
        if snapshot.get("question_type") == "picture_description":
            from .picture_responses import get_picture_evidence

            with database.session() as db:
                evidence = get_picture_evidence(db, card.id, evaluation.user_id)
            result = EvaluationAI(database.settings).evaluate(
                snapshot, submission["free_text"], before_request, evidence=evidence
            )
        else:
            result = EvaluationAI(database.settings).evaluate(
                snapshot, submission["free_text"], before_request
            )
        outcome = "succeeded"
        staged = stage_evaluation(database, identifier, revision, result)
        finalize_evaluation(database, identifier, revision, staged)
    except EvaluationCancelled:
        return
    except Exception as error:
        code = (
            "quota_exceeded"
            if isinstance(error, EvaluationQuotaExceeded)
            else "runtime_unavailable"
            if isinstance(error, EvaluationUnavailable)
            else "insufficient_context"
            if isinstance(error, InsufficientContext)
            else "unknown"
            if outcome_unknown(error)
            else "failed"
        )
        if outcome != "succeeded":
            ledger_error = code
            outcome = (
                "unknown"
                if code in {"unknown", "quota_exceeded", "runtime_unavailable"}
                else "failed"
            )
        with database.session() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            evaluation = db.get(Evaluation, identifier)
            if (
                evaluation is None
                or evaluation.revision != revision
                or evaluation.status != "running"
            ):
                # A durable stage must survive local commit failure; recovery uses it.
                return
            evaluation.status, evaluation.error_code = (
                ("unknown" if code == "unknown" else "failed"),
                code,
            )
            job = db.get(Job, job_id)
            if job.status == "running":
                job.status, job.error = evaluation.status, ERRORS[code]
    finally:
        from .question_images import cleanup_image_assets

        cleanup_image_assets(database)
        with database.session() as db:
            for record in db.scalars(
                select(EvaluationRequest).where(
                    EvaluationRequest.id.in_(reservations),
                    EvaluationRequest.job_id == job_id,
                    EvaluationRequest.request_key == key,
                )
            ):
                # The SDK adapter returns no per-attempt usage. Do not invent token zeros.
                record.status = outcome if record.id == reservations[-1] else "unknown"
                record.error_code = ledger_error


def cleanup_evaluation_requests(database):
    with database.session() as db:
        db.execute(
            delete(EvaluationRequest).where(
                EvaluationRequest.reserved_at
                < (utc_now() - timedelta(days=30)).replace(tzinfo=None)
            )
        )


def recover_evaluations(database):
    cleanup_evaluation_requests(database)
    with database.session() as db:
        staged = [
            (v.id, v.revision, v.staged_result)
            for v in db.scalars(select(Evaluation).where(Evaluation.status == "staged"))
        ]
    for identifier, revision, result in staged:
        try:
            finalize_evaluation(database, identifier, revision, result)
        except EvaluationCancelled:
            pass
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        for evaluation in db.scalars(
            select(Evaluation).where(Evaluation.status.in_(["queued", "running"]))
        ):
            job = db.get(Job, evaluation.job_id)
            if job.status == "running" or evaluation.status == "running":
                evaluation.status, evaluation.error_code = "unknown", "unknown"
                job.status, job.error = "unknown", ERRORS["unknown"]
        for record in db.scalars(
            select(EvaluationRequest).where(EvaluationRequest.status == "reserved")
        ):
            record.status = "unknown"


class RetryEvaluationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=80)
    acknowledge_extra_cost: StrictBool

    @field_validator("acknowledge_extra_cost")
    @classmethod
    def acknowledged(cls, value):
        if not value:
            raise ValueError("Подтвердите возможную дополнительную оплату")
        return value


@router.get("/study/{identifier}/evaluations")
def status(identifier: int, position: int, request: Request):
    from .study import at_position, owned

    user = require_user(request)
    with request.app.state.db.session() as db:
        owned(db, identifier, user.id)
        card = at_position(db, identifier, position)
        evaluation = db.scalar(
            select(Evaluation).where(
                Evaluation.session_card_id == card.id, Evaluation.user_id == user.id
            )
        )
        return evaluation_data(db, evaluation) if evaluation else None


@router.post("/evaluations/{identifier}/retry")
def retry(identifier: int, body: RetryEvaluationBody, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        evaluation = db.get(Evaluation, identifier)
        if not evaluation or evaluation.user_id != user.id:
            raise HTTPException(404, "Не найдено")
        if evaluation.status == "completed":
            raise HTTPException(409, "Завершённый ответ нельзя оценить повторно")
        job = db.get(Job, evaluation.job_id)
        if body.idempotency_key in evaluation.request_keys:
            if (
                body.idempotency_key == job.payload["request_key"]
                and body.idempotency_key != evaluation.request_key
            ):
                return JSONResponse(evaluation_data(db, evaluation, False), status_code=202)
            raise HTTPException(409, "Для повтора нужен новый идентификатор")
        if evaluation.status not in {"failed", "unknown"}:
            raise HTTPException(409, "Повтор доступен только после ошибки")
        card = db.get(SessionCard, evaluation.session_card_id)
        require_available(
            request.app.state.settings,
            card.snapshot.get("question_type") if card else "free_response",
        )
        if key_used(db, user.id, body.idempotency_key) or len(evaluation.request_keys) >= 100:
            raise HTTPException(409, "Идентификатор уже использован или достигнут лимит повторов")
        card = db.get(SessionCard, evaluation.session_card_id)
        session = db.get(StudySession, card.session_id) if card else None
        if not session or session.status != "active" or session.position != card.position:
            raise HTTPException(409, "Занятие больше не активно")
        if card.snapshot.get("question_type") == "picture_description":
            from .picture_responses import get_picture_evidence
            from .question_images import bind_context

            try:
                evidence = get_picture_evidence(db, card.id, user.id)
            except ValueError:
                raise HTTPException(409, "Источник картинки недоступен") from None
            bind_context(db, job.id, evidence.asset_id)
        evaluation.request_keys = [*evaluation.request_keys, body.idempotency_key]
        evaluation.revision += 1
        evaluation.status, evaluation.error_code = "queued", None
        job.status, job.error = "queued", None
        job.payload = {
            **job.payload,
            "revision": evaluation.revision,
            "request_key": body.idempotency_key,
        }
        return JSONResponse(evaluation_data(db, evaluation, False), status_code=202)

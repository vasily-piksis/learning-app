"""Explicit single-image attempts; durable accounting and local-only save recovery."""

import base64
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import Field, StrictBool, StrictInt, field_validator
from sqlalchemy import delete, func, select, text

from .auth import require_user
from .jobs import bind_request, fingerprint, job_data, request_replay
from .models import ImageAsset, ImageRequest, Job, JobImage
from .question_images import (
    Slot,
    asset_path,
    candidate_data,
    cleanup_image_assets,
    live_card,
    normalize_image,
    write_candidate,
)
from .schemas import Strict

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])
FIXED_SETTINGS = {"n": 1, "size": "1024x1024", "quality": "low", "output_format": "webp"}
UNKNOWN_MESSAGE = "Результат неизвестен; запрос мог быть оплачен. Автоматического повтора нет"


@dataclass
class GeneratedImage:
    data: bytes
    metadata: dict = field(default_factory=dict)


class ImageOutcomeUnknown(Exception):
    pass


class ImageProviderFailure(Exception):
    def __init__(self, code="provider_rejected"):
        self.code = code


def safe_usage(metadata):
    usage = metadata.get("usage", {})
    return (
        {
            key: value
            for key, value in usage.items()
            if key in {"input_tokens", "output_tokens", "total_tokens"}
            and type(value) is int
            and value >= 0
        }
        if isinstance(usage, dict)
        else {}
    )


class ImageGenerator:
    def __init__(self, settings, model):
        self.model = model
        self.client = OpenAI(api_key=settings.openai_api_key, max_retries=0)

    def generate(self, prompt: str) -> GeneratedImage:
        try:
            result = self.client.images.generate(model=self.model, prompt=prompt, **FIXED_SETTINGS)
        except (APITimeoutError, APIConnectionError) as error:
            raise ImageOutcomeUnknown() from error
        except APIStatusError as error:
            if error.status_code >= 500 or error.status_code == 408:
                raise ImageOutcomeUnknown() from error
            code = (
                "access_denied"
                if error.status_code in {401, 403}
                else ("rate_limited" if error.status_code == 429 else "provider_rejected")
            )
            raise ImageProviderFailure(code) from error
        try:
            if len(result.data) != 1 or not result.data[0].b64_json:
                raise ValueError("Missing single image")
            data = base64.b64decode(result.data[0].b64_json, validate=True)
            usage = getattr(result, "usage", None)
            return GeneratedImage(data, {"usage": usage.model_dump() if usage else {}})
        except (AttributeError, TypeError, ValueError) as error:
            raise ImageOutcomeUnknown() from error


class GenerateImageBody(Strict):
    version: StrictInt = Field(ge=1)
    slot: Slot
    prompt: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=80)


class RetryImageBody(Strict):
    idempotency_key: str = Field(min_length=1, max_length=80)
    acknowledge_extra_cost: StrictBool

    @field_validator("acknowledge_extra_cost")
    @classmethod
    def acknowledged(cls, value):
        if not value:
            raise ValueError("Подтвердите возможную дополнительную оплату")
        return value


def utc_now():
    return datetime.now(UTC)


def budget_window(current, timezone):
    zone = ZoneInfo(timezone)
    day = current.astimezone(zone).date()
    return (
        datetime.combine(day, time.min, zone).astimezone(UTC),
        datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC),
    )


def configuration_status(settings):
    if not settings.image_generation_enabled:
        return "disabled"
    if not settings.openai_image_model.strip():
        return "missing_model"
    if len(settings.openai_image_model) > 200 or any(
        c.isspace() for c in settings.openai_image_model
    ):
        return "invalid_model"
    if not settings.openai_api_key:
        return "missing_key"
    try:
        ZoneInfo(settings.image_budget_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return "invalid_timezone"
    if settings.image_daily_request_limit < 1:
        return "invalid_limit"
    return "ready"


def budget(db, settings, current=None):
    start, end = budget_window(current or utc_now(), settings.image_budget_timezone)
    used = db.scalar(
        select(func.count(ImageRequest.id)).where(
            ImageRequest.reserved_at >= start.replace(tzinfo=None),
            ImageRequest.reserved_at < end.replace(tzinfo=None),
        )
    )
    return {
        "limit": settings.image_daily_request_limit,
        "used": used,
        "remaining": max(0, settings.image_daily_request_limit - used),
        "timezone": settings.image_budget_timezone,
        "next_reset_at": end.isoformat(),
    }


def require_available(db, settings, current=None):
    if configuration_status(settings) != "ready":
        raise HTTPException(503, "Генерация картинок отключена или не настроена")
    if budget(db, settings, current)["remaining"] == 0:
        raise HTTPException(429, "Дневной лимит запросов картинок исчерпан")


@router.get("/image-generation")
def availability(request: Request):
    settings = request.app.state.settings
    with request.app.state.db.session() as db:
        status = configuration_status(settings)
        try:
            limits = budget(db, settings)
        except (ZoneInfoNotFoundError, ValueError):
            limits = {
                "limit": settings.image_daily_request_limit,
                "used": None,
                "remaining": 0,
                "timezone": settings.image_budget_timezone,
                "next_reset_at": None,
            }
        last = db.scalar(select(ImageRequest).order_by(ImageRequest.id.desc()).limit(1))
        return {
            "status": status,
            "enabled": settings.image_generation_enabled,
            "model": settings.openai_image_model or None,
            "settings": FIXED_SETTINGS,
            "access_status": "denied"
            if last and last.error_code == "access_denied"
            else ("confirmed" if last and last.status == "succeeded" else "unverified"),
            **limits,
        }


def owned_job(db, identifier, user_id):
    job = db.get(Job, identifier)
    if not job or job.kind != "generate_image" or job.user_id != user_id:
        raise HTTPException(404, "Не найдено")
    return job


def check_scope(db, payload):
    card = live_card(db, payload["card_id"])
    if card.version != payload["version"] or card.question_type != payload["question_type"]:
        raise HTTPException(409, "Вопрос изменён. Обновите страницу")
    return card


def check_busy(db, card_id, slot, excluding=None):
    query = select(Job.id).where(
        Job.kind == "generate_image",
        Job.status.in_(["queued", "running"]),
        Job.payload["card_id"].as_integer() == card_id,
        Job.payload["slot"].as_string() == slot,
    )
    if excluding is not None:
        query = query.where(Job.id != excluding)
    if db.scalar(query.limit(1)) is not None:
        raise HTTPException(409, "Для этого места уже готовится картинка")


def replay(db, user_id, key, signature):
    recorded = db.scalar(
        select(ImageRequest).where(ImageRequest.user_id == user_id, ImageRequest.request_key == key)
    )
    if recorded:
        if recorded.fingerprint != signature:
            raise HTTPException(409, "Идентификатор уже использован для другого запроса")
        return db.get(Job, recorded.job_id)
    return request_replay(db, user_id, "generate_image", key, signature)


@router.post("/cards/{identifier}/generate-image")
def start(identifier: int, body: GenerateImageBody, request: Request):
    user = require_user(request)
    database = request.app.state.db
    signature = fingerprint({"card_id": identifier, **body.model_dump(exclude={"idempotency_key"})})
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        previous = replay(db, user.id, body.idempotency_key, signature)
        if previous:
            return job_data(previous, db)
        require_available(db, database.settings)
        card = live_card(db, identifier)
        if card.version != body.version:
            raise HTTPException(409, "Вопрос изменён. Обновите страницу")
        check_busy(db, identifier, body.slot)
        job = Job(
            user_id=user.id,
            kind="generate_image",
            payload={
                "card_id": identifier,
                "version": body.version,
                "slot": body.slot,
                "question_type": card.question_type,
                "prompt": body.prompt,
                "topic_ids": [card.topic_id],
                "model": database.settings.openai_image_model,
                "settings": FIXED_SETTINGS,
                "pending_key": body.idempotency_key,
                "pending_fingerprint": signature,
            },
        )
        bind_request(job, body.idempotency_key, signature)
        db.add(job)
        db.flush()
        return job_data(job, db)


@router.post("/jobs/{identifier}/retry-image")
def retry(identifier: int, body: RetryImageBody, request: Request):
    user = require_user(request)
    database = request.app.state.db
    signature = fingerprint({"retry_image": identifier, "acknowledge_extra_cost": True})
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        job = owned_job(db, identifier, user.id)
        previous = replay(db, user.id, body.idempotency_key, signature)
        if previous:
            return job_data(previous, db)
        if job.status not in {"failed", "unknown"} or (job.result or {}).get("can_retry_save"):
            raise HTTPException(409, "Сначала завершите локальное сохранение или дождитесь задачи")
        require_available(db, database.settings)
        check_scope(db, job.payload)
        check_busy(db, job.payload["card_id"], job.payload["slot"], job.id)
        bind_request(job, body.idempotency_key, signature)
        job.payload = {
            **job.payload,
            "pending_key": body.idempotency_key,
            "pending_fingerprint": signature,
        }
        job.status, job.error, job.result = "queued", None, None
        return job_data(job, db)


def current_attempt(db, identifier):
    return db.scalar(
        select(ImageRequest)
        .where(ImageRequest.job_id == identifier)
        .order_by(ImageRequest.attempt_no.desc())
        .limit(1)
    )


def staged_asset(db, identifier):
    return db.scalar(
        select(ImageAsset)
        .join(JobImage, JobImage.asset_id == ImageAsset.id)
        .where(JobImage.job_id == identifier, JobImage.role == "candidate")
    )


def stage_image(database, identifier, generated):
    encoded, width, height = normalize_image(generated.data)
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        job = db.get(Job, identifier)
        if job.status != "running":
            return False
        live_card(db, job.payload["card_id"])
        identity = uuid.uuid4().hex
        asset = ImageAsset(
            id=identity,
            filename=f"{identity}.webp",
            owner_user_id=job.user_id,
            origin="generated",
            target_card_id=job.payload["card_id"],
            target_version=job.payload["version"],
            slot=job.payload["slot"],
            width=width,
            height=height,
            provider_meta={
                "model": job.payload["model"],
                "settings": FIXED_SETTINGS,
                "usage": safe_usage(generated.metadata),
            },
        )
        db.add(asset)
        db.flush()
        db.add(JobImage(job_id=identifier, asset_id=identity))
    # Persist an accounting row before any file exists; cancellation shares the write lock.
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        job, asset = db.get(Job, identifier), db.get(ImageAsset, identity)
        if job.status != "running" or asset.stage != "writing":
            return False
        path = Path(str(asset_path(database, asset)) + ".part")
        with path.open("wb") as stream:
            path.chmod(0o600)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        job.result = {"can_retry_save": True}
    return True


def finish_candidate(database, identifier):
    with database.session() as db:
        job = db.get(Job, identifier)
        if job.status not in {"running", "failed", "unknown"}:
            return
        asset = staged_asset(db, identifier)
        if not asset or asset.stage not in {"writing", "draft", "obsolete"}:
            raise ImageOutcomeUnknown()
        live_card(db, asset.target_card_id)
        path = asset_path(database, asset)
        source = path if path.exists() else Path(str(path) + ".part")
        try:
            encoded, width, height = normalize_image(source.read_bytes())
        except (OSError, HTTPException) as error:
            raise ImageOutcomeUnknown() from error
        identity, writing = asset.id, asset.stage == "writing"
    if writing:
        write_candidate(database, identity, encoded, width, height)
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        job = db.get(Job, identifier)
        if job.status not in {"running", "failed", "unknown"}:
            return
        asset = staged_asset(db, identifier)
        if not asset or asset.stage not in {"draft", "obsolete"}:
            raise ImageOutcomeUnknown()
        card = live_card(db, asset.target_card_id)
        job.status, job.error = "succeeded", None
        job.result = {"candidate": candidate_data(asset, card), "can_retry_save": False}


def mark_error(database, identifier, status, code, message):
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        job = db.get(Job, identifier)
        attempt = current_attempt(db, identifier)
        if attempt and attempt.status in {"reserved", "sent"}:
            attempt.status, attempt.error_code = status, code
        if job.status == "running":
            job.status, job.error = status, message


def run_image_job(database, identifier):
    try:
        with database.session() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            job = db.get(Job, identifier)
            if job.status != "running":
                return
            reserved_at = utc_now()
            require_available(db, database.settings, reserved_at)
            check_scope(db, job.payload)
            previous = current_attempt(db, identifier)
            # Reservations and counters use send time, never Job.created.
            attempt = ImageRequest(
                job_id=identifier,
                user_id=job.user_id,
                attempt_no=1 if not previous else previous.attempt_no + 1,
                request_key=job.payload["pending_key"],
                fingerprint=job.payload["pending_fingerprint"],
                reserved_at=reserved_at.replace(tzinfo=None),
                status="sent",
                model=job.payload["model"],
                settings=job.payload["settings"],
            )
            db.add(attempt)
            prompt, model = job.payload["prompt"], job.payload["model"]
        generated = ImageGenerator(database.settings, model).generate(prompt)
        with database.session() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            attempt = current_attempt(db, identifier)
            attempt.status, attempt.usage = "succeeded", safe_usage(generated.metadata)
        if stage_image(database, identifier, generated):
            finish_candidate(database, identifier)
    except HTTPException as error:
        mark_error(database, identifier, "failed", "unavailable", str(error.detail))
    except ImageProviderFailure as error:
        mark_error(
            database,
            identifier,
            "failed",
            error.code,
            "Провайдер отклонил запрос картинки. Проверьте настройки или повторите явно",
        )
    except ImageOutcomeUnknown:
        mark_error(database, identifier, "unknown", "unknown", UNKNOWN_MESSAGE)
    except Exception:
        with database.session() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            job = db.get(Job, identifier)
            asset = staged_asset(db, identifier)
            staged = False
            if (
                job.status == "running"
                and asset
                and asset.stage in {"writing", "draft", "obsolete"}
            ):
                path = asset_path(database, asset)
                source = path if path.exists() else Path(str(path) + ".part")
                try:
                    normalize_image(source.read_bytes())
                    with source.open("rb") as stream:
                        os.fsync(stream.fileno())
                    descriptor = os.open(source.parent, os.O_RDONLY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                    staged = True
                except (OSError, HTTPException):
                    asset.stage, asset.target_card_id = "discarded", None
                    asset.target_version, asset.slot = None, None
                    db.execute(delete(JobImage).where(JobImage.job_id == identifier))
                job.result = {"can_retry_save": staged}
        cleanup_image_assets(database)
        mark_error(
            database,
            identifier,
            "failed" if staged else "unknown",
            "local_save" if staged else "unknown",
            "Картинка получена. Повторите только локальное сохранение"
            if staged
            else UNKNOWN_MESSAGE,
        )


@router.post("/jobs/{identifier}/retry-image-save")
def retry_save(identifier: int, request: Request):
    database = request.app.state.db
    with database.session() as db:
        job = owned_job(db, identifier, require_user(request).id)
        if job.status not in {"failed", "unknown"} or not (job.result or {}).get("can_retry_save"):
            raise HTTPException(409, "Нет картинки для локального сохранения")
    try:
        finish_candidate(database, identifier)
    except ImageOutcomeUnknown:
        with database.session() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            job = owned_job(db, identifier, require_user(request).id)
            if job.status not in {"failed", "unknown"}:
                return job_data(job, db)
            job.status, job.error, job.result = (
                "unknown",
                UNKNOWN_MESSAGE,
                {"can_retry_save": False},
            )
            asset = staged_asset(db, identifier)
            if asset:
                asset.stage, asset.target_card_id = "discarded", None
                asset.target_version, asset.slot = None, None
            db.execute(delete(JobImage).where(JobImage.job_id == identifier))
        cleanup_image_assets(database)
    except (OSError, HTTPException):
        raise HTTPException(
            409, "Не удалось сохранить картинку локально. Попробуйте ещё раз"
        ) from None
    with database.session() as db:
        return job_data(owned_job(db, identifier, require_user(request).id), db)


def cancel_image_job(db, job):
    for reference in db.scalars(select(JobImage).where(JobImage.job_id == job.id)):
        asset = db.get(ImageAsset, reference.asset_id)
        if asset and asset.stage in {"writing", "draft", "obsolete"}:
            asset.stage, asset.target_card_id = "discarded", None
            asset.target_version, asset.slot = None, None
        db.delete(reference)
    job.status, job.result, job.error = "cancelled", None, None
    job.payload = {
        key: value
        for key, value in job.payload.items()
        if key in {"card_id", "topic_ids", "request_keys"}
    }


@router.post("/jobs/{identifier}/discard-image")
def discard(identifier: int, request: Request):
    database = request.app.state.db
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        cancel_image_job(db, owned_job(db, identifier, require_user(request).id))
    cleanup_image_assets(database)
    return {"discarded": True}


def recover_image_jobs(database):
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        for attempt in db.scalars(
            select(ImageRequest).where(ImageRequest.status.in_(["reserved", "sent"]))
        ):
            attempt.status, attempt.error_code = "unknown", "unknown"
        for job in db.scalars(
            select(Job).where(
                Job.kind == "generate_image", Job.status.in_(["running", "failed", "unknown"])
            )
        ):
            asset = staged_asset(db, job.id)
            if asset and asset.stage in {"draft", "obsolete"}:
                job.status, job.error, job.result = (
                    "failed",
                    "Повторите локальное сохранение",
                    {"can_retry_save": True},
                )
            elif job.status == "running" or (job.result or {}).get("can_retry_save"):
                job.status, job.error, job.result = (
                    "unknown",
                    UNKNOWN_MESSAGE,
                    {"can_retry_save": False},
                )
            if asset and asset.stage not in {"draft", "obsolete"}:
                db.execute(delete(JobImage).where(JobImage.job_id == job.id))
    cleanup_image_assets(database)

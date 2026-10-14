"""Private immutable illustrations, explicit candidates and reference-based cleanup."""

import hashlib
import io
import logging
import os
import uuid
import warnings
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from pydantic import Field, StrictInt
from sqlalchemy import delete, func, select, text

from .auth import require_user
from .models import (
    Attempt,
    Card,
    CardImage,
    ImageAsset,
    Job,
    JobImage,
    SessionCard,
    SessionImage,
    StudySession,
)
from .schemas import Strict

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])
Slot = Literal["question", "answer"]
MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000


class RebaseBody(Strict):
    version: StrictInt = Field(ge=1)


def root(database):
    directory = database.settings.data_dir / "question-images"
    if directory.is_symlink():
        raise ValueError("Private image directory must not be a symlink")
    directory.mkdir(exist_ok=True, mode=0o700)
    return directory


def asset_path(database, asset):
    directory = root(database)
    path = directory / asset.filename
    if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError("Invalid private image path")
    return path


def normalize_image(data):
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Картинка должна быть не больше 10 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as original:
                if (
                    original.format not in {"JPEG", "PNG", "WEBP"}
                    or getattr(original, "n_frames", 1) != 1
                ):
                    raise ValueError("Unsupported image")
                if original.width * original.height > MAX_PIXELS:
                    raise HTTPException(413, "Картинка должна быть не больше 20 мегапикселей")
                original.load()
                image = ImageOps.exif_transpose(original).convert("RGBA")
                image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                # A fresh pixel image strips EXIF/XMP/other decoder metadata, preserving alpha.
                clean = Image.new("RGBA", image.size)
                clean.paste(image)
                output = io.BytesIO()
                clean.save(output, format="WEBP", quality=85)
                return output.getvalue(), clean.width, clean.height
    except HTTPException:
        raise
    except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, "Загрузи статичную картинку JPEG, PNG или WebP") from None


def live_card(db, identifier):
    card = db.get(Card, identifier)
    if not card or card.status == "deleted":
        raise HTTPException(404, "Вопрос удалён")
    return card


def owned_candidate(db, identifier, user_id, allow_deleted=False):
    asset = db.get(ImageAsset, identifier)
    if not asset or asset.owner_user_id != user_id:
        raise HTTPException(404, "Кандидат не найден")
    if not allow_deleted and asset.stage not in {"draft", "obsolete"}:
        raise HTTPException(404, "Кандидат недоступен")
    return asset


def metadata(asset, url, alt=""):
    return {
        "asset_id": asset.id,
        "url": url,
        "alt": alt,
        "width": asset.width,
        "height": asset.height,
        "mime": asset.mime,
        "origin": asset.origin,
    }


def candidate_data(asset, card):
    apply = asset.stage == "draft" and asset.target_version == card.version
    return {
        "id": asset.id,
        "slot": asset.slot,
        "stage": asset.stage,
        "can_apply": apply,
        "reason": None if apply else "Вопрос изменён; проверь картинку и обнови привязку",
        "target_version": asset.target_version,
        **metadata(asset, f"/api/image-candidates/{asset.id}/preview"),
    }


def library_images(db, card_id):
    values = {}
    for link in db.scalars(select(CardImage).where(CardImage.card_id == card_id)):
        asset = db.get(ImageAsset, link.asset_id)
        if asset and asset.stage == "ready":
            values[link.slot] = metadata(
                asset, f"/api/cards/{card_id}/images/{link.slot}", link.alt
            )
    return values


def session_images(db, card, revealed):
    values = {}
    for link in db.scalars(select(SessionImage).where(SessionImage.session_card_id == card.id)):
        if link.slot == "answer" and not revealed:
            continue
        asset = db.get(ImageAsset, link.asset_id)
        if asset and asset.stage == "ready":
            values[link.slot] = metadata(
                asset,
                f"/api/study/{card.session_id}/cards/{card.position}/images/{link.slot}",
                link.alt,
            )
    return values


def copy_images(db, target, source_session_card_id=None, source_card_id=None):
    model = SessionImage if source_session_card_id else CardImage
    query = (
        select(model).where(model.session_card_id == source_session_card_id)
        if source_session_card_id
        else select(model).where(model.card_id == source_card_id)
    )
    for link in db.scalars(query):
        db.add(
            SessionImage(
                session_card_id=target.id, asset_id=link.asset_id, slot=link.slot, alt=link.alt
            )
        )


def apply_updates(db, card, updates, user_id):
    if updates is None:
        return
    for slot, update in updates.items():
        current = db.scalar(
            select(CardImage).where(CardImage.card_id == card.id, CardImage.slot == slot)
        )
        if update.asset_id is None:
            if current:
                db.delete(current)
            continue
        asset = db.get(ImageAsset, update.asset_id)
        if current and current.asset_id == update.asset_id and asset and asset.stage == "ready":
            current.alt = update.alt
            continue
        if not asset or asset.owner_user_id != user_id:
            raise HTTPException(404, "Кандидат не найден")
        if asset.target_card_id != card.id or asset.slot != slot:
            raise HTTPException(422, "Картинка подготовлена для другого вопроса или места")
        if asset.target_version != card.version or asset.stage == "obsolete":
            raise HTTPException(409, "Вопрос изменён; проверь картинку и обнови привязку")
        if asset.stage != "draft":
            raise HTTPException(409, "Картинка недоступна для сохранения")
        if current:
            current.asset_id, current.alt = asset.id, update.alt
        else:
            db.add(CardImage(card_id=card.id, asset_id=asset.id, slot=slot, alt=update.alt))
        asset.stage, asset.target_card_id, asset.target_version, asset.slot = (
            "ready",
            None,
            None,
            None,
        )
        for reference in db.scalars(
            select(JobImage).where(JobImage.asset_id == asset.id, JobImage.role == "candidate")
        ):
            job = db.get(Job, reference.job_id)
            if job:
                job.result = {**(job.result or {}), "applied_asset_id": asset.id}
                if job.kind == "generate_image":
                    job.status, job.error = "succeeded", None
                    job.result = {**job.result, "can_retry_save": False}
            db.delete(reference)
    db.flush()


def write_candidate(database, identifier, encoded, width, height):
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        asset = db.get(ImageAsset, identifier)
        if not asset or asset.stage != "writing":
            raise HTTPException(409, "Загрузка отменена")
        card = live_card(db, asset.target_card_id)
        path = asset_path(database, asset)
        temporary = Path(str(path) + ".part")
        with temporary.open("wb") as stream:
            temporary.chmod(0o600)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        asset.sha256, asset.size, asset.width, asset.height = (
            hashlib.sha256(encoded).hexdigest(),
            len(encoded),
            width,
            height,
        )
        asset.stage = "draft" if asset.target_version == card.version else "obsolete"
        return candidate_data(asset, card)


@router.post("/cards/{identifier}/image-candidates")
async def upload(
    identifier: int,
    request: Request,
    slot: Annotated[Slot, Form()],
    version: Annotated[int, Form(gt=0)],
    file: Annotated[UploadFile, File()],
):
    user = require_user(request)
    data = await file.read(MAX_BYTES + 1)
    encoded, width, height = normalize_image(data)
    database = request.app.state.db
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        card = live_card(db, identifier)
        if card.version != version:
            raise HTTPException(409, "Вопрос изменён. Обновите страницу")
        identity = uuid.uuid4().hex
        db.add(
            ImageAsset(
                id=identity,
                filename=f"{identity}.webp",
                owner_user_id=user.id,
                target_card_id=card.id,
                target_version=version,
                slot=slot,
            )
        )
    try:
        return write_candidate(database, identity, encoded, width, height)
    except Exception:
        cleanup_image_assets(database, recover_writing=True, recover_ids={identity})
        raise


@router.get("/cards/{identifier}/image-candidates")
def candidates(
    identifier: int,
    request: Request,
    cursor: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=50),
):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        card = live_card(db, identifier)
        rows = list(
            db.scalars(
                select(ImageAsset)
                .where(
                    ImageAsset.owner_user_id == user.id,
                    ImageAsset.target_card_id == identifier,
                    ImageAsset.stage.in_(["draft", "obsolete"]),
                )
                .order_by(ImageAsset.created.desc(), ImageAsset.id)
                .offset(cursor)
                .limit(limit + 1)
            )
        )
        for asset in rows:
            if asset.target_version != card.version:
                asset.stage = "obsolete"
        return {
            "items": [candidate_data(asset, card) for asset in rows[:limit]],
            "next_cursor": cursor + limit if len(rows) > limit else None,
        }


def serve(database, asset):
    path = asset_path(database, asset)
    if not path.is_file():
        raise HTTPException(404, "Изображение недоступно")
    return FileResponse(
        path,
        media_type="image/webp",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/image-candidates/{identifier}/preview")
def preview(identifier: str, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        asset = owned_candidate(db, identifier, user.id)
        live_card(db, asset.target_card_id)
        return serve(request.app.state.db, asset)


@router.post("/image-candidates/{identifier}/rebase")
def rebase(identifier: str, body: RebaseBody, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        asset = owned_candidate(db, identifier, user.id)
        card = live_card(db, asset.target_card_id)
        if card.version != body.version:
            raise HTTPException(409, "Вопрос изменён. Обновите страницу")
        asset.target_version, asset.stage = card.version, "draft"
        return candidate_data(asset, card)


@router.delete("/image-candidates/{identifier}")
def discard(identifier: str, request: Request):
    user = require_user(request)
    database = request.app.state.db
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        asset = owned_candidate(db, identifier, user.id, allow_deleted=True)
        if asset.stage == "ready":
            raise HTTPException(409, "Текущее изображение нельзя удалить как кандидат")
        asset.stage = "discarded" if asset.stage != "deleted" else "deleted"
        for reference in db.scalars(
            select(JobImage).where(JobImage.asset_id == asset.id, JobImage.role == "candidate")
        ):
            job = db.get(Job, reference.job_id)
            if job and job.kind == "generate_image":
                from .image_generation import cancel_image_job

                cancel_image_job(db, job)
            else:
                db.delete(reference)
        asset.target_card_id, asset.target_version, asset.slot = None, None, None
    cleanup_image_assets(database)
    return {"discarded": True}


@router.get("/cards/{identifier}/images/{slot}")
def library_image(identifier: int, slot: Slot, request: Request):
    with request.app.state.db.session() as db:
        live_card(db, identifier)
        link = db.scalar(
            select(CardImage).where(CardImage.card_id == identifier, CardImage.slot == slot)
        )
        if not link:
            raise HTTPException(404, "Изображение недоступно")
        return serve(request.app.state.db, db.get(ImageAsset, link.asset_id))


@router.get("/study/{identifier}/cards/{position}/images/{slot}")
def study_image(identifier: int, position: int, slot: Slot, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        session = db.get(StudySession, identifier)
        if not session or session.user_id != user.id or session.status == "deleted":
            raise HTTPException(404, "Занятие не найдено")
        card = db.scalar(
            select(SessionCard).where(
                SessionCard.session_id == identifier, SessionCard.position == position
            )
        )
        if not card:
            raise HTTPException(404, "Вопрос не найден")
        attempted = db.scalar(select(Attempt.id).where(Attempt.session_card_id == card.id))
        if slot == "answer" and not card.revealed and attempted is None:
            raise HTTPException(404, "Сначала откройте ответ")
        link = db.scalar(
            select(SessionImage).where(
                SessionImage.session_card_id == card.id, SessionImage.slot == slot
            )
        )
        if not link:
            raise HTTPException(404, "Изображение недоступно")
        return serve(request.app.state.db, db.get(ImageAsset, link.asset_id))


def invalidate_card_images(db, card_ids):
    db.execute(delete(CardImage).where(CardImage.card_id.in_(card_ids)))
    for asset in db.scalars(select(ImageAsset).where(ImageAsset.target_card_id.in_(card_ids))):
        asset.stage, asset.target_card_id, asset.target_version, asset.slot = (
            "discarded",
            None,
            None,
            None,
        )
        db.execute(
            delete(JobImage).where(JobImage.asset_id == asset.id, JobImage.role == "candidate")
        )


def cleanup_image_assets(database, recover_writing=False, recover_ids=None):
    deleting = []
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        for asset in db.scalars(select(ImageAsset).where(ImageAsset.stage != "deleted")):
            card = db.get(Card, asset.target_card_id) if asset.target_card_id else None
            candidate_live = card is not None and card.status != "deleted"
            can_recover = recover_writing and (recover_ids is None or asset.id in recover_ids)
            if asset.stage == "writing" and candidate_live and not can_recover:
                continue
            if asset.stage == "writing" and can_recover and candidate_live:
                path = asset_path(database, asset)
                temporary = Path(str(path) + ".part")
                try:
                    source = path if path.exists() else temporary
                    raw = source.read_bytes()
                    with Image.open(io.BytesIO(raw)) as image:
                        if (
                            image.format != "WEBP"
                            or getattr(image, "n_frames", 1) != 1
                            or max(image.size) > 2048
                        ):
                            raise ValueError("Incomplete image")
                        image.load()
                        asset.sha256, asset.size, asset.width, asset.height = (
                            hashlib.sha256(raw).hexdigest(),
                            len(raw),
                            image.width,
                            image.height,
                        )
                    if source == temporary:
                        temporary.replace(path)
                    asset.stage = "draft" if card.version == asset.target_version else "obsolete"
                except (ValueError, OSError):
                    asset.stage = "discarded"
            valid_candidate = candidate_live and asset.stage in {"draft", "obsolete"}
            referenced = any(
                db.scalar(select(func.count(model.id)).where(model.asset_id == asset.id))
                for model in (CardImage, SessionImage, JobImage)
            )
            if not valid_candidate and not referenced:
                asset.stage = "deleting"
                deleting.append(asset.id)
    for identifier in deleting:
        with database.session() as db:
            asset = db.get(ImageAsset, identifier)
            path = asset_path(database, asset)
        try:
            path.unlink(missing_ok=True)
            Path(str(path) + ".part").unlink(missing_ok=True)
        except OSError:
            logging.getLogger(__name__).warning(
                "Private image cleanup pending for asset %s", identifier
            )
            continue
        with database.session() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            asset = db.get(ImageAsset, identifier)
            if asset.stage == "deleting":
                asset.stage, asset.target_card_id, asset.target_version, asset.slot = (
                    "deleted",
                    None,
                    None,
                    None,
                )

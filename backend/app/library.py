import hashlib
import uuid
import warnings
from io import BytesIO
from pathlib import Path

import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from .auth import require_user
from .models import Card, CardSource, Document, Job, SourcePage, Subject, Topic
from .schemas import NameBody, TopicBody

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])
Image.MAX_IMAGE_PIXELS = 30_000_000


def get_or_404(db, model, identifier):
    value = db.get(model, identifier)
    if (
        value is None
        or getattr(value, "deleted", False)
        or (model in {Document, Card, Job} and value.status == "deleted")
    ):
        raise HTTPException(404, "Не найдено")
    return value


def subject_data(db, value):
    return {
        "id": value.id,
        "name": value.name,
        "topic_count": db.scalar(
            select(func.count(Topic.id)).where(
                Topic.subject_id == value.id, Topic.deleted.is_(False)
            )
        ),
    }


def topic_data(db, value, user_id=None):
    from .practice import practice_availability

    return {
        "id": value.id,
        "subject_id": value.subject_id,
        "name": value.name,
        "version": value.version,
        "practice_availability": practice_availability(db, value.id, user_id),
        "card_count": db.scalar(
            select(func.count(Card.id)).where(Card.topic_id == value.id, Card.status == "saved")
        ),
        "document_count": db.scalar(
            select(func.count(Document.id)).where(
                Document.topic_id == value.id, Document.status != "deleted"
            )
        ),
    }


@router.get("/subjects")
def subjects(request: Request):
    with request.app.state.db.session() as db:
        return [
            subject_data(db, value)
            for value in db.scalars(
                select(Subject).where(Subject.deleted.is_(False)).order_by(Subject.id)
            )
        ]


@router.post("/subjects")
def new_subject(body: NameBody, request: Request):
    with request.app.state.db.session() as db:
        value = Subject(name=body.name)
        db.add(value)
        db.flush()
        return subject_data(db, value)


@router.patch("/subjects/{identifier}")
def rename_subject(identifier: int, body: NameBody, request: Request):
    with request.app.state.db.session() as db:
        value = get_or_404(db, Subject, identifier)
        value.name = body.name
        return subject_data(db, value)


@router.get("/topics")
def topics(request: Request, subject_id: int | None = None):
    with request.app.state.db.session() as db:
        query = select(Topic).where(Topic.deleted.is_(False)).order_by(Topic.id)
        if subject_id is not None:
            query = query.where(Topic.subject_id == subject_id)
        return [topic_data(db, value, require_user(request).id) for value in db.scalars(query)]


@router.get("/topics/{identifier}")
def topic(identifier: int, request: Request):
    with request.app.state.db.session() as db:
        return topic_data(db, get_or_404(db, Topic, identifier), require_user(request).id)


@router.post("/topics")
def new_topic(body: TopicBody, request: Request):
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        get_or_404(db, Subject, body.subject_id)
        value = Topic(name=body.name, subject_id=body.subject_id)
        db.add(value)
        db.flush()
        return topic_data(db, value, require_user(request).id)


@router.patch("/topics/{identifier}")
def rename_topic(identifier: int, body: NameBody, request: Request):
    with request.app.state.db.session() as db:
        value = get_or_404(db, Topic, identifier)
        value.name = body.name
        return topic_data(db, value, require_user(request).id)


def inspect_upload(data: bytes):
    try:
        if data.startswith(b"%PDF-"):
            with pymupdf.open(stream=data, filetype="pdf") as pdf:
                if pdf.needs_pass or not 1 <= pdf.page_count <= 50:
                    raise ValueError("PDF должен быть без пароля и содержать от 1 до 50 страниц")
                for page in pdf:
                    page.get_text()
                return "application/pdf", pdf.page_count
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Поддерживаются PDF, JPEG, PNG и WebP")
                mime = Image.MIME[image.format]
                if image.width * image.height > 30_000_000:
                    raise ValueError("Изображение слишком большое (максимум 30 мегапикселей)")
                image.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()
            return mime, 1
    except (
        ValueError,
        UnidentifiedImageError,
        OSError,
        RuntimeError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise HTTPException(
            422,
            str(error)
            if isinstance(error, ValueError)
            else "Файл повреждён или имеет неподдерживаемый формат",
        ) from None


def document_data(db, value):
    job = db.scalar(
        select(Job)
        .where(Job.kind.in_(["ingest", "youtube"]))
        .order_by(Job.id.desc())
        .filter(Job.payload["document_id"].as_integer() == value.id)
    )
    return {
        "id": value.id,
        "topic_id": value.topic_id,
        "name": value.name,
        "mime": value.mime,
        "size": value.size,
        "page_count": value.page_count,
        "status": value.status,
        "job_id": job.id if job else None,
        "error": job.error if job else None,
        "source_url": value.source_url,
        "language": value.source_meta.get("language"),
        "is_generated": value.source_meta.get("is_generated"),
        "used_for_questions": db.scalar(
            select(CardSource.id)
            .join(SourcePage, CardSource.page_id == SourcePage.id)
            .where(SourcePage.document_id == value.id)
            .limit(1)
        )
        is not None,
        "warnings": [
            {"page": page.number, "messages": page.warnings}
            for page in db.scalars(
                select(SourcePage)
                .where(SourcePage.document_id == value.id)
                .order_by(SourcePage.number)
            )
            if page.warnings
        ],
    }


@router.get("/topics/{identifier}/documents")
def documents(identifier: int, request: Request):
    with request.app.state.db.session() as db:
        get_or_404(db, Topic, identifier)
        return [
            document_data(db, value)
            for value in db.scalars(
                select(Document)
                .where(Document.topic_id == identifier, Document.status != "deleted")
                .order_by(Document.id)
            )
        ]


@router.post("/topics/{identifier}/documents")
async def upload(identifier: int, request: Request, file: UploadFile):
    user = require_user(request)
    with request.app.state.db.session() as db:
        get_or_404(db, Topic, identifier)
    chunks, size = [], 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > request.app.state.settings.max_upload_bytes:
            raise HTTPException(413, "Максимальный размер файла — 20 МБ")
        chunks.append(chunk)
    data = b"".join(chunks)
    mime, page_count = inspect_upload(data)
    digest = hashlib.sha256(data).hexdigest()
    database = request.app.state.db
    with database.session() as db:
        duplicate = db.scalar(
            select(Document).where(Document.topic_id == identifier, Document.sha256 == digest)
        )
        if duplicate:
            return {**document_data(db, duplicate), "duplicate": True}
    filename = uuid.uuid4().hex
    path = database.settings.data_dir / "files" / filename
    path.write_bytes(data)
    try:
        with database.session() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            get_or_404(db, Topic, identifier)
            value = Document(
                topic_id=identifier,
                name=Path((file.filename or "Материал").replace("\\", "/")).name[:240],
                filename=filename,
                mime=mime,
                size=size,
                sha256=digest,
                page_count=page_count,
            )
            db.add(value)
            db.flush()
            topic = db.get(Topic, identifier)
            topic.version += 1
            db.add(Job(user_id=user.id, kind="ingest", payload={"document_id": value.id}))
            db.flush()
            return {**document_data(db, value), "duplicate": False}
    except IntegrityError:
        path.unlink(missing_ok=True)
        with database.session() as db:
            duplicate = db.scalar(
                select(Document).where(Document.topic_id == identifier, Document.sha256 == digest)
            )
            if not duplicate:
                raise
            return {**document_data(db, duplicate), "duplicate": True}
    except Exception:
        path.unlink(missing_ok=True)
        raise


@router.get("/documents/{identifier}/download")
def download(identifier: int, request: Request):
    with request.app.state.db.session() as db:
        value = get_or_404(db, Document, identifier)
        path = request.app.state.settings.data_dir / "files" / value.filename
        if not path.is_file():
            raise HTTPException(404, "Файл не найден в хранилище")
        return FileResponse(
            path,
            media_type=value.mime,
            filename=f"{value.name}.json" if value.source_url else value.name,
        )

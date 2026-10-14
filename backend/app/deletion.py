"""Library removal, keeping identifiers referenced by immutable study history."""

import hashlib
import json
import logging
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text

from .auth import require_user
from .caption_cache import lock as cache_lock
from .caption_cache import remove_transcript, retained_languages
from .library import get_or_404
from .models import Card, CardSource, Document, Job, SourcePage, Subject, Topic, now

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


class DeleteBody(BaseModel):
    revision: str | None = Field(default=None, max_length=64)


def preview(documents, cards, topics=None):
    signature = {
        "documents": sorted(d.id for d in documents),
        "cards": sorted((c.id, c.version) for c in cards),
    }
    if topics is not None:
        signature["topics"] = sorted(t.id for t in topics)
    return {
        **({"topic_count": len(topics)} if topics is not None else {}),
        "document_count": len(documents),
        "card_count": len(cards),
        "revision": hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest(),
    }


def check_confirmation(body, documents, cards, topics=None):
    if (
        body
        and body.revision is not None
        and body.revision != preview(documents, cards, topics)["revision"]
    ):
        raise HTTPException(409, "Состав изменился. Подтвердите удаление ещё раз")


def affected(db, topic_id=None, document_id=None, card_id=None):
    documents = (
        list(
            db.scalars(
                select(Document).where(
                    Document.status != "deleted",
                    Document.topic_id == topic_id
                    if topic_id is not None
                    else Document.id == document_id,
                )
            )
        )
        if card_id is None
        else []
    )
    doc_ids = {d.id for d in documents}
    if topic_id is not None:
        cards = list(
            db.scalars(select(Card).where(Card.topic_id == topic_id, Card.status != "deleted"))
        )
    elif card_id is not None:
        cards = [get_or_404(db, Card, card_id)]
    else:
        cards = list(
            db.scalars(
                select(Card)
                .join(CardSource)
                .join(SourcePage, SourcePage.id == CardSource.page_id)
                .where(SourcePage.document_id.in_(doc_ids), Card.status != "deleted")
                .distinct()
            )
        )
    return documents, cards


def affected_subject(db, identifier):
    topics = list(
        db.scalars(select(Topic).where(Topic.subject_id == identifier, Topic.deleted.is_(False)))
    )
    ids = [topic.id for topic in topics]
    documents = list(
        db.scalars(select(Document).where(Document.topic_id.in_(ids), Document.status != "deleted"))
    )
    cards = list(db.scalars(select(Card).where(Card.topic_id.in_(ids), Card.status != "deleted")))
    return topics, documents, cards


def cleanup_document_files(database, document):
    path = database.settings.data_dir / "files" / document.filename
    complete = True
    for candidate in (path, path.with_suffix(".tmp")):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            complete = False
            logging.getLogger(__name__).warning(
                "Deletion file cleanup pending for document %s", document.id
            )
    video = document.source_meta.get("video_id")
    if not video and document.source_url:
        video = parse_qs(urlsplit(document.source_url).query).get("v", [None])[0]
    if video:
        with cache_lock:
            language = document.source_meta.get("language")
            languages = [language] if language else retained_languages(database.settings)
            for language in languages:
                # A pending or ready document in any subject keeps its shared transcript.
                with database.session() as db:
                    retained = db.scalar(
                        select(Document.id)
                        .where(
                            Document.status != "deleted",
                            Document.source_url == document.source_url,
                            Document.source_meta["language"].as_string() == language,
                        )
                        .limit(1)
                    )
                if retained is None:
                    try:
                        remove_transcript(database.settings, video, language)
                    except OSError:
                        complete = False
                        logging.getLogger(__name__).warning(
                            "Transcript cleanup pending for document %s", document.id
                        )
    return complete


def cleanup_deleted_files(database):
    with database.session() as db:
        for document in db.scalars(select(Document).where(Document.status == "deleted")):
            cleanup_document_files(database, document)


def remove(db, database, documents, cards, topic_id=None, topic_ids=(), subject_id=None):
    removed_topics = set(topic_ids) | ({topic_id} if topic_id is not None else set())
    doc_ids, card_ids = {d.id for d in documents}, {c.id for c in cards}
    from .image_generation import cancel_image_job

    for job in db.scalars(select(Job).where(Job.kind == "generate_image")):
        if job.payload.get("card_id") in card_ids:
            cancel_image_job(db, job)
    for job in db.scalars(select(Job).where(Job.kind == "regenerate")):
        if job.payload.get("card_id") in card_ids or removed_topics.intersection(
            job.payload.get("topic_ids", [])
        ):
            job.status, job.result, job.error = "cancelled", None, None
            job.payload = {
                k: v
                for k, v in job.payload.items()
                if k in {"card_id", "topic_ids", "base_version", "request_keys"}
            }
    for job in db.scalars(select(Job).where(Job.status.in_(["queued", "running", "failed"]))):
        payload = job.payload
        topics = payload.get("topics", [])
        referenced_documents = {s["document_id"] for t in topics for s in t.get("sources", [])}
        referenced_cards = {c["id"] for c in payload.get("cards", [])}
        touched = (
            job.kind in {"ingest", "youtube"}
            and payload.get("document_id") in doc_ids
            or job.kind == "generate"
            and (
                bool(referenced_documents & doc_ids)
                or any(t["id"] in removed_topics for t in topics)
            )
            or job.kind == "prepare_quiz"
            and (
                bool(referenced_cards & card_ids)
                or bool(removed_topics.intersection(payload.get("topic_ids", [])))
            )
        )
        if touched:
            job.status, job.error, job.updated = (
                "cancelled",
                "Материал или вопрос удалён. Задача отменена",
                now(),
            )
    from .question_images import cleanup_image_assets, invalidate_card_images

    invalidate_card_images(db, card_ids)
    db.execute(delete(CardSource).where(CardSource.card_id.in_(card_ids)))
    for card in cards:
        card.status = "deleted"
        card.version += 1
    db.execute(delete(SourcePage).where(SourcePage.document_id.in_(doc_ids)))
    for document in documents:
        # Release the deduplication key so a corrected upload of the same bytes/link is allowed.
        document.status, document.sha256 = "deleted", f"deleted:{document.id}"
        document.source_meta = {
            key: document.source_meta[key]
            for key in ("video_id", "language")
            if key in document.source_meta
        }
        document.size, document.page_count = 0, 0
    if removed_topics:
        for identifier in removed_topics:
            db.get(Topic, identifier).deleted = True
    elif documents:
        db.get(Topic, documents[0].topic_id).version += 1
    if subject_id is not None:
        db.get(Subject, subject_id).deleted = True
    db.flush()
    # Commit cancellation before removing files: workers must observe the tombstone first.
    db.commit()
    cleanup_image_assets(database)
    cleanup = documents
    if subject_id is not None:
        all_topics = select(Topic.id).where(Topic.subject_id == subject_id)
        cleanup = list(
            db.scalars(
                select(Document).where(
                    Document.topic_id.in_(all_topics), Document.status == "deleted"
                )
            )
        )
    elif removed_topics:
        cleanup = list(
            db.scalars(
                select(Document).where(
                    Document.topic_id.in_(removed_topics), Document.status == "deleted"
                )
            )
        )
    pending = False
    for document in cleanup:
        if not cleanup_document_files(database, document):
            pending = True
    return {
        "deleted": True,
        "card_count": len(cards),
        "document_count": len(documents),
        "cleanup_pending": pending,
    }


@router.get("/topics/{identifier}/deletion")
def topic_preview(identifier: int, request: Request):
    with request.app.state.db.session() as db:
        get_or_404(db, Topic, identifier)
        documents, cards = affected(db, topic_id=identifier)
        return preview(documents, cards)


@router.get("/documents/{identifier}/deletion")
def document_preview(identifier: int, request: Request):
    with request.app.state.db.session() as db:
        get_or_404(db, Document, identifier)
        documents, cards = affected(db, document_id=identifier)
        return preview(documents, cards)


@router.delete("/topics/{identifier}")
def delete_topic(identifier: int, request: Request, body: DeleteBody | None = None):
    database = request.app.state.db
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        get_or_404(db, Topic, identifier)
        documents, cards = affected(db, topic_id=identifier)
        check_confirmation(body, documents, cards)
        return remove(db, database, documents, cards, topic_id=identifier)


@router.delete("/documents/{identifier}")
def delete_document(identifier: int, request: Request, body: DeleteBody | None = None):
    database = request.app.state.db
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        get_or_404(db, Document, identifier)
        documents, cards = affected(db, document_id=identifier)
        check_confirmation(body, documents, cards)
        return remove(db, database, documents, cards)


@router.delete("/cards/{identifier}")
def delete_card(identifier: int, request: Request):
    database = request.app.state.db
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        documents, cards = affected(db, card_id=identifier)
        return remove(db, database, documents, cards)


@router.get("/subjects/{identifier}/deletion")
def subject_preview(identifier: int, request: Request):
    with request.app.state.db.session() as db:
        get_or_404(db, Subject, identifier)
        topics, documents, cards = affected_subject(db, identifier)
        return preview(documents, cards, topics)


@router.delete("/subjects/{identifier}")
def delete_subject(identifier: int, request: Request, body: DeleteBody | None = None):
    database = request.app.state.db
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        get_or_404(db, Subject, identifier)
        topics, documents, cards = affected_subject(db, identifier)
        check_confirmation(body, documents, cards, topics)
        result = remove(
            db, database, documents, cards, topic_ids=[t.id for t in topics], subject_id=identifier
        )
        return {**result, "topic_count": len(topics)}

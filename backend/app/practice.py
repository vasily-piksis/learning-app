"""Read-only practice availability, shared by the library and study selection."""

import hashlib
import json

from sqlalchemy import select

from .exercises import QUESTION_TYPES, validate_exercise
from .models import Card, Document, Job, SourcePage
from .quiz import quiz_ready


def ready_for_quiz(card):
    if card.question_type == "choice":
        return quiz_ready(card)
    try:
        return bool(validate_exercise(card.question_type, card.exercise) and card.answer.strip())
    except ValueError:
        return False


def material_fingerprint(db, topic_id):
    documents = list(
        db.scalars(
            select(Document)
            .where(Document.topic_id == topic_id, Document.status != "deleted")
            .order_by(Document.id)
        )
    )
    pages = list(
        db.scalars(
            select(SourcePage)
            .where(SourcePage.document_id.in_([d.id for d in documents]))
            .order_by(SourcePage.document_id, SourcePage.number)
        )
    )
    value = {
        "documents": [(d.id, d.sha256, d.status) for d in documents],
        "pages": [
            (
                p.document_id,
                p.number,
                hashlib.sha256(p.text.encode()).hexdigest(),
                p.language,
                p.start_seconds,
                p.end_seconds,
            )
            for p in pages
        ],
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def practice_availability(db, topic_id, user_id=None):
    cards = list(
        db.scalars(select(Card).where(Card.topic_id == topic_id, Card.status != "deleted"))
    )
    source_texts = db.scalars(
        select(SourcePage.text)
        .join(Document)
        .where(Document.topic_id == topic_id, Document.status == "ready")
    )
    has_materials = any(value.strip() for value in source_texts)
    result = {}
    for method in ("flashcard", *QUESTION_TYPES):
        relevant = (
            cards if method == "flashcard" else [c for c in cards if c.question_type == method]
        )
        result[method] = {
            "ready_count": sum(
                c.status == "saved"
                and (bool(c.answer.strip()) if method == "flashcard" else ready_for_quiz(c))
                for c in relevant
            ),
            "draft_count": sum(c.status == "draft" for c in relevant),
            "needs_options_count": sum(c.status == "saved" and not quiz_ready(c) for c in relevant)
            if method == "choice"
            else 0,
            "preparation_job_id": None,
            "preparation_status": None,
            "has_ready_materials": has_materials,
            "last_outcome": None,
        }
    if user_id is None:
        return result
    current = material_fingerprint(db, topic_id)
    for job in db.scalars(
        select(Job)
        .where(
            Job.user_id == user_id,
            Job.kind.in_(["generate", "prepare_quiz"]),
            Job.status != "deleted",
        )
        .order_by(Job.id.desc())
    ):
        topic = next((t for t in job.payload.get("topics", []) if t["id"] == topic_id), None)
        if topic is None and topic_id not in job.payload.get("topic_ids", []):
            continue
        methods = (
            job.payload.get("question_types", ["choice"]) if job.kind == "generate" else ["choice"]
        )
        if job.payload.get("mode") == "flashcard":
            methods = ["flashcard"]
        for method in methods:
            if method not in result:
                continue
            item = result[method]
            unapplied = (
                job.kind == "prepare_quiz"
                and job.status == "succeeded"
                and bool(
                    set((job.result or {}).get("card_ids", []))
                    - set((job.result or {}).get("applied_card_ids", []))
                )
                and not (job.result or {}).get("discarded")
            )
            if item["preparation_job_id"] is None and (
                job.status in {"queued", "running", "failed"} or unapplied
            ):
                item["preparation_job_id"], item["preparation_status"] = job.id, job.status
            outcomes = (job.result or {}).get("outcomes_by_topic", [])
            outcome = next((v for v in outcomes if v["topic_id"] == topic_id), None)
            if outcome and item["last_outcome"] is None:
                reason = next(
                    (
                        v["reason"]
                        for v in outcome.get("unsupported_types", [])
                        if v["question_type"] == method
                    ),
                    None,
                )
                if reason:
                    item["last_outcome"] = {
                        "method": method,
                        "source_fingerprint": outcome["source_fingerprint"],
                        "reason": reason,
                        "stale": current != outcome["source_fingerprint"],
                    }
    return result

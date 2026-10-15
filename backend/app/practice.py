"""Read-only practice availability, shared by the library and study selection."""

import hashlib
import json

from sqlalchemy import select

from .exercises import QUESTION_TYPES, validate_exercise
from .models import Card, Document, Job, SourcePage
from .quiz import quiz_ready


def ready_for_quiz(card, db=None):
    if card.question_type == "choice":
        return quiz_ready(card)
    try:
        if card.question_type == "picture_description":
            if db is None:
                return False
            from .picture_responses import validate_picture_card

            return bool(validate_picture_card(db, card))
        return bool(validate_exercise(card.question_type, card.exercise) and card.answer.strip())
    except (ValueError, OSError):
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


def practice_availability(db, topic_id, user_id=None, settings=None):
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
    for method in ("flashcard", *QUESTION_TYPES, "free_response", "picture_description"):
        relevant = (
            [c for c in cards if c.question_type not in {"free_response", "picture_description"}]
            if method == "flashcard"
            else [c for c in cards if c.question_type == method]
        )
        result[method] = {
            "ready_count": sum(
                c.status == "saved"
                and (bool(c.answer.strip()) if method == "flashcard" else ready_for_quiz(c, db))
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
    from .evaluations import runtime_available

    result["free_response"]["runtime_unavailable"] = settings is None or not runtime_available(
        settings
    )
    result["picture_description"]["runtime_unavailable"] = (
        settings is None or not runtime_available(settings, "picture_description")
    )
    from .models import CardImage, ImageAsset

    result["picture_description"]["has_ready_materials"] = bool(
        db.scalar(
            select(CardImage.id)
            .join(Card)
            .join(ImageAsset, ImageAsset.id == CardImage.asset_id)
            .where(
                Card.topic_id == topic_id,
                Card.status != "deleted",
                CardImage.image_role == "source",
                ImageAsset.stage == "ready",
            )
        )
    )
    if user_id is None:
        return result
    for job in db.scalars(
        select(Job)
        .where(Job.user_id == user_id, Job.kind == "regenerate", Job.status != "deleted")
        .order_by(Job.id.desc())
    ):
        if not job.payload.get("picture_source") or topic_id not in job.payload.get(
            "topic_ids", []
        ):
            continue
        current_card = db.get(Card, job.payload.get("card_id"))
        if (
            not current_card
            or current_card.status == "deleted"
            or current_card.version != job.payload.get("base_version")
        ):
            continue
        if job.status in {"queued", "running", "failed"} or (
            job.status == "succeeded" and (job.result or {}).get("candidate")
        ):
            result["picture_description"]["preparation_job_id"] = job.id
            result["picture_description"]["preparation_status"] = job.status
            break
    current = material_fingerprint(db, topic_id)
    seen_outcomes = set()
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
            if outcome and method not in seen_outcomes:
                seen_outcomes.add(method)
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

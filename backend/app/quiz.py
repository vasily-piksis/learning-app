import json

from fastapi import HTTPException
from sqlalchemy import select

from .models import Card, Job
from .schemas import QuizOptions


def correct_indices(card):
    if isinstance(card, dict):
        indices, index = card.get("correct_indices"), card.get("correct_index")
    else:
        indices, index = card.correct_indices, card.correct_index
    return indices or ([] if index is None else [index])


def quiz_ready(card):
    if getattr(card, "question_type", "choice") != "choice":
        return False
    return (
        2 <= len(card.options) <= 6
        and len(set(card.options)) == len(card.options)
        and bool(correct_indices(card))
        and len(set(correct_indices(card))) == len(correct_indices(card))
        and all(0 <= index < len(card.options) for index in correct_indices(card))
    )


def preparation_job(db, user_id, topic_ids, snapshots):
    signature = [
        (card["id"], card["version"], json.dumps(card.get("sources", []), sort_keys=True))
        for card in snapshots
    ]
    for job in db.scalars(
        select(Job)
        .where(
            Job.kind == "prepare_quiz",
            Job.user_id == user_id,
            Job.status.in_(["queued", "running", "failed"]),
        )
        .order_by(Job.id.desc())
    ):
        if (
            job.payload["topic_ids"] == topic_ids
            and [
                (card["id"], card["version"], json.dumps(card.get("sources", []), sort_keys=True))
                for card in job.payload.get("cards", [])
            ]
            == signature
        ):
            return job
    sources = {
        (source["document_id"], source["page"]): source
        for card in snapshots
        for source in card["sources"]
    }
    if sum(len(source.get("text", "")) for source in sources.values()) > 100000:
        raise HTTPException(422, "Материалы превышают 100 000 символов. Выберите меньше документов")
    job = Job(
        user_id=user_id, kind="prepare_quiz", payload={"topic_ids": topic_ids, "cards": snapshots}
    )
    db.add(job)
    db.flush()
    return job


def prepare_options(ai, payload, before_each=None):
    results = []
    for snapshot in payload["cards"]:
        if before_each is not None:
            before_each()
        result = QuizOptions.model_validate(ai.prepare_quiz(snapshot))
        if result.card_id != snapshot["id"] or (
            len(result.correct_indices) == 1
            and result.options[result.correct_indices[0]] != snapshot["answer"]
        ):
            raise ValueError("Модель изменила правильный ответ при подготовке теста")
        results.append(result)
    return results


def validate_preparation(db, payload):
    cards = [db.get(Card, snapshot["id"]) for snapshot in payload["cards"]]
    if any(
        card is None
        or card.version != snapshot["version"]
        or card.status != "saved"
        or card.question_type != "choice"
        for card, snapshot in zip(cards, payload["cards"], strict=True)
    ):
        raise ValueError("Вопрос изменён во время подготовки теста. Запустите тест заново")
    return cards


def save_options(db, payload, results):
    cards = validate_preparation(db, payload)
    for card, result in zip(cards, results, strict=True):
        card.mode, card.options, card.correct_index = "quiz", result.options, result.correct_index
        card.correct_indices = result.correct_indices
        card.version += 1

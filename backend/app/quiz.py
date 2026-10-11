from fastapi import HTTPException
from sqlalchemy import select

from .models import Card, Job
from .schemas import QuizOptions


def quiz_ready(card):
    return (
        2 <= len(card.options) <= 6
        and len(set(card.options)) == len(card.options)
        and card.correct_index is not None
        and 0 <= card.correct_index < len(card.options)
    )


def preparation_job(db, user_id, topic_ids, snapshots):
    signature = [(card["id"], card["version"]) for card in snapshots]
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
            and [(card["id"], card["version"]) for card in job.payload["cards"]] == signature
        ):
            return job
    if sum(len(s.get("text", "")) for card in snapshots for s in card["sources"]) > 100000:
        raise HTTPException(422, "Материалы превышают 100 000 символов. Выберите меньше документов")
    job = Job(
        user_id=user_id, kind="prepare_quiz", payload={"topic_ids": topic_ids, "cards": snapshots}
    )
    db.add(job)
    db.flush()
    return job


def prepare_options(ai, payload):
    results = []
    for snapshot in payload["cards"]:
        result = QuizOptions.model_validate(ai.prepare_quiz(snapshot))
        if (
            result.card_id != snapshot["id"]
            or result.options[result.correct_index] != snapshot["answer"]
        ):
            raise ValueError("Модель изменила правильный ответ при подготовке теста")
        results.append(result)
    return results


def save_options(db, payload, results):
    cards = [db.get(Card, snapshot["id"]) for snapshot in payload["cards"]]
    if any(
        card is None or card.version != snapshot["version"] or card.status != "saved"
        for card, snapshot in zip(cards, payload["cards"], strict=True)
    ):
        raise ValueError("Вопрос изменён во время подготовки теста. Запустите тест заново")
    for card, result in zip(cards, results, strict=True):
        card.mode, card.options, card.correct_index = "quiz", result.options, result.correct_index
        card.version += 1

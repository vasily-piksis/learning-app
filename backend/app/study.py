import random
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictInt
from sqlalchemy import delete, func, select, text

from .auth import require_user
from .jobs import card_data, job_data
from .library import get_or_404
from .models import Attempt, Card, Explanation, Job, SessionCard, StudySession, Topic, now
from .quiz import correct_indices, preparation_job, quiz_ready
from .sources import available_sources

router = APIRouter(prefix="/api/study", dependencies=[Depends(require_user)])


class StartBody(BaseModel):
    topic_ids: list[int] = Field(min_length=1, max_length=30)
    mode: Literal["quiz", "flashcard"]


class DeleteHistoryBody(BaseModel):
    session_ids: list[Annotated[StrictInt, Field(gt=0)]] = Field(min_length=1, max_length=200)


class PositionBody(BaseModel):
    position: int = Field(ge=0)


class AnswerBody(PositionBody):
    idempotency_key: str = Field(min_length=1, max_length=80)
    choice: StrictInt | None = Field(default=None, ge=0)
    choices: list[StrictInt] | None = None
    remembered: bool | None = None


class ExplainBody(PositionBody):
    question: str = Field(
        default="Объясни проще, как ребёнку пяти лет", min_length=1, max_length=2000
    )
    parent_id: int | None = None


def owned(db, identifier, user_id):
    value = get_or_404(db, StudySession, identifier)
    if value.user_id != user_id or value.status == "deleted":
        raise HTTPException(404, "Не найдено")
    return value


def at_position(db, session_id, position):
    value = db.scalar(
        select(SessionCard).where(
            SessionCard.session_id == session_id, SessionCard.position == position
        )
    )
    if not value:
        raise HTTPException(404, "Карточка занятия не найдена")
    return value


def public_card(snapshot, revealed=False, db=None):
    value = {
        **snapshot,
        "sources": [{k: v for k, v in s.items() if k != "text"} for s in snapshot["sources"]],
    }
    if db is not None:
        value["sources"] = available_sources(db, value["sources"])
    value["correct_indices"] = correct_indices(snapshot)
    value["multiple_answers"] = len(value["correct_indices"]) > 1
    if not revealed:
        value.pop("correct_indices", None)
        value.pop("answer", None)
        value.pop("correct_index", None)
    return value


def session_data(db, session, full=False):
    count = db.scalar(
        select(func.count(SessionCard.id)).where(SessionCard.session_id == session.id)
    )
    attempts = list(
        db.scalars(
            select(Attempt)
            .join(SessionCard, Attempt.session_card_id == SessionCard.id)
            .where(SessionCard.session_id == session.id)
        )
    )
    topic_names = [db.get(Topic, identifier).name for identifier in session.topic_ids]
    result = {
        "id": session.id,
        "topic_ids": session.topic_ids,
        "topic_names": topic_names,
        "active_topic_ids": [
            identifier for identifier in session.topic_ids if not db.get(Topic, identifier).deleted
        ],
        "mode": session.mode,
        "position": session.position,
        "status": session.status,
        "count": count,
        "answered": len(attempts),
        "correct": sum(a.correct for a in attempts),
        "created": session.created.isoformat(),
    }
    if full:
        result["card"] = None
        result["review"] = []
        for attempt in attempts:
            answered_card = db.get(SessionCard, attempt.session_card_id)
            result["review"].append(
                {
                    "position": answered_card.position,
                    "card": public_card(answered_card.snapshot, True, db),
                    "correct": attempt.correct,
                    **attempt.value,
                }
            )
        result["review"].sort(key=lambda item: item["position"])
        if session.position < count:
            current = at_position(db, session.id, session.position)
            result["card"] = {
                **public_card(current.snapshot, current.revealed, db),
                "session_card_id": current.id,
                "revealed": current.revealed,
            }
    return result


def new_session(db, user_id, topics, mode, snapshots):
    random.SystemRandom().shuffle(snapshots)
    value = StudySession(user_id=user_id, topic_ids=topics, mode=mode)
    db.add(value)
    db.flush()
    for position, snapshot in enumerate(snapshots):
        db.add(SessionCard(session_id=value.id, position=position, snapshot=snapshot))
    db.flush()
    return session_data(db, value, full=True)


@router.post("")
def start(body: StartBody, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        for identifier in body.topic_ids:
            get_or_404(db, Topic, identifier)
        cards = list(
            db.scalars(
                select(Card).where(
                    Card.topic_id.in_(body.topic_ids),
                    Card.status == "saved",
                )
            )
        )
        if not cards:
            raise HTTPException(422, "Сначала сохраните карточки выбранного формата")
        if len(cards) > 300:
            raise HTTPException(
                422, "Для одного занятия выберите меньше тем (максимум 300 карточек)"
            )
        if body.mode == "quiz":
            missing = [
                card_data(db, card, include_text=True)
                for card in sorted(cards, key=lambda c: c.id)
                if not quiz_ready(card)
            ]
            if missing:
                job = preparation_job(db, user.id, sorted(set(body.topic_ids)), missing)
                return JSONResponse(status_code=202, content={"preparation_job": job_data(job)})
        snapshots = [card_data(db, card, include_text=True) for card in cards]
        if body.mode == "flashcard":
            for snapshot in snapshots:
                snapshot.update(
                    mode="flashcard",
                    options=[],
                    correct_index=None,
                    correct_indices=[],
                    multiple_answers=False,
                )
        else:
            for snapshot in snapshots:
                snapshot["mode"] = "quiz"
        return new_session(
            db,
            user.id,
            list(dict.fromkeys(body.topic_ids)),
            body.mode,
            snapshots,
        )


@router.get("")
def history(request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        return [
            session_data(db, value)
            for value in db.scalars(
                select(StudySession)
                .where(StudySession.user_id == user.id, StudySession.status != "deleted")
                .order_by(StudySession.id.desc())
                .limit(200)
            )
        ]


@router.post("/delete")
def delete_history(body: DeleteHistoryBody, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        identifiers = set(body.session_ids)
        sessions = list(
            db.scalars(
                select(StudySession).where(
                    StudySession.id.in_(identifiers),
                    StudySession.user_id == user.id,
                    StudySession.status != "deleted",
                )
            )
        )
        if len(sessions) != len(identifiers):
            raise HTTPException(404, "Занятие не найдено. Обновите историю")
        card_ids = select(SessionCard.id).where(SessionCard.session_id.in_(identifiers))
        for job in db.scalars(
            select(Job).where(
                Job.kind == "explain",
                Job.payload["session_card_id"].as_integer().in_(card_ids),
            )
        ):
            # Keep the ID reserved so an in-flight worker cannot write into a new job.
            job.status, job.payload, job.result, job.error = "deleted", {}, None, None
        db.execute(delete(Explanation).where(Explanation.session_card_id.in_(card_ids)))
        db.execute(delete(Attempt).where(Attempt.session_card_id.in_(card_ids)))
        db.execute(delete(SessionCard).where(SessionCard.session_id.in_(identifiers)))
        for session in sessions:
            # Empty tombstones also prevent old browser tabs from reaching reused IDs.
            session.status, session.topic_ids, session.position = "deleted", [], 0
        return {"deleted_count": len(sessions)}


@router.get("/{identifier}")
def resume(identifier: int, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        return session_data(db, owned(db, identifier, user.id), full=True)


@router.post("/{identifier}/reveal")
def reveal(identifier: int, body: PositionBody, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        session = owned(db, identifier, user.id)
        if (
            session.mode != "flashcard"
            or session.position != body.position
            or session.status != "active"
        ):
            raise HTTPException(409, "Обновите занятие: текущая карточка изменилась")
        card = at_position(db, identifier, body.position)
        card.revealed = True
        return session_data(db, session, full=True)


def feedback(attempt, card, session_id, db=None):
    return {
        "session_id": session_id,
        "position": card.position,
        "correct": attempt.correct,
        "card": public_card(card.snapshot, True, db),
        "next_position": card.position + 1,
    }


@router.post("/{identifier}/answer")
def answer(identifier: int, body: AnswerBody, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        session = owned(db, identifier, user.id)
        card = at_position(db, identifier, body.position)
        value = {"choice": body.choice, "remembered": body.remembered}
        if body.choices is not None:
            value["choices"] = sorted(body.choices)
        prior = db.scalar(
            select(Attempt).where(
                Attempt.user_id == user.id, Attempt.idempotency_key == body.idempotency_key
            )
        )
        if prior:
            if prior.session_card_id != card.id or prior.value != value:
                raise HTTPException(409, "Идентификатор запроса уже использован для другого ответа")
            return feedback(prior, card, session.id, db)
        if session.position != body.position or session.status != "active":
            raise HTTPException(409, "Ответ уже сохранён в другой вкладке. Обновите занятие")
        if session.mode == "quiz":
            selected = (
                body.choices
                if body.choices is not None
                else ([] if body.choice is None else [body.choice])
            )
            if (
                not selected
                or len(set(selected)) != len(selected)
                or any(not 0 <= index < len(card.snapshot["options"]) for index in selected)
                or body.remembered is not None
                or (body.choices is not None and body.choice is not None)
                or (len(correct_indices(card.snapshot)) == 1 and len(selected) != 1)
            ):
                raise HTTPException(422, "Выберите допустимые варианты ответа")
            correct = set(selected) == set(correct_indices(card.snapshot))
        else:
            if not card.revealed:
                raise HTTPException(409, "Сначала откройте ответ")
            if body.remembered is None or body.choice is not None or body.choices is not None:
                raise HTTPException(422, "Отметьте, помните ли ответ")
            correct = body.remembered
        attempt = Attempt(
            user_id=user.id,
            session_card_id=card.id,
            idempotency_key=body.idempotency_key,
            value=value,
            correct=correct,
        )
        db.add(attempt)
        session.position += 1
        session.updated = now()
        count = db.scalar(
            select(func.count(SessionCard.id)).where(SessionCard.session_id == identifier)
        )
        if session.position >= count:
            session.status = "completed"
        return feedback(attempt, card, identifier, db)


@router.post("/{identifier}/repeat")
def repeat(identifier: int, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        session = owned(db, identifier, user.id)
        cards = list(
            db.scalars(
                select(SessionCard)
                .join(Attempt, Attempt.session_card_id == SessionCard.id)
                .where(SessionCard.session_id == identifier, Attempt.correct.is_(False))
            )
        )
        if not cards:
            raise HTTPException(422, "Пока нет карточек для повторения")
        return new_session(
            db, user.id, session.topic_ids, session.mode, [card.snapshot for card in cards]
        )


@router.get("/{identifier}/explanations")
def explanations(identifier: int, position: int, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        owned(db, identifier, user.id)
        card = at_position(db, identifier, position)
        return [
            {
                "id": value.id,
                "question": value.question,
                "parent_id": value.parent_id,
                **value.result,
                "sources": available_sources(db, value.result["sources"]),
            }
            for value in db.scalars(
                select(Explanation)
                .where(Explanation.user_id == user.id, Explanation.session_card_id == card.id)
                .order_by(Explanation.id)
            )
        ]


@router.get("/{identifier}/explanation-jobs")
def explanation_jobs(identifier: int, position: int, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        owned(db, identifier, user.id)
        card = at_position(db, identifier, position)
        return [
            job_data(job, db)
            for job in db.scalars(
                select(Job)
                .where(
                    Job.user_id == user.id,
                    Job.kind == "explain",
                    Job.payload["session_card_id"].as_integer() == card.id,
                )
                .order_by(Job.id.desc())
            )
        ]


@router.post("/{identifier}/explain")
def explain(identifier: int, body: ExplainBody, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        owned(db, identifier, user.id)
        card = at_position(db, identifier, body.position)
        attempted = db.scalar(select(Attempt.id).where(Attempt.session_card_id == card.id))
        if not card.revealed and attempted is None:
            raise HTTPException(409, "Сначала откройте ответ или ответьте на тест")
        if not body.question.strip():
            raise HTTPException(422, "Напишите вопрос")
        pending = db.scalar(
            select(Job).where(
                Job.user_id == user.id,
                Job.kind == "explain",
                Job.status.in_(["queued", "running"]),
                Job.payload["session_card_id"].as_integer() == card.id,
            )
        )
        if pending:
            raise HTTPException(409, "Дождитесь текущего объяснения")
        if body.parent_id:
            parent = db.get(Explanation, body.parent_id)
            if not parent or parent.user_id != user.id or parent.session_card_id != card.id:
                raise HTTPException(422, "Уточнение должно относиться к этой карточке")
        previous = list(
            db.scalars(
                select(Explanation)
                .where(Explanation.user_id == user.id, Explanation.session_card_id == card.id)
                .order_by(Explanation.id)
            )
        )
        context = [{"question": e.question, **e.result} for e in previous]
        if sum(len(str(item)) for item in context) > 60000:
            raise HTTPException(
                422, "Обсуждение слишком длинное. Начните новое занятие для этой темы"
            )
        value = Job(
            user_id=user.id,
            kind="explain",
            payload={
                "session_card_id": card.id,
                "snapshot": card.snapshot,
                "question": body.question.strip(),
                "parent_id": body.parent_id,
                "history": context,
            },
        )
        db.add(value)
        db.flush()
        return job_data(value)

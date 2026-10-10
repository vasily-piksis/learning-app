import random
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, func, text
from .auth import require_user
from .library import get_or_404
from .jobs import card_data, job_data
from .models import StudySession, SessionCard, Attempt, Card, Topic, Explanation, Job, now

router = APIRouter(prefix="/api/study", dependencies=[Depends(require_user)])


class StartBody(BaseModel):
    topic_ids: list[int] = Field(min_length=1, max_length=30)
    mode: Literal["quiz", "flashcard"]


class PositionBody(BaseModel):
    position: int = Field(ge=0)


class AnswerBody(PositionBody):
    idempotency_key: str = Field(min_length=1, max_length=80)
    choice: int | None = Field(default=None, ge=0)
    remembered: bool | None = None


class ExplainBody(PositionBody):
    question: str = Field(default="Объясни проще, как ребёнку пяти лет", min_length=1, max_length=2000)
    parent_id: int | None = None


def owned(db, identifier, user_id):
    value = get_or_404(db, StudySession, identifier)
    if value.user_id != user_id:
        raise HTTPException(404, "Не найдено")
    return value


def at_position(db, session_id, position):
    value = db.scalar(select(SessionCard).where(SessionCard.session_id == session_id, SessionCard.position == position))
    if not value:
        raise HTTPException(404, "Карточка занятия не найдена")
    return value


def public_card(snapshot, revealed=False):
    value = {**snapshot, "sources": [{k: v for k, v in s.items() if k != "text"} for s in snapshot["sources"]]}
    if not revealed:
        value.pop("answer", None)
        value.pop("correct_index", None)
    return value


def session_data(db, session, full=False):
    count = db.scalar(select(func.count(SessionCard.id)).where(SessionCard.session_id == session.id))
    attempts = list(db.scalars(select(Attempt).join(SessionCard, Attempt.session_card_id == SessionCard.id).where(SessionCard.session_id == session.id)))
    topic_names = [db.get(Topic, identifier).name for identifier in session.topic_ids]
    result = {"id": session.id, "topic_ids": session.topic_ids, "topic_names": topic_names, "mode": session.mode,
              "position": session.position, "status": session.status, "count": count,
              "answered": len(attempts), "correct": sum(a.correct for a in attempts), "created": session.created.isoformat()}
    if full:
        result["card"] = None
        if session.position < count:
            current = at_position(db, session.id, session.position)
            result["card"] = {**public_card(current.snapshot, current.revealed), "session_card_id": current.id, "revealed": current.revealed}
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
        for identifier in body.topic_ids:
            get_or_404(db, Topic, identifier)
        cards = list(db.scalars(select(Card).where(Card.topic_id.in_(body.topic_ids), Card.status == "saved", Card.mode == body.mode)))
        if not cards:
            raise HTTPException(422, "Сначала сохраните карточки выбранного формата")
        if len(cards) > 300:
            raise HTTPException(422, "Для одного занятия выберите меньше тем (максимум 300 карточек)")
        return new_session(db, user.id, list(dict.fromkeys(body.topic_ids)), body.mode, [card_data(db, card, include_text=True) for card in cards])


@router.get("")
def history(request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        return [session_data(db, value) for value in db.scalars(select(StudySession).where(StudySession.user_id == user.id).order_by(StudySession.id.desc()).limit(200))]


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
        if session.mode != "flashcard" or session.position != body.position or session.status != "active":
            raise HTTPException(409, "Обновите занятие: текущая карточка изменилась")
        card = at_position(db, identifier, body.position)
        card.revealed = True
        return session_data(db, session, full=True)


def feedback(attempt, card, session_id):
    return {"session_id": session_id, "position": card.position, "correct": attempt.correct,
            "card": public_card(card.snapshot, True), "next_position": card.position + 1}


@router.post("/{identifier}/answer")
def answer(identifier: int, body: AnswerBody, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        session = owned(db, identifier, user.id)
        card = at_position(db, identifier, body.position)
        value = {"choice": body.choice, "remembered": body.remembered}
        prior = db.scalar(select(Attempt).where(Attempt.user_id == user.id, Attempt.idempotency_key == body.idempotency_key))
        if prior:
            if prior.session_card_id != card.id or prior.value != value:
                raise HTTPException(409, "Идентификатор запроса уже использован для другого ответа")
            return feedback(prior, card, session.id)
        if session.position != body.position or session.status != "active":
            raise HTTPException(409, "Ответ уже сохранён в другой вкладке. Обновите занятие")
        if session.mode == "quiz":
            if body.choice is None or body.remembered is not None or body.choice >= len(card.snapshot["options"]):
                raise HTTPException(422, "Выберите один вариант")
            correct = body.choice == card.snapshot["correct_index"]
        else:
            if not card.revealed:
                raise HTTPException(409, "Сначала откройте ответ")
            if body.remembered is None or body.choice is not None:
                raise HTTPException(422, "Отметьте, помните ли ответ")
            correct = body.remembered
        attempt = Attempt(user_id=user.id, session_card_id=card.id, idempotency_key=body.idempotency_key, value=value, correct=correct)
        db.add(attempt)
        session.position += 1
        session.updated = now()
        count = db.scalar(select(func.count(SessionCard.id)).where(SessionCard.session_id == identifier))
        if session.position >= count:
            session.status = "completed"
        return feedback(attempt, card, identifier)


@router.post("/{identifier}/repeat")
def repeat(identifier: int, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        session = owned(db, identifier, user.id)
        cards = list(db.scalars(select(SessionCard).join(Attempt, Attempt.session_card_id == SessionCard.id).where(SessionCard.session_id == identifier, Attempt.correct.is_(False))))
        if not cards:
            raise HTTPException(422, "Пока нет карточек для повторения")
        return new_session(db, user.id, session.topic_ids, session.mode, [card.snapshot for card in cards])


@router.get("/{identifier}/explanations")
def explanations(identifier: int, position: int, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        owned(db, identifier, user.id)
        card = at_position(db, identifier, position)
        return [{"id": value.id, "question": value.question, "parent_id": value.parent_id, **value.result}
                for value in db.scalars(select(Explanation).where(Explanation.user_id == user.id, Explanation.session_card_id == card.id).order_by(Explanation.id))]


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
        pending = db.scalar(select(Job).where(Job.user_id == user.id, Job.kind == "explain", Job.status.in_(["queued", "running"]), Job.payload["session_card_id"].as_integer() == card.id))
        if pending:
            raise HTTPException(409, "Дождитесь текущего объяснения")
        if body.parent_id:
            parent = db.get(Explanation, body.parent_id)
            if not parent or parent.user_id != user.id or parent.session_card_id != card.id:
                raise HTTPException(422, "Уточнение должно относиться к этой карточке")
        previous = list(db.scalars(select(Explanation).where(Explanation.user_id == user.id, Explanation.session_card_id == card.id).order_by(Explanation.id)))
        context = [{"question": e.question, **e.result} for e in previous]
        if sum(len(str(item)) for item in context) > 60000:
            raise HTTPException(422, "Обсуждение слишком длинное. Начните новое занятие для этой темы")
        value = Job(user_id=user.id, kind="explain", payload={"session_card_id": card.id, "snapshot": card.snapshot,
                                                            "question": body.question.strip(), "parent_id": body.parent_id,
                                                            "history": context})
        db.add(value)
        db.flush()
        return job_data(value)

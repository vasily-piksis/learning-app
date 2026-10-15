import copy
import random
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator
from sqlalchemy import delete, func, select, text

from . import exercises
from .auth import require_user
from .exercises import QuestionType
from .jobs import card_data, job_data
from .library import get_or_404
from .models import (
    Attempt,
    Card,
    Evaluation,
    Explanation,
    Job,
    SessionCard,
    StudySession,
    Topic,
    now,
)
from .practice import ready_for_quiz
from .quiz import correct_indices
from .sources import available_sources

router = APIRouter(prefix="/api/study", dependencies=[Depends(require_user)])


class StartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic_ids: list[StrictInt] = Field(min_length=1, max_length=30)
    mode: Literal["quiz", "flashcard"]
    question_types: list[QuestionType] | None = Field(default=None, min_length=1, max_length=8)
    include_ai_evaluated: StrictBool = False

    @model_validator(mode="after")
    def distinct_selection(self):
        if len(set(self.topic_ids)) != len(self.topic_ids) or any(i < 1 for i in self.topic_ids):
            raise ValueError("Выберите разные темы")
        if self.question_types is not None and len(set(self.question_types)) != len(
            self.question_types
        ):
            raise ValueError("Выберите разные способы проверки")
        if self.mode == "flashcard" and self.question_types is not None:
            raise ValueError("Флеш-карты используют вопросы всех типов")
        if (
            self.question_types
            and bool({"free_response", "picture_description"} & set(self.question_types))
            and not self.include_ai_evaluated
        ):
            raise ValueError("Подтвердите платную проверку свободного ответа")
        return self


class DeleteHistoryBody(BaseModel):
    session_ids: list[Annotated[StrictInt, Field(gt=0)]] = Field(min_length=1, max_length=200)


class PositionBody(BaseModel):
    position: int = Field(ge=0)


class AnswerBody(PositionBody):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=80)
    choice: StrictInt | None = Field(default=None, ge=0)
    choices: list[StrictInt] | None = None
    remembered: bool | None = None
    text: StrictStr | None = Field(default=None, max_length=1000)
    free_text: StrictStr | None = Field(default=None, max_length=10000)
    gap_answers: dict[StrictStr, StrictStr] | None = None
    pairs: list[dict[StrictStr, StrictStr]] | None = Field(default=None, max_length=8)
    order: list[StrictStr] | None = Field(default=None, max_length=20)


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


def public_card(snapshot, revealed=False, db=None, session_card=None):
    if snapshot.get("question_type") in {"free_response", "picture_description"} and db is not None:
        revealed = bool(
            session_card
            and db.scalar(select(Attempt.id).where(Attempt.session_card_id == session_card.id))
        )
    value = exercises.public_exercise(snapshot, revealed)
    if db is not None:
        value["sources"] = available_sources(db, value["sources"])
    value["multiple_answers"] = len(correct_indices(snapshot)) > 1
    if revealed:
        value["correct_indices"] = correct_indices(snapshot)
    if db is not None and session_card is not None:
        from .question_images import session_images

        value["images"] = session_images(db, session_card, revealed)
    return value


def stored_submission(attempt, snapshot):
    value = {k: v for k, v in attempt.value.items() if k != "_grading"}
    return exercises.canonical_submission(snapshot, value)


def grading_data(attempt):
    grading = attempt.value.get("_grading") or {}
    if grading.get("version") == 2:
        from .free_responses import StoredEvaluationGrade

        return StoredEvaluationGrade.model_validate(grading).model_dump(
            exclude={"version", "voice"}
        )
    if grading and grading.get("version") != 1:
        raise ValueError("Неизвестная версия оценки")
    return {"parts": grading.get("parts", []), "message_code": grading.get("message_code")}


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
    type_column = func.coalesce(SessionCard.snapshot["question_type"].as_string(), "choice")
    types = {
        kind: amount
        for kind, amount in db.execute(
            select(type_column, func.count(SessionCard.id))
            .where(SessionCard.session_id == session.id)
            .group_by(type_column)
        )
    }
    method = (
        "flashcard"
        if session.mode == "flashcard"
        else (next(iter(types)) if len(types) == 1 else "mixed")
    )
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
        "question_types": types,
        "practice_method": method,
    }
    if full:
        result["card"] = None
        result["review"] = []
        for attempt in attempts:
            answered_card = db.get(SessionCard, attempt.session_card_id)
            result["review"].append(
                {
                    "position": answered_card.position,
                    "card": public_card(answered_card.snapshot, True, db, answered_card),
                    "correct": attempt.correct,
                    "submission": stored_submission(attempt, answered_card.snapshot),
                    "choice": attempt.value.get(
                        "choice", (attempt.value.get("choices") or [None])[0]
                    ),
                    "choices": attempt.value.get("choices"),
                    "remembered": attempt.value.get("remembered"),
                    **grading_data(attempt),
                }
            )
        result["review"].sort(key=lambda item: item["position"])
        if session.position < count:
            current = at_position(db, session.id, session.position)
            result["card"] = {
                **public_card(current.snapshot, current.revealed, db, current),
                "session_card_id": current.id,
                "revealed": current.revealed,
            }
    return result


def new_session(db, user_id, topics, mode, snapshots):
    random.SystemRandom().shuffle(snapshots)
    value = StudySession(user_id=user_id, topic_ids=topics, mode=mode)
    db.add(value)
    db.flush()
    from .question_images import copy_images

    for position, snapshot in enumerate(snapshots):
        source_session = snapshot.get("_image_source_session_card_id")
        clean = {
            k: v
            for k, v in snapshot.items()
            if k not in {"images", "_image_source_session_card_id"}
        }
        if clean.get("question_type") == "free_response":
            from .quiz import build_free_snapshot

            frozen = (
                copy.deepcopy(clean)
                if source_session is not None
                else build_free_snapshot(clean, clean["exercise"]["source_fragments"])
            )
        else:
            frozen = exercises.build_snapshot(clean)
        card = SessionCard(session_id=value.id, position=position, snapshot=frozen)
        db.add(card)
        db.flush()
        copy_images(
            db, card, source_session_card_id=source_session, source_card_id=snapshot.get("id")
        )
    db.flush()
    return session_data(db, value, full=True)


@router.post("")
def start(body: StartBody, request: Request):
    user = require_user(request)
    if body.question_types and {"free_response", "picture_description"} & set(body.question_types):
        from .evaluations import require_available

        for kind in set(body.question_types) & {"free_response", "picture_description"}:
            require_available(request.app.state.settings, kind)
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
        if body.mode == "quiz":
            ready = [card for card in cards if ready_for_quiz(card, db)]
            types_by_topic = [
                {c.question_type for c in ready if c.topic_id == topic_id}
                for topic_id in body.topic_ids
            ]
            selected = body.question_types
            if selected is None:
                selected = (
                    sorted(
                        set.intersection(*types_by_topic) - {"free_response", "picture_description"}
                    )
                    if types_by_topic
                    else []
                )
                if not selected:
                    raise HTTPException(
                        422,
                        {
                            "message": "Нет общего готового способа. Выберите способы и подготовьте задания",
                            "missing_pairs": [],
                            "action": "prepare",
                        },
                    )
            missing = [
                {"topic_id": topic_id, "question_type": kind}
                for topic_id in body.topic_ids
                for kind in selected
                if not any(c.topic_id == topic_id and c.question_type == kind for c in ready)
            ]
            if missing:
                raise HTTPException(
                    422,
                    {
                        "message": "Подготовьте задания для выбранных тем и способов",
                        "missing_pairs": missing,
                        "action": "prepare",
                    },
                )
            cards = [c for c in ready if c.question_type in selected]
        else:
            cards = [
                c for c in cards if c.question_type not in {"free_response", "picture_description"}
            ]
            missing = [
                {"topic_id": topic_id, "question_type": "flashcard"}
                for topic_id in body.topic_ids
                if not any(c.topic_id == topic_id and c.answer.strip() for c in cards)
            ]
            if missing:
                raise HTTPException(
                    422,
                    {
                        "message": "Сначала сохраните вопросы выбранных тем",
                        "missing_pairs": missing,
                        "action": "prepare",
                    },
                )
        if not cards:
            raise HTTPException(422, "Сначала сохраните вопросы")
        if len(cards) > 300:
            raise HTTPException(
                422, "Для одного занятия выберите меньше тем (максимум 300 вопросов)"
            )
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
                Job.kind.in_(
                    ["explain", "evaluate_response", "prepare_picture", "transcribe_answer"]
                ),
                Job.payload["session_card_id"].as_integer().in_(card_ids),
            )
        ):
            # Keep the ID reserved so an in-flight worker cannot write into a new job.
            job.status, job.payload, job.result, job.error = "deleted", {}, None, None
        db.execute(delete(Explanation).where(Explanation.session_card_id.in_(card_ids)))
        db.execute(delete(Evaluation).where(Evaluation.session_card_id.in_(card_ids)))
        db.execute(delete(Attempt).where(Attempt.session_card_id.in_(card_ids)))
        db.execute(delete(SessionCard).where(SessionCard.session_id.in_(identifiers)))
        for session in sessions:
            # Empty tombstones also prevent old browser tabs from reaching reused IDs.
            session.status, session.topic_ids, session.position = "deleted", [], 0
        result = {"deleted_count": len(sessions)}
    from .question_images import cleanup_image_assets

    cleanup_image_assets(request.app.state.db)
    return result


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
        "card": public_card(card.snapshot, True, db, card),
        "next_position": card.position + 1,
        "submission": stored_submission(attempt, card.snapshot),
        **grading_data(attempt),
    }


@router.post("/{identifier}/answer")
def answer(identifier: int, body: AnswerBody, request: Request):
    user = require_user(request)
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        session = owned(db, identifier, user.id)
        card = at_position(db, identifier, body.position)
        try:
            value = exercises.canonical_submission(
                card.snapshot,
                body.model_dump(exclude={"position", "idempotency_key"}, exclude_none=True),
            )
        except exercises.InvalidSubmission as error:
            raise HTTPException(422, str(error)) from error
        if card.snapshot.get("question_type") in {"free_response", "picture_description"}:
            from .evaluations import answer_evaluation

            return answer_evaluation(
                db, request.app.state.settings, session, card, user.id, body.idempotency_key, value
            )
        from .evaluations import key_used

        if key_used(db, user.id, body.idempotency_key) and not db.scalar(
            select(Attempt.id).where(
                Attempt.user_id == user.id, Attempt.idempotency_key == body.idempotency_key
            )
        ):
            raise HTTPException(409, "Идентификатор запроса уже использован")
        prior = db.scalar(
            select(Attempt).where(
                Attempt.user_id == user.id, Attempt.idempotency_key == body.idempotency_key
            )
        )
        if prior:
            if prior.session_card_id != card.id or stored_submission(prior, card.snapshot) != value:
                raise HTTPException(409, "Идентификатор запроса уже использован для другого ответа")
            return feedback(prior, card, session.id, db)
        if session.position != body.position or session.status != "active":
            raise HTTPException(409, "Ответ уже сохранён в другой вкладке. Обновите занятие")
        if session.mode == "flashcard" and not card.revealed:
            raise HTTPException(409, "Сначала откройте ответ")
        grade = exercises.grade_answer(card.snapshot, value)
        correct = grade.correct
        value = {**value, "_grading": {"version": 1, **asdict(grade)}}
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
        from .evaluations import require_available

        kinds = {card.snapshot.get("question_type") for card in cards}
        for kind in kinds & {"free_response", "picture_description"}:
            require_available(request.app.state.settings, kind)
        return new_session(
            db,
            user.id,
            session.topic_ids,
            session.mode,
            [{**card.snapshot, "_image_source_session_card_id": card.id} for card in cards],
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
        if attempted is None and (
            not card.revealed
            or card.snapshot.get("question_type") in {"free_response", "picture_description"}
        ):
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
        if card.snapshot.get("question_type") == "picture_description":
            from .models import JobImage
            from .picture_responses import get_picture_evidence

            evidence = get_picture_evidence(db, card.id, user.id)
            db.add(JobImage(job_id=value.id, asset_id=evidence.asset_id, role="context"))
        return job_data(value)

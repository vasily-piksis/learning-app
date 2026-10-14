import json

import pytest
from app.jobs import run_job
from app.models import Card, Job
from exercise_cases import CASES
from sqlalchemy import func, select
from test_exercise_generation import setup_generation
from test_study import saved_cards


def saved_exercise(client, app, kind, topic=None):
    topic = topic or setup_generation(client, app)
    job = client.post(
        "/api/generate",
        json={
            "topic_ids": [topic],
            "count": 1,
            "question_types": [kind],
            "practice_goal": "language",
        },
    ).json()
    run_job(app.state.db, app.state.ai, job["id"])
    cards = client.get(f"/api/cards?job_id={job['id']}").json()
    assert len(cards) == 1
    assert client.post("/api/cards/save", json={"card_ids": [cards[0]["id"]]}).status_code == 200
    return topic, cards[0]


def submission(card, correct=True):
    kind, exercise = card["question_type"], card["exercise"]
    if kind == "written":
        return {"text": "LENTELĖ" if correct else "lentelé"}
    if kind == "gap":
        return {"gap_answers": {"subject": "I", "verb": "am" if correct else "are"}}
    if kind == "ending":
        return {"gap_answers": {"ending": "u" if correct else "i"}}
    if kind == "matching":
        expected = {"stalas": "table", "namas": "house"}
        right = {item["text"]: item["id"] for item in exercise["right"]}
        pairs = [
            {"left_id": item["id"], "right_id": right[expected[item["text"]]]}
            for item in exercise["left"]
        ]
        if not correct:
            pairs[0]["right_id"], pairs[1]["right_id"] = pairs[1]["right_id"], pairs[0]["right_id"]
        return {"pairs": pairs}
    ids = {}
    for item in exercise["tokens"]:
        ids.setdefault(item["text"], []).append(item["id"])
    order = [ids["I"][0], ids["think"][0], ids["I"][1], ids["can"][0]]
    return {"order": order if correct else order[::-1]}


@pytest.mark.parametrize("kind", CASES)
@pytest.mark.parametrize("correct", [True, False])
def test_each_exercise_start_answer_feedback_and_history(client, app, kind, correct):
    topic, _ = saved_exercise(client, app, kind)
    response = client.post(
        "/api/study", json={"topic_ids": [topic], "mode": "quiz", "question_types": [kind]}
    )
    assert response.status_code == 200, response.text
    session = response.json()
    public = json.dumps(session["card"])
    assert "accepted_answers" not in public and "accepted_combinations" not in public
    assert "accepted_orders" not in public and "solution" not in session["card"]["exercise"]
    assert client.get(f"/api/study/{session['id']}").json()["card"] == session["card"]
    data = {
        "position": 0,
        "idempotency_key": "exercise-answer",
        **submission(session["card"], correct),
    }
    response = client.post(f"/api/study/{session['id']}/answer", json=data)
    assert response.status_code == 200, response.text
    feedback = response.json()
    assert feedback["correct"] is correct and "answer" in feedback["card"]
    assert client.post(f"/api/study/{session['id']}/answer", json=data).json() == feedback
    if kind == "matching":
        assert (
            client.post(
                f"/api/study/{session['id']}/answer", json={**data, "pairs": data["pairs"][::-1]}
            ).json()
            == feedback
        )
    history = client.get(f"/api/study/{session['id']}").json()
    assert history["status"] == "completed" and history["correct"] == int(correct)
    assert history["question_types"] == {kind: 1} and history["practice_method"] == kind
    assert history["review"][0]["submission"] == feedback["submission"]
    if kind == "gap" and not correct:
        assert feedback["message_code"] == "incompatible_combination"
        assert history["review"][0]["parts"] == feedback["parts"]


def test_missing_topic_method_is_not_silently_excluded_and_start_creates_no_job(client, app):
    first, _ = saved_exercise(client, app, "written")
    second, _ = saved_cards(client, app, "quiz", 1)
    with app.state.db.session() as db:
        before = db.scalar(select(func.count(Job.id)))
    response = client.post(
        "/api/study",
        json={"topic_ids": [first, second], "mode": "quiz", "question_types": ["written"]},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["missing_pairs"] == [
        {"topic_id": second, "question_type": "written"}
    ]
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(Job.id))) == before


def test_availability_counts_drafts_ready_and_pending_preparation_separately(client, app):
    topic, card = saved_exercise(client, app, "written")
    pending = client.post(
        "/api/generate", json={"topic_ids": [topic], "count": 2, "question_types": ["written"]}
    ).json()
    response = client.get(f"/api/topics/{topic}").json()
    value = response["practice_availability"]["written"]
    assert value["ready_count"] == 1 and value["draft_count"] == 0
    assert value["preparation_job_id"] == pending["id"] and value["preparation_status"] == "queued"
    assert "accepted_answers" not in json.dumps(response)
    with app.state.db.session() as db:
        db.get(Card, card["id"]).status = "draft"
    value = client.get(f"/api/topics/{topic}").json()["practice_availability"]["written"]
    assert value["ready_count"] == 0 and value["draft_count"] == 1


def test_mixed_default_uses_only_common_ready_types(client, app):
    first, _ = saved_exercise(client, app, "written")
    second, _ = saved_exercise(client, app, "written")
    saved_exercise(client, app, "gap", first)
    response = client.post("/api/study", json={"topic_ids": [first, second], "mode": "quiz"})
    assert response.status_code == 200, response.text
    assert response.json()["question_types"] == {"written": 2}
    response = client.post(
        "/api/study",
        json={"topic_ids": [first, second], "mode": "quiz", "question_types": ["written", "gap"]},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["missing_pairs"] == [
        {"topic_id": second, "question_type": "gap"}
    ]


def test_invalid_submission_is_not_recorded_and_does_not_reveal_solution(client, app):
    topic, _ = saved_exercise(client, app, "gap")
    response = client.post(
        "/api/study", json={"topic_ids": [topic], "mode": "quiz", "question_types": ["gap"]}
    )
    assert response.status_code == 200
    session = response.json()
    route = f"/api/study/{session['id']}/answer"
    for data in (
        {"gap_answers": {"subject": "I"}},
        {"text": "I am"},
        {"gap_answers": {"subject": "I", "verb": "am"}, "_grading": {"correct": True}},
    ):
        result = client.post(route, json={"position": 0, "idempotency_key": "invalid", **data})
        assert result.status_code == 422 and "accepted_combinations" not in result.text
    current = client.get(f"/api/study/{session['id']}").json()
    assert current["answered"] == 0 and "answer" not in current["card"]


@pytest.mark.parametrize("kind", CASES)
def test_specialized_questions_remain_usable_as_flashcards(client, app, kind):
    topic, card = saved_exercise(client, app, kind)
    response = client.post("/api/study", json={"topic_ids": [topic], "mode": "flashcard"})
    assert response.status_code == 200, response.text
    session = response.json()
    assert session["practice_method"] == "flashcard" and "answer" not in session["card"]
    revealed = client.post(f"/api/study/{session['id']}/reveal", json={"position": 0})
    assert revealed.status_code == 200 and revealed.json()["card"]["answer"] == card["answer"]
    answered = client.post(
        f"/api/study/{session['id']}/answer",
        json={"position": 0, "remembered": False, "idempotency_key": "flash-specialized"},
    )
    assert answered.status_code == 200 and answered.json()["correct"] is False


def test_unsupported_material_reason_becomes_stale_when_materials_are_added(client, app):
    from types import SimpleNamespace

    from fakes import ready_document

    topic = setup_generation(client, app)
    app.state.ai.generate = lambda *args, **kwargs: SimpleNamespace(
        cards=[],
        insufficient_reason=None,
        unsupported_types=[
            SimpleNamespace(question_type="ending", reason="Need grammatical context")
        ],
    )
    job = client.post(
        "/api/generate",
        json={
            "topic_ids": [topic],
            "count": 1,
            "question_types": ["ending"],
            "practice_goal": "language",
        },
    ).json()
    run_job(app.state.db, app.state.ai, job["id"])
    value = client.get(f"/api/topics/{topic}").json()["practice_availability"]["ending"][
        "last_outcome"
    ]
    assert value["reason"] == "Need grammatical context" and value["stale"] is False
    ready_document(client, app, topic, pages=2)
    value = client.get(f"/api/topics/{topic}").json()["practice_availability"]["ending"][
        "last_outcome"
    ]
    assert value["stale"] is True


def test_private_preparation_job_ids_do_not_leak_in_shared_topic_availability(client, app):
    topic, _ = saved_exercise(client, app, "written")
    client.post("/api/generate", json={"topic_ids": [topic], "count": 1, "question_types": ["gap"]})
    login = client.post(
        "/api/auth/login", json={"username": "parent", "password": "parent-password"}
    )
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    value = client.get(f"/api/topics/{topic}").json()["practice_availability"]
    assert value["written"]["ready_count"] == 1
    assert value["gap"]["preparation_job_id"] is None

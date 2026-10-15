import pytest
from app.models import Attempt, Card
from exercise_cases import CASES
from sqlalchemy import select
from test_exercise_study import saved_exercise, submission


@pytest.mark.parametrize("kind", CASES)
def test_repeat_retains_original_exercise_after_question_edit_and_delete(client, app, kind):
    topic, card = saved_exercise(client, app, kind)
    response = client.post(
        "/api/study", json={"topic_ids": [topic], "mode": "quiz", "question_types": [kind]}
    )
    assert response.status_code == 200, response.text
    session = response.json()
    assert (
        client.post(
            f"/api/study/{session['id']}/answer",
            json={"position": 0, "idempotency_key": "wrong", **submission(session["card"], False)},
        ).status_code
        == 200
    )
    with app.state.db.session() as db:
        db.get(Card, card["id"]).question = "Changed after studying"
    assert client.delete(f"/api/cards/{card['id']}").status_code == 200
    history = client.get(f"/api/study/{session['id']}").json()
    repeated = client.post(f"/api/study/{session['id']}/repeat").json()
    assert repeated["count"] == 1 and repeated["card"]["question"] == session["card"]["question"]
    assert history["review"][0]["card"]["question"] == session["card"]["question"]
    if kind == "matching":
        assert {p["id"] for p in repeated["card"]["exercise"]["left"]}.isdisjoint(
            {p["id"] for p in session["card"]["exercise"]["left"]}
        )
    if kind == "ordering":
        assert {p["id"] for p in repeated["card"]["exercise"]["tokens"]}.isdisjoint(
            {p["id"] for p in session["card"]["exercise"]["tokens"]}
        )


def test_saved_feedback_is_not_regraded_on_replay_or_history(client, app, monkeypatch):
    from app import exercises

    topic, _ = saved_exercise(client, app, "gap")
    started = client.post(
        "/api/study", json={"topic_ids": [topic], "mode": "quiz", "question_types": ["gap"]}
    )
    assert started.status_code == 200
    session = started.json()
    body = {
        "position": 0,
        "idempotency_key": "frozen-grading",
        **submission(session["card"], False),
    }
    result = client.post(f"/api/study/{session['id']}/answer", json=body).json()

    def changed_grader(*args, **kwargs):
        raise AssertionError("Stored result must not be recalculated")

    monkeypatch.setattr(exercises, "grade_answer", changed_grader)
    assert client.post(f"/api/study/{session['id']}/answer", json=body).json() == result
    review = client.get(f"/api/study/{session['id']}").json()["review"][0]
    assert review["parts"] == result["parts"] and review["correct"] is False
    with app.state.db.session() as db:
        stored = db.scalar(select(Attempt))
        assert stored.value["_grading"]["version"] == 1


def test_ordering_new_repeat_and_saved_solved_bank_are_immutable(client, app, monkeypatch):
    from app import exercises
    from app.models import SessionCard

    monkeypatch.setattr(exercises.random.SystemRandom, "shuffle", lambda self, values: None)
    topic, _ = saved_exercise(client, app, "ordering")
    session = client.post(
        "/api/study", json={"topic_ids": [topic], "mode": "quiz", "question_types": ["ordering"]}
    ).json()
    bank = session["card"]["exercise"]["tokens"]
    assert [token["text"] for token in bank] not in CASES["ordering"]["accepted_orders"]
    # Emulate an already-persisted solved bank from the old implementation.
    with app.state.db.session() as db:
        row = db.scalar(select(SessionCard).where(SessionCard.session_id == session["id"]))
        frozen = dict(row.snapshot)
        pool = list(frozen["exercise"]["tokens"])
        ordered = []
        for word in CASES["ordering"]["accepted_orders"][0]:
            token = next(token for token in pool if token["text"] == word)
            ordered.append(token)
            pool.remove(token)
        frozen["exercise"] = {**frozen["exercise"], "tokens": ordered}
        row.snapshot = frozen
    saved = client.get(f"/api/study/{session['id']}").json()["card"]
    assert saved["exercise"]["tokens"] == ordered
    result = client.post(
        f"/api/study/{session['id']}/answer",
        json={
            "position": 0,
            "idempotency_key": "old-bank",
            "order": [token["id"] for token in reversed(ordered)],
        },
    ).json()
    assert result["correct"] is False
    repeated = client.post(f"/api/study/{session['id']}/repeat").json()
    assert [token["text"] for token in repeated["card"]["exercise"]["tokens"]] not in CASES[
        "ordering"
    ]["accepted_orders"]
    assert (
        client.get(f"/api/study/{session['id']}").json()["review"][0]["card"]["exercise"]["tokens"]
        == ordered
    )

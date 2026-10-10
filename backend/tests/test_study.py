from app.models import Card
from conftest import make_topic
from fakes import FixtureAI, ready_document


def saved_cards(client, app, mode="quiz", count=3):
    from app.jobs import run_job

    app.state.ai = FixtureAI()
    topic = make_topic(client)
    ready_document(client, app, topic)
    job = client.post(
        "/api/generate", json={"topic_ids": [topic], "mode": mode, "count": count}
    ).json()
    run_job(app.state.db, app.state.ai, job["id"])
    cards = client.get(f"/api/cards?job_id={job['id']}").json()
    client.post("/api/cards/save", json={"card_ids": [c["id"] for c in cards]})
    return topic, cards


def test_quiz_snapshot_idempotency_and_stale_tabs(client, app):
    topic, cards = saved_cards(client, app)
    session = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    assert session["position"] == 0 and session["count"] == 3
    assert "correct_index" not in session["card"]
    assert "answer" not in session["card"]
    assert "text" not in session["card"]["sources"][0]
    current = session["card"]
    with app.state.db.session() as db:
        card = db.get(Card, current["id"])
        card.question = "ИЗМЕНЕНО"
        card.correct_index = 2
        card.version += 1
    assert (
        client.get(f"/api/study/{session['id']}").json()["card"]["question"] == current["question"]
    )
    route = f"/api/study/{session['id']}/answer"
    payload = {"position": 0, "choice": 0, "idempotency_key": "one-answer"}
    result = client.post(route, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["correct"] is True
    assert result.json()["card"]["answer"] == "Нил"
    assert client.post(route, json=payload).json() == result.json()
    assert client.post(route, json={**payload, "idempotency_key": "stale-tab"}).status_code == 409
    assert client.post(route, json={**payload, "choice": 1}).status_code == 409
    resumed = client.get(f"/api/study/{session['id']}").json()
    assert resumed["position"] == 1 and resumed["answered"] == 1


def test_private_history_and_resume_after_reopen(client, app):
    from app.main import create_app
    from fastapi.testclient import TestClient

    topic, cards = saved_cards(client, app, "flashcard", 1)
    session = client.post("/api/study", json={"topic_ids": [topic], "mode": "flashcard"}).json()
    assert (
        client.post(
            f"/api/study/{session['id']}/answer",
            json={"position": 0, "remembered": False, "idempotency_key": "before-reveal"},
        ).status_code
        == 409
    )
    client.post(f"/api/study/{session['id']}/reveal", json={"position": 0})
    answer = client.post(
        f"/api/study/{session['id']}/answer",
        json={"position": 0, "remembered": False, "idempotency_key": "grade"},
    )
    assert answer.status_code == 200
    repeated = client.post(f"/api/study/{session['id']}/repeat").json()
    assert repeated["id"] != session["id"] and repeated["count"] == 1
    with TestClient(create_app(app.state.settings, worker=False)) as reopened:
        reopened.cookies.update(client.cookies)
        assert reopened.get(f"/api/study/{session['id']}").json()["status"] == "completed"
        login = reopened.post(
            "/api/auth/login",
            json={"username": "parent", "password": "parent-password"},
            headers={"Origin": "http://testserver"},
        )
        reopened.headers.update(
            {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf_token"]}
        )
        assert reopened.get("/api/study").json() == []
        assert reopened.get(f"/api/study/{session['id']}").status_code == 404
        assert reopened.post(f"/api/study/{session['id']}/repeat").status_code == 404


def test_explanations_use_snapshot_and_keep_followups(client, app):
    from app.jobs import run_job

    topic, _ = saved_cards(client, app, "quiz", 1)
    session = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    route = f"/api/study/{session['id']}/explain"
    assert client.post(route, json={"position": 0, "question": "Объясни проще"}).status_code == 409
    client.post(
        f"/api/study/{session['id']}/answer",
        json={"position": 0, "choice": 1, "idempotency_key": "wrong"},
    )
    first = client.post(route, json={"position": 0, "question": "Объясни проще"}).json()
    run_job(app.state.db, app.state.ai, first["id"])
    result = client.get(f"/api/jobs/{first['id']}").json()["result"]
    second = client.post(
        route,
        json={
            "position": 0,
            "question": "Почему река важна?",
            "parent_id": result["explanation_id"],
        },
    ).json()
    run_job(app.state.db, app.state.ai, second["id"])
    assert len(app.state.ai.inputs[-1][2]) == 1
    assert len(client.get(f"/api/study/{session['id']}/explanations?position=0").json()) == 2


def test_saved_quiz_cards_can_be_studied_as_flashcards_without_mutation(client, app):
    from app.models import SessionCard
    from sqlalchemy import select

    topic, cards = saved_cards(client, app, "quiz", 2)
    response = client.post("/api/study", json={"topic_ids": [topic], "mode": "flashcard"})
    assert response.status_code == 200, response.text
    session = response.json()
    assert session["mode"] == "flashcard" and session["count"] == 2
    assert session["card"]["mode"] == "flashcard" and session["card"]["options"] == []
    assert "answer" not in session["card"] and "correct_index" not in session["card"]
    with app.state.db.session() as db:
        assert db.get(Card, cards[0]["id"]).mode == "quiz"
        assert db.get(Card, cards[0]["id"]).options
        snapshots = list(
            db.scalars(select(SessionCard).where(SessionCard.session_id == session["id"]))
        )
        assert {snapshot.snapshot["mode"] for snapshot in snapshots} == {"flashcard"}
    revealed = client.post(f"/api/study/{session['id']}/reveal", json={"position": 0}).json()
    assert revealed["card"]["answer"] == "Нил"
    result = client.post(
        f"/api/study/{session['id']}/answer",
        json={"position": 0, "remembered": False, "idempotency_key": "quiz-as-flash"},
    )
    assert result.status_code == 200 and result.json()["correct"] is False
    quiz = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    assert quiz["card"]["options"] and "correct_index" not in quiz["card"]

from app.jobs import recover_jobs, run_job
from app.models import Card, Job, SourcePage
from sqlalchemy import func, select
from test_study import saved_cards


def prepare(client, topic):
    response = client.post("/api/study/prepare-options", json={"topic_ids": [topic]})
    assert response.status_code == 200, response.text
    return response.json()


def accept(client, job):
    result = client.get(f"/api/jobs/{job['id']}").json()["result"]
    response = client.post(
        f"/api/jobs/{job['id']}/save-preparation", json={"card_ids": result["card_ids"]}
    )
    assert response.status_code == 200, response.text


def test_legacy_flashcards_prepare_once_then_review_without_changing_history(client, app):
    topic, cards = saved_cards(client, app, "flashcard", 2)
    flash = client.post("/api/study", json={"topic_ids": [topic], "mode": "flashcard"}).json()
    assert client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).status_code == 422
    job = prepare(client, topic)
    assert prepare(client, topic)["id"] == job["id"]
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "succeeded"
    assert client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).status_code == 422
    accept(client, job)
    quiz = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    assert quiz["count"] == 2 and quiz["card"]["options"]
    assert "correct_index" not in quiz["card"]
    old = client.get(f"/api/study/{flash['id']}").json()
    assert old["card"]["mode"] == "flashcard" and old["card"]["options"] == []
    client.post(f"/api/study/{flash['id']}/reveal", json={"position": 0})
    assert client.get(f"/api/study/{flash['id']}").json()["card"]["answer"] == "Нил"
    with app.state.db.session() as db:
        assert {c.id for c in db.scalars(select(Card))} == {c["id"] for c in cards}
        assert db.scalar(select(func.count(Job.id)).where(Job.kind == "prepare_quiz")) == 1


def test_preparation_version_conflict_is_atomic_and_drafts_excluded(client, app):
    topic, cards = saved_cards(client, app, "flashcard", 3)
    with app.state.db.session() as db:
        db.get(Card, cards[2]["id"]).status = "draft"
    job = prepare(client, topic)
    with app.state.db.session() as db:
        db.get(Card, cards[0]["id"]).version += 1
    run_job(app.state.db, app.state.ai, job["id"])
    failed = client.get(f"/api/jobs/{job['id']}").json()
    assert failed["status"] == "failed" and "измен" in failed["error"]
    with app.state.db.session() as db:
        assert all(c.options == [] for c in db.scalars(select(Card)))
    fresh = prepare(client, topic)
    assert fresh["id"] != job["id"]
    run_job(app.state.db, app.state.ai, fresh["id"])
    accept(client, fresh)
    assert (
        client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()["count"] == 2
    )


def test_failed_preparation_recovery_retry_and_private_access(client, app):
    topic, _ = saved_cards(client, app, "flashcard", 1)
    job = prepare(client, topic)
    with app.state.db.session() as db:
        db.get(Job, job["id"]).status = "running"
    recover_jobs(app.state.db)
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"
    assert prepare(client, topic)["id"] == job["id"]
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 200
    run_job(app.state.db, app.state.ai, job["id"])
    login = client.post(
        "/api/auth/login", json={"username": "parent", "password": "parent-password"}
    )
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 404
    assert (
        client.post(f"/api/jobs/{job['id']}/save-preparation", json={"card_ids": [1]}).status_code
        == 404
    )


def test_mixed_bank_prepares_only_missing_options_and_rejects_changed_answer(client, app):
    from app.schemas import QuizOptions

    topic, cards = saved_cards(client, app, "flashcard", 2)
    with app.state.db.session() as db:
        ready = db.get(Card, cards[0]["id"])
        ready.mode, ready.options, ready.correct_index = "quiz", [ready.answer, "Дон"], 0
    job = prepare(client, topic)
    with app.state.db.session() as db:
        assert [c["id"] for c in db.get(Job, job["id"]).payload["cards"]] == [cards[1]["id"]]
    app.state.ai.prepare_quiz = lambda snapshot: QuizOptions(
        card_id=snapshot["id"], options=["Неверный ответ", "Дон"], correct_index=0
    )
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"
    with app.state.db.session() as db:
        assert db.get(Card, cards[1]["id"]).options == []


def test_many_legacy_questions_share_one_source_without_exceeding_limit(client, app):
    topic, _ = saved_cards(client, app, "flashcard", 21)
    with app.state.db.session() as db:
        db.scalar(select(SourcePage)).text = "x" * 5600
    job = prepare(client, topic)
    run_job(app.state.db, app.state.ai, job["id"])
    accept(client, job)
    assert (
        client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()["count"] == 21
    )


def test_preparation_stale_before_run_and_retry_make_no_paid_calls(client, app):
    topic, cards = saved_cards(client, app, "flashcard", 2)
    job = prepare(client, topic)
    calls = []
    original = app.state.ai.prepare_quiz

    def track(snapshot):
        calls.append(snapshot["id"])
        return original(snapshot)

    app.state.ai.prepare_quiz = track
    with app.state.db.session() as db:
        db.get(Card, cards[0]["id"]).version += 1
    run_job(app.state.db, app.state.ai, job["id"])
    assert calls == [] and client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 409
    fresh = prepare(client, topic)
    assert fresh["id"] != job["id"]
    run_job(app.state.db, app.state.ai, fresh["id"])
    assert (
        len(calls) == 2 and client.get(f"/api/jobs/{fresh['id']}").json()["status"] == "succeeded"
    )


def test_edit_during_model_call_rejects_option_candidate_atomically(client, app):
    topic, cards = saved_cards(client, app, "flashcard", 2)
    job = prepare(client, topic)
    original = app.state.ai.prepare_quiz

    def concurrent_edit(snapshot):
        with app.state.db.session() as db:
            db.get(Card, cards[0]["id"]).version += 1
        return original(snapshot)

    app.state.ai.prepare_quiz = concurrent_edit
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"
    with app.state.db.session() as db:
        assert all(card.options == [] for card in db.scalars(select(Card)))


def test_failed_preparation_retry_rejects_obsolete_snapshot(client, app):
    topic, cards = saved_cards(client, app, "flashcard", 1)
    job = prepare(client, topic)
    with app.state.db.session() as db:
        db.get(Job, job["id"]).status = "failed"
        db.get(Card, cards[0]["id"]).version += 1
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 409
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"

from app.jobs import recover_jobs, run_job
from app.models import Card, Job, SourcePage
from sqlalchemy import func, select
from test_study import saved_cards


def test_legacy_flashcards_prepare_once_then_both_modes_keep_history(client, app):
    topic, cards = saved_cards(client, app, "flashcard", 2)
    flash = client.post("/api/study", json={"topic_ids": [topic], "mode": "flashcard"}).json()
    response = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"})
    assert response.status_code == 202, response.text
    job = response.json()["preparation_job"]
    repeated = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    assert repeated["preparation_job"]["id"] == job["id"]
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "succeeded"
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
    job = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()[
        "preparation_job"
    ]
    with app.state.db.session() as db:
        db.get(Card, cards[0]["id"]).version += 1
    run_job(app.state.db, app.state.ai, job["id"])
    failed = client.get(f"/api/jobs/{job['id']}").json()
    assert failed["status"] == "failed" and "измен" in failed["error"]
    with app.state.db.session() as db:
        assert all(c.options == [] for c in db.scalars(select(Card)))
    new = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()[
        "preparation_job"
    ]
    assert new["id"] != job["id"]
    run_job(app.state.db, app.state.ai, new["id"])
    quiz = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    assert quiz["count"] == 2


def test_failed_preparation_recovery_retry_and_private_access(client, app):
    topic, _ = saved_cards(client, app, "flashcard", 1)
    job = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()[
        "preparation_job"
    ]
    with app.state.db.session() as db:
        db.get(Job, job["id"]).status = "running"
    recover_jobs(app.state.db)
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"
    response = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"})
    assert response.json()["preparation_job"]["id"] == job["id"]
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 200
    run_job(app.state.db, app.state.ai, job["id"])
    login = client.post(
        "/api/auth/login", json={"username": "parent", "password": "parent-password"}
    )
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 404


def test_mixed_bank_prepares_only_missing_options_and_rejects_changed_answer(client, app):
    from app.schemas import QuizOptions

    topic, cards = saved_cards(client, app, "flashcard", 2)
    with app.state.db.session() as db:
        ready = db.get(Card, cards[0]["id"])
        ready.mode, ready.options, ready.correct_index = "quiz", [ready.answer, "Дон"], 0
    job = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()[
        "preparation_job"
    ]
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
    response = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"})
    assert response.status_code == 202, response.text
    run_job(app.state.db, app.state.ai, response.json()["preparation_job"]["id"])
    assert (
        client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()["count"] == 21
    )


def test_preparation_stale_before_run_and_retry_make_no_paid_calls(client, app):
    topic, cards = saved_cards(client, app, "flashcard", 2)
    job = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()[
        "preparation_job"
    ]
    calls = []
    original = app.state.ai.prepare_quiz

    def track(snapshot):
        calls.append(snapshot["id"])
        return original(snapshot)

    app.state.ai.prepare_quiz = track
    with app.state.db.session() as db:
        db.get(Card, cards[0]["id"]).version += 1
    run_job(app.state.db, app.state.ai, job["id"])
    assert calls == []
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"
    response = client.post(f"/api/jobs/{job['id']}/retry")
    assert response.status_code == 409
    assert "Запустите тест заново" in response.json()["detail"]
    run_job(app.state.db, app.state.ai, job["id"])
    assert calls == []
    fresh = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()[
        "preparation_job"
    ]
    assert fresh["id"] != job["id"]
    run_job(app.state.db, app.state.ai, fresh["id"])
    assert len(calls) == 2
    assert client.get(f"/api/jobs/{fresh['id']}").json()["status"] == "succeeded"


def test_edit_during_model_call_still_rejects_all_option_writes(client, app):
    topic, cards = saved_cards(client, app, "flashcard", 2)
    job = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()[
        "preparation_job"
    ]
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
    job = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()[
        "preparation_job"
    ]
    with app.state.db.session() as db:
        db.get(Job, job["id"]).status = "failed"
        db.get(Card, cards[0]["id"]).version += 1
    response = client.post(f"/api/jobs/{job['id']}/retry")
    assert response.status_code == 409, response.text
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"

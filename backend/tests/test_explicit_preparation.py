from app.jobs import run_job
from app.models import Card, Job
from sqlalchemy import func, select
from test_study import saved_cards


def test_start_never_prepares_legacy_options_or_creates_model_job(client, app):
    topic, _ = saved_cards(client, app, "flashcard", 1)
    with app.state.db.session() as db:
        before = db.scalar(select(func.count(Job.id)))
    response = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"})
    assert response.status_code == 422, response.text
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(Job.id))) == before


def test_options_require_explicit_review_and_save_with_idempotent_request(client, app):
    topic, cards = saved_cards(client, app, "flashcard", 2)
    body = {"topic_ids": [topic], "idempotency_key": "prepare-once"}
    response = client.post("/api/study/prepare-options", json=body)
    assert response.status_code == 200, response.text
    job = response.json()
    assert client.post("/api/study/prepare-options", json=body).json()["id"] == job["id"]
    run_job(app.state.db, app.state.ai, job["id"])
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert len(result["result"]["candidates"]) == 2
    with app.state.db.session() as db:
        assert all(db.get(Card, c["id"]).options == [] for c in cards)
    save = {"card_ids": [cards[0]["id"]]}
    applied = client.post(f"/api/jobs/{job['id']}/save-preparation", json=save)
    assert applied.status_code == 200, applied.text
    assert (
        client.post(f"/api/jobs/{job['id']}/save-preparation", json=save).json() == applied.json()
    )
    with app.state.db.session() as db:
        assert db.get(Card, cards[0]["id"]).version == cards[0]["version"] + 1
        assert db.get(Card, cards[1]["id"]).options == []
    assert (
        client.post(
            f"/api/jobs/{job['id']}/save-preparation", json={"card_ids": [cards[1]["id"]]}
        ).status_code
        == 200
    )


def test_options_apply_rejects_version_changed_after_preview(client, app):
    topic, cards = saved_cards(client, app, "flashcard", 1)
    response = client.post("/api/study/prepare-options", json={"topic_ids": [topic]})
    assert response.status_code == 200, response.text
    job = response.json()
    run_job(app.state.db, app.state.ai, job["id"])
    with app.state.db.session() as db:
        db.get(Card, cards[0]["id"]).version += 1
    assert (
        client.post(
            f"/api/jobs/{job['id']}/save-preparation", json={"card_ids": [cards[0]["id"]]}
        ).status_code
        == 409
    )
    with app.state.db.session() as db:
        assert db.get(Card, cards[0]["id"]).options == []


def test_discard_preparation_leaves_original_cards_untouched(client, app):
    topic, cards = saved_cards(client, app, "flashcard", 1)
    response = client.post("/api/study/prepare-options", json={"topic_ids": [topic]})
    assert response.status_code == 200
    job = response.json()
    run_job(app.state.db, app.state.ai, job["id"])
    response = client.post(f"/api/jobs/{job['id']}/discard-preparation")
    assert response.status_code == 200, response.text
    assert client.post(f"/api/jobs/{job['id']}/discard-preparation").status_code == 200
    assert (
        client.post(
            f"/api/jobs/{job['id']}/save-preparation", json={"card_ids": [cards[0]["id"]]}
        ).status_code
        == 409
    )
    with app.state.db.session() as db:
        card = db.get(Card, cards[0]["id"])
        assert card.options == [] and card.version == cards[0]["version"]

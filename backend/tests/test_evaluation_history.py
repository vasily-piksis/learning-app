import json

from app.jobs import run_job
from app.models import Attempt, Job, SessionCard
from sqlalchemy import func, select
from test_evaluations import install_evaluator, setup_free, start_free, submit


def test_history_delete_scrubs_and_blocks_late_worker(client, app, monkeypatch):
    import app.evaluations as module
    from app.models import Evaluation, EvaluationRequest

    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()
    original = module.finalize_evaluation

    def delete_before_finalize(*args):
        assert client.post("/api/study/delete", json={"session_ids": [session]}).status_code == 200
        return original(*args)

    monkeypatch.setattr(module, "finalize_evaluation", delete_before_finalize)
    with install_evaluator(monkeypatch, app):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(Evaluation.id))) == 0
        assert db.scalar(select(func.count(Attempt.id))) == 0
        job = db.get(Job, pending["job_id"])
        assert (job.status, job.payload, job.result, job.error) == ("deleted", {}, None, None)
        rows = list(db.scalars(select(EvaluationRequest)))
        assert len(rows) == 1
        assert "medis" not in json.dumps(
            [
                {c.name: getattr(r, c.name) for c in EvaluationRequest.__table__.columns}
                for r in rows
            ],
            default=str,
        )
    assert client.get(f"/api/jobs/{pending['job_id']}").status_code == 404
    assert client.get(f"/api/study/{session}/evaluations?position=0").status_code == 404


def test_private_owner_and_csrf(client, app):
    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()
    assert (
        client.post(
            f"/api/study/{session}/answer", json={}, headers={"X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )
    response = client.post(
        "/api/auth/login", json={"username": "parent", "password": "parent-password"}
    )
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    assert client.get(f"/api/study/{session}/evaluations?position=0").status_code == 404
    assert client.get(f"/api/jobs/{pending['job_id']}").status_code == 404
    assert client.post(f"/api/jobs/{pending['job_id']}/retry").status_code == 404
    assert (
        client.post(
            f"/api/evaluations/{pending['evaluation_id']}/retry",
            json={"idempotency_key": "x", "acknowledge_extra_cost": True},
        ).status_code
        == 404
    )
    assert pending["job_id"] not in [j["id"] for j in client.get("/api/jobs").json()]


def test_completed_history_keeps_v2_null_limits_without_regrading(client, app, monkeypatch):
    import app.free_responses as free

    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()
    with install_evaluator(monkeypatch, app):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    monkeypatch.setattr(
        free,
        "validate_evaluation",
        lambda *args: (_ for _ in ()).throw(AssertionError("regraded history")),
    )
    item = client.get(f"/api/study/{session}").json()["review"][0]
    assert item["score"] == 88
    assert item["word_limit"] == {"min": None, "max": None, "met": True}
    assert item["submission"] == {"free_text": "Tai yra medis", "audio_answer_id": None}


def test_library_deletion_preserves_active_evidence_repeat_and_session_images(
    client, app, monkeypatch
):
    import httpx
    from app.models import Card, CardImage, ImageAsset, SessionImage
    from test_evaluations import valid_result
    from test_question_images import image_bytes
    from test_retry import completed

    topic = setup_free(client, app)
    # Existing illustrations are frozen refs; no image model is enabled or called.
    with app.state.db.session() as db:
        card = db.scalar(select(Card).where(Card.topic_id == topic))
        asset = ImageAsset(
            id="frozen-image",
            filename="frozen.webp",
            owner_user_id=1,
            stage="ready",
            size=len(image_bytes("WEBP")),
        )
        db.add(asset)
        db.flush()
        db.add(CardImage(card_id=card.id, asset_id=asset.id, slot="question", alt="tree"))
        from app.question_images import asset_path

        asset_path(app.state.db, asset).write_bytes(image_bytes("WEBP"))
    session = start_free(client, topic)
    with app.state.db.session() as db:
        original = db.scalar(select(SessionCard).where(SessionCard.session_id == session))
        frozen = original.snapshot
        assert (
            db.scalar(select(SessionImage).where(SessionImage.session_card_id == original.id))
            is not None
        )
    pending = submit(client, session).json()
    assert client.delete(f"/api/topics/{topic}").status_code == 200
    result = valid_result()
    result["rubric_scores"][0]["score"] = 0
    with install_evaluator(
        monkeypatch, app, lambda req: httpx.Response(200, json=completed(result))
    ):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    review = client.get(f"/api/study/{session}").json()["review"][0]
    assert review["correct"] is False
    repeated = client.post(f"/api/study/{session}/repeat")
    assert repeated.status_code == 200, repeated.text
    from app.models import Evaluation

    with app.state.db.session() as db:
        repeated_card = db.scalar(
            select(SessionCard).where(SessionCard.session_id == repeated.json()["id"])
        )
        assert repeated_card.snapshot == frozen
        assert (
            db.scalar(
                select(SessionImage.asset_id).where(
                    SessionImage.session_card_id == repeated_card.id
                )
            )
            == "frozen-image"
        )
        assert db.scalar(select(func.count(Evaluation.id))) == 1
    assert submit(client, repeated.json()["id"], key="new-answer").status_code == 202


def test_delete_does_not_refund_family_quota_for_another_user(client, app, monkeypatch):
    topic = setup_free(client, app)
    app.state.settings.free_response_daily_request_limit = 1
    session = start_free(client, topic)
    pending = submit(client, session).json()
    with install_evaluator(monkeypatch, app):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    assert client.post("/api/study/delete", json={"session_ids": [session]}).status_code == 200
    login = client.post(
        "/api/auth/login", json={"username": "parent", "password": "parent-password"}
    )
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    second = start_free(client, topic)
    pending = submit(client, second).json()
    with install_evaluator(
        monkeypatch,
        app,
        lambda request: (_ for _ in ()).throw(AssertionError("family quota bypass")),
    ):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    result = client.get(f"/api/study/{second}/evaluations?position=0").json()
    assert result["error_code"] == "quota_exceeded" and result["status"] == "failed"
    assert client.get(f"/api/study/{second}").json()["answered"] == 0


def test_delete_during_provider_retry_prevents_next_send_and_no_revival(
    client, app, monkeypatch, retry_waits
):
    import httpx
    from app.models import Evaluation, EvaluationRequest

    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()

    def handler(request):
        assert client.post("/api/study/delete", json={"session_ids": [session]}).status_code == 200
        return httpx.Response(503, json={"error": {"message": "retry"}})

    with install_evaluator(monkeypatch, app, handler):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(EvaluationRequest.id))) == 1
        assert db.scalar(select(func.count(Evaluation.id))) == 0
        assert db.get(Job, pending["job_id"]).status == "deleted"
    assert retry_waits == [1]

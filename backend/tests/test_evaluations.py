import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from app.jobs import run_job
from app.models import Attempt, Card, CardSource, Job, SessionCard, SourcePage, StudySession
from sqlalchemy import func, select
from test_free_response_generation import candidate, setup_generation
from test_free_response_schemas import evaluation_data
from test_retry import ai_client, completed


def setup_free(client, app, enabled=True):
    topic, ref = setup_generation(client, app)
    app.state.settings.__dict__.update(free_response_enabled=enabled, openai_api_key="test-key")
    data = candidate(topic, ref)
    with app.state.db.session() as db:
        card = Card(**{k: v for k, v in data.items() if k != "sources"}, status="saved")
        db.add(card)
        db.flush()
        page = db.scalar(select(SourcePage).where(SourcePage.document_id == ref["document_id"]))
        db.add(CardSource(card_id=card.id, page_id=page.id))
    return topic


def start_free(client, topic):
    response = client.post(
        "/api/study",
        json={
            "topic_ids": [topic],
            "mode": "quiz",
            "question_types": ["free_response"],
            "include_ai_evaluated": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def submit(client, session, key="initial", answer="Tai yra medis"):
    return client.post(
        f"/api/study/{session}/answer",
        json={"position": 0, "idempotency_key": key, "free_text": answer},
    )


def valid_result():
    result = evaluation_data()
    result["point_checks"][0]["evidence"][0]["source"]["page"] = 1
    return result


def install_evaluator(monkeypatch, app, handler=None):
    import app.evaluations as module
    from app.evaluation_ai import EvaluationAI

    ai, sdk = ai_client(
        app.state.settings.data_dir,
        handler or (lambda req: httpx.Response(200, json=completed(valid_result()))),
    )
    monkeypatch.setattr(module, "EvaluationAI", lambda settings: EvaluationAI(settings, client=sdk))
    return sdk


def test_pending_final_feedback_and_private_history(client, app, monkeypatch):
    session = start_free(client, setup_free(client, app))
    response = submit(client, session)
    assert response.status_code == 202, response.text
    pending = response.json()
    resumed = client.get(f"/api/study/{session}").json()
    assert (resumed["position"], resumed["answered"], resumed["correct"]) == (0, 0, 0)
    assert "model_answer" not in json.dumps(resumed) and "source_fragments" not in json.dumps(
        resumed
    )
    status = client.get(f"/api/study/{session}/evaluations?position=0").json()
    assert status["submission"] == {"free_text": "Tai yra medis", "audio_answer_id": None}
    assert status["status"] == "queued"
    assert submit(client, session).json() == pending
    assert submit(client, session, answer="other").status_code == 409
    assert submit(client, session, key="other").status_code == 409
    with install_evaluator(monkeypatch, app):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    finished = submit(client, session)
    assert finished.status_code == 200
    assert finished.json()["score"] == 88 and finished.json()["correct"] is True
    assert finished.json()["word_count"] == 3
    resumed = client.get(f"/api/study/{session}").json()
    assert (resumed["position"], resumed["answered"], resumed["correct"]) == (1, 1, 1)
    assert resumed["review"][0]["score"] == 88
    assert (
        client.post(
            f"/api/evaluations/{pending['evaluation_id']}/retry",
            json={"idempotency_key": "retry", "acknowledge_extra_cost": True},
        ).status_code
        == 409
    )


def test_failure_retry_preserves_original_key_and_no_grade(client, app, monkeypatch):
    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()
    with install_evaluator(
        monkeypatch,
        app,
        lambda req: httpx.Response(
            400, json={"error": {"message": "PRIVATE PROMPT answer secret"}}
        ),
    ):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    status = client.get(f"/api/study/{session}/evaluations?position=0").json()
    assert status["status"] == "failed" and "PRIVATE" not in json.dumps(status)
    assert client.get(f"/api/study/{session}").json()["answered"] == 0
    assert client.post(f"/api/jobs/{pending['job_id']}/retry").status_code == 409
    route = f"/api/evaluations/{pending['evaluation_id']}/retry"
    assert (
        client.post(
            route, json={"idempotency_key": "retry", "acknowledge_extra_cost": "true"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            route, json={"idempotency_key": "retry", "acknowledge_extra_cost": False}
        ).status_code
        == 422
    )
    retry = client.post(route, json={"idempotency_key": "retry", "acknowledge_extra_cost": True})
    assert retry.status_code == 202
    assert submit(client, session).status_code == 202
    with install_evaluator(monkeypatch, app):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    assert submit(client, session).json()["score"] == 88
    from app.models import EvaluationRequest

    with app.state.db.session() as db:
        assert db.scalar(select(func.count(EvaluationRequest.id))) == 2
        assert db.scalar(select(func.count(Attempt.id))) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"free_text": "medis", "text": "medis"},
        {"free_text": "medis", "_grading": None},
        {"free_text": "medis", "audio_answer_id": "voice"},
        {"free_text": "word " * 2001},
        {"free_text": "a" * 10001},
    ],
)
def test_invalid_submission_never_queues(client, app, payload):
    session = start_free(client, setup_free(client, app))
    response = client.post(
        f"/api/study/{session}/answer", json={"position": 0, "idempotency_key": "key", **payload}
    )
    assert response.status_code == 422
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(Job.id)).where(Job.kind == "evaluate_response")) == 0


def test_explicit_optin_runtime_and_default_exclusion(client, app):
    topic = setup_free(client, app, enabled=False)
    body = {"topic_ids": [topic], "mode": "quiz", "question_types": ["free_response"]}
    assert client.post("/api/study", json=body).status_code == 422
    assert client.post("/api/study", json={**body, "include_ai_evaluated": True}).status_code == 409
    app.state.settings.free_response_enabled = True
    app.state.settings.openai_api_key = ""
    assert client.post("/api/study", json={**body, "include_ai_evaluated": True}).status_code == 409
    app.state.settings.openai_api_key = "test-key"
    assert client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).status_code == 422
    assert (
        client.post("/api/study", json={"topic_ids": [topic], "mode": "flashcard"}).status_code
        == 422
    )
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(StudySession.id))) == 0


def test_two_tabs_and_workers_apply_once(client, app, monkeypatch):
    session = start_free(client, setup_free(client, app))
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: submit(client, session), range(2)))
    assert [r.status_code for r in responses] == [202, 202]
    assert responses[0].json() == responses[1].json()
    pending = responses[0].json()
    with install_evaluator(monkeypatch, app):
        with ThreadPoolExecutor(2) as pool:
            list(
                pool.map(lambda _: run_job(app.state.db, app.state.ai, pending["job_id"]), range(2))
            )
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(Attempt.id))) == 1
        assert db.get(StudySession, session).position == 1


def test_free_explain_and_malformed_revealed_flag_cannot_leak(client, app):
    session = start_free(client, setup_free(client, app))
    with app.state.db.session() as db:
        db.scalar(select(SessionCard).where(SessionCard.session_id == session)).revealed = True
    assert client.post(f"/api/study/{session}/explain", json={"position": 0}).status_code == 409
    assert client.post(f"/api/study/{session}/reveal", json={"position": 0}).status_code == 409
    assert "model_answer" not in client.get(f"/api/study/{session}").text


def test_availability_reports_preparation_and_runtime_separately(client, app):
    topic = setup_free(client, app, enabled=False)
    value = client.get(f"/api/topics/{topic}").json()["practice_availability"]
    assert value["free_response"]["ready_count"] == 1
    assert value["free_response"]["runtime_unavailable"] is True
    assert value["flashcard"]["ready_count"] == 0
    app.state.settings.free_response_enabled = True
    assert (
        client.get(f"/api/topics/{topic}").json()["practice_availability"]["free_response"][
            "runtime_unavailable"
        ]
        is False
    )
    with app.state.db.session() as db:
        db.scalar(select(Card).where(Card.topic_id == topic)).status = "draft"
    value = client.get(f"/api/topics/{topic}").json()["practice_availability"]["free_response"]
    assert value["ready_count"] == 0 and value["draft_count"] == 1
    response = client.post(
        "/api/study",
        json={
            "topic_ids": [topic],
            "mode": "quiz",
            "question_types": ["free_response"],
            "include_ai_evaluated": True,
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["missing_pairs"] == [
        {"topic_id": topic, "question_type": "free_response"}
    ]


def test_each_transient_send_is_charged_and_quota_stops_retry(
    client, app, monkeypatch, retry_waits
):
    from app.models import EvaluationRequest

    session = start_free(client, setup_free(client, app))
    app.state.settings.free_response_daily_request_limit = 2
    pending = submit(client, session).json()

    def handler(request):
        # A separate connection can acquire the write lock during external IO.
        from sqlalchemy import text

        with app.state.db.session() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            db.get(StudySession, session).updated = __import__("datetime").datetime(2026, 1, 1)
        return httpx.Response(503, json={"error": {"message": "busy"}})

    with install_evaluator(monkeypatch, app, handler):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    status = client.get(f"/api/study/{session}/evaluations?position=0").json()
    assert status["status"] == "failed" and status["error_code"] == "quota_exceeded"
    with app.state.db.session() as db:
        records = list(db.scalars(select(EvaluationRequest)))
        assert [r.attempt_no for r in records] == [1, 2]
        assert db.scalar(select(func.count(Attempt.id))) == 0
    assert retry_waits == [1, 2]
    retry = client.post(
        f"/api/evaluations/{pending['evaluation_id']}/retry",
        json={"idempotency_key": "charged-retry", "acknowledge_extra_cost": True},
    )
    assert retry.status_code == 202
    other = start_free(client, topic=client.get(f"/api/study/{session}").json()["topic_ids"][0])
    assert submit(client, other, key="charged-retry").status_code == 409
    with install_evaluator(monkeypatch, app, lambda req: pytest.fail("quota bypassed")):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    assert (
        client.get(f"/api/study/{session}/evaluations?position=0").json()["error_code"]
        == "quota_exceeded"
    )
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(EvaluationRequest.id))) == 2


def test_timeout_is_unknown_without_grade_or_automatic_restart_send(
    client, app, monkeypatch, retry_waits
):
    from app.jobs import recover_jobs
    from app.models import EvaluationRequest

    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()

    def timeout(request):
        raise httpx.ReadTimeout("secret answer", request=request)

    with install_evaluator(monkeypatch, app, timeout):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    status = client.get(f"/api/study/{session}/evaluations?position=0").json()
    assert status["status"] == "unknown" and "secret" not in json.dumps(status)
    recover_jobs(app.state.db)
    run_job(app.state.db, None, pending["job_id"])
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(EvaluationRequest.id))) == 3
        assert db.scalar(select(func.count(Attempt.id))) == 0


def test_default_mixed_and_flashcard_keep_only_old_types_and_runtime_change_blocks_new_answer(
    client, app
):
    topic = setup_free(client, app)
    with app.state.db.session() as db:
        db.add(
            Card(
                topic_id=topic,
                question_type="written",
                exercise={"accepted_answers": ["medis"], "case_sensitive": False},
                question="Kas?",
                answer="medis",
                mode="quiz",
                status="saved",
                options=[],
            )
        )
    for mode in ["quiz", "flashcard"]:
        response = client.post(
            "/api/study", json={"topic_ids": [topic], "mode": mode, "include_ai_evaluated": True}
        )
        assert response.status_code == 200, response.text
        assert response.json()["question_types"] == {"written": 1}
        assert response.json()["count"] == 1
    session = start_free(client, topic)
    app.state.settings.free_response_enabled = False
    assert submit(client, session).status_code == 409
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(Job.id)).where(Job.kind == "evaluate_response")) == 0


@pytest.mark.parametrize("insufficient", [True, False])
def test_invalid_or_insufficient_feedback_does_not_turn_into_incorrect_attempt(
    client, app, monkeypatch, insufficient
):
    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()
    result = valid_result()
    if insufficient:
        result.update(
            assessability="insufficient_context",
            reason="private source detail",
            rubric_scores=[],
            point_checks=[],
        )
    else:
        result["point_checks"][0]["point_id"] = "invented"
    with install_evaluator(
        monkeypatch, app, lambda request: httpx.Response(200, json=completed(result))
    ):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    status = client.get(f"/api/study/{session}/evaluations?position=0").json()
    assert status["status"] == "failed"
    assert status["error_code"] == ("insufficient_context" if insufficient else "failed")
    assert "private source detail" not in json.dumps(status)
    assert client.get(f"/api/study/{session}").json()["answered"] == 0
    assert client.post(f"/api/study/{session}/repeat").status_code == 422


@pytest.mark.parametrize("change", [{"free_response_enabled": False}, {"openai_api_key": ""}])
def test_queued_runtime_unavailable_is_not_a_provider_failure_or_charge(client, app, change):
    from app.models import EvaluationRequest

    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()
    for key, value in change.items():
        setattr(app.state.settings, key, value)
    run_job(app.state.db, app.state.ai, pending["job_id"])
    status = client.get(f"/api/study/{session}/evaluations?position=0").json()
    assert status["error_code"] == "runtime_unavailable"
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(EvaluationRequest.id))) == 0
        assert db.scalar(select(func.count(Attempt.id))) == 0

import copy
from types import SimpleNamespace

import pytest
from app.jobs import run_job
from app.models import Card, Job
from app.schemas import GeneratedCard
from test_study import saved_cards


def fixture(client, app):
    topic, cards = saved_cards(client, app, count=2)
    cards = client.get(f"/api/cards?topic_id={topic}").json()
    original = cards[0]
    calls = []

    def regenerate(card, sources):
        calls.append((card, sources))
        return SimpleNamespace(
            card=GeneratedCard(
                topic_id=topic,
                question="Новая река?",
                answer="Нил",
                mode="quiz",
                options=["Нил", "Дон"],
                correct_indices=[0],
                sources=[{"document_id": sources[0]["document_id"], "page": sources[0]["page"]}],
                language=card["language"],
            ),
            insufficient_reason=None,
        )

    app.state.ai.regenerate = regenerate
    return topic, original, cards[1], calls


def request(client, card, key="regen", **kwargs):
    return client.post(
        f"/api/cards/{card['id']}/regenerate",
        json={"version": card["version"], "idempotency_key": key, **kwargs},
    )


def completed(client, app):
    topic, original, other, calls = fixture(client, app)
    response = request(client, original)
    assert response.status_code == 200, response.text
    job = response.json()
    run_job(app.state.db, app.state.ai, job["id"])
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert result["status"] == "succeeded", result
    return topic, original, other, calls, result


def test_request_preview_replay_and_atomic_apply_preserve_other_cards_and_history(client, app):
    topic, original, other, calls = fixture(client, app)
    session = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    response = request(client, original)
    assert response.status_code == 200, response.text
    job = response.json()
    assert request(client, original, key="double-click").json()["id"] == job["id"]
    run_job(app.state.db, app.state.ai, job["id"])
    assert len(calls) == 1
    assert request(client, original, key="reopen-preview").json()["id"] == job["id"]
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert client.get(f"/api/cards?topic_id={topic}").json() == [original, other]
    body = {"candidate": result["result"]["candidate"]}
    route = f"/api/jobs/{job['id']}/apply-regeneration"
    applied = client.post(route, json=body)
    assert applied.status_code == 200, applied.text
    assert applied.json()["question"] == "Новая река?"
    assert applied.json()["version"] == original["version"] + 1
    assert (
        applied.json()["status"] == original["status"]
        and applied.json()["job_id"] == original["job_id"]
    )
    assert client.get(f"/api/study/{session['id']}").json()["card"] == session["card"]
    with app.state.db.session() as db:
        assert db.get(Card, other["id"]).question == other["question"]
        db.get(Card, original["id"]).question = "Later manual edit"
        db.get(Card, original["id"]).version += 1
    assert client.post(route, json=body).json() == applied.json()
    changed = copy.deepcopy(body)
    changed["candidate"]["question"] = "Different request"
    assert client.post(route, json=changed).status_code == 409
    assert client.post(f"/api/jobs/{job['id']}/discard-regeneration").status_code == 409


@pytest.mark.parametrize(
    "field,value",
    [("question_type", "written"), ("language", "ru"), ("topic_id", 987), ("mode", "flashcard")],
)
def test_model_cannot_switch_question_type_language_topic_or_mode(client, app, field, value):
    _, original, _, _ = fixture(client, app)
    regenerate = app.state.ai.regenerate

    def changed(*args):
        result = regenerate(*args)
        setattr(result.card, field, value)
        return result

    app.state.ai.regenerate = changed
    job = request(client, original).json()
    assert "id" in job, job
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"
    with app.state.db.session() as db:
        assert db.get(Card, original["id"]).version == original["version"]


def test_discard_clears_sources_and_candidate_and_another_variant_is_explicit(client, app):
    _, original, _, calls, job = completed(client, app)
    another = request(client, original, key="another", another_variant=True)
    assert another.status_code == 200, another.text
    assert another.json()["id"] != job["id"]
    run_job(app.state.db, app.state.ai, another.json()["id"])
    assert len(calls) == 2
    identifier = another.json()["id"]
    route = f"/api/jobs/{identifier}/discard-regeneration"
    assert client.post(route).status_code == 200
    assert client.post(route).status_code == 200
    assert client.get(f"/api/jobs/{identifier}").json()["result"].get("candidate") is None
    with app.state.db.session() as db:
        assert "snapshot" not in db.get(Job, identifier).payload
        assert db.get(Card, original["id"]).version == original["version"]
    assert (
        client.post(
            f"/api/jobs/{identifier}/apply-regeneration",
            json={"candidate": job["result"]["candidate"]},
        ).status_code
        == 409
    )


def test_apply_conflict_and_duplicate_do_not_mutate_original(client, app):
    _, original, other, _, job = completed(client, app)
    candidate = job["result"]["candidate"]
    duplicate = copy.deepcopy(candidate)
    duplicate.update(
        question=other["question"],
        answer=other["answer"],
        options=other["options"],
        correct_index=other["correct_index"],
        correct_indices=other["correct_indices"],
    )
    route = f"/api/jobs/{job['id']}/apply-regeneration"
    assert client.post(route, json={"candidate": duplicate}).status_code == 409
    with app.state.db.session() as db:
        db.get(Card, original["id"]).version += 1
    assert client.post(route, json={"candidate": candidate}).status_code == 409


@pytest.mark.parametrize("remove", ["card", "topic", "subject"])
def test_deletion_clears_ready_candidate_and_inflight_worker_cannot_restore_it(client, app, remove):
    topic, original, _, _, job = completed(client, app)
    path = {
        "card": f"/api/cards/{original['id']}",
        "topic": f"/api/topics/{topic}",
        "subject": f"/api/subjects/{client.get(f'/api/topics/{topic}').json()['subject_id']}",
    }[remove]
    assert client.delete(path).status_code == 200
    with app.state.db.session() as db:
        row = db.get(Job, job["id"])
        assert row.result is None and "snapshot" not in row.payload
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.post(
        f"/api/jobs/{job['id']}/apply-regeneration", json={"candidate": job["result"]["candidate"]}
    ).status_code in [404, 409]


def test_private_candidates_require_owner_login_and_csrf(client, app):
    _, original, _, _, job = completed(client, app)
    assert (
        client.post(
            f"/api/jobs/{job['id']}/discard-regeneration", headers={"X-CSRF-Token": ""}
        ).status_code
        == 403
    )
    login = client.post(
        "/api/auth/login", json={"username": "parent", "password": "parent-password"}
    ).json()
    client.headers.update({"X-CSRF-Token": login["csrf_token"]})
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
    assert (
        client.post(
            f"/api/jobs/{job['id']}/apply-regeneration",
            json={"candidate": job["result"]["candidate"]},
        ).status_code
        == 404
    )
    assert client.post(f"/api/jobs/{job['id']}/discard-regeneration").status_code == 404
    separate = request(client, original, key="parent").json()
    assert separate["id"] != job["id"]


def test_insufficient_context_and_late_worker_after_delete_leave_original_intact(client, app):
    _, original, _, _ = fixture(client, app)
    app.state.ai.regenerate = lambda *args: SimpleNamespace(
        card=None, insufficient_reason="Недостаточно материала"
    )
    job = request(client, original)
    assert job.status_code == 200, job.text
    run_job(app.state.db, app.state.ai, job.json()["id"])
    assert (
        client.get(f"/api/jobs/{job.json()['id']}").json()["result"]["insufficient_reason"]
        == "Недостаточно материала"
    )

    def deleting(card, sources):
        assert client.delete(f"/api/cards/{original['id']}").status_code == 200
        return SimpleNamespace(
            card=GeneratedCard(
                topic_id=original["topic_id"],
                question="Late",
                answer="Нил",
                mode="quiz",
                options=["Нил", "Дон"],
                correct_indices=[0],
                sources=[{"document_id": sources[0]["document_id"], "page": sources[0]["page"]}],
            ),
            insufficient_reason=None,
        )

    app.state.ai.regenerate = deleting
    pending = request(client, original, key="late", another_variant=True).json()
    run_job(app.state.db, app.state.ai, pending["id"])
    assert client.get(f"/api/jobs/{pending['id']}").json()["status"] == "cancelled"


def test_parallel_apply_and_discard_have_one_winning_transition(client, app):
    from concurrent.futures import ThreadPoolExecutor

    _, original, _, _, job = completed(client, app)
    with ThreadPoolExecutor(max_workers=2) as pool:
        saving = pool.submit(
            client.post,
            f"/api/jobs/{job['id']}/apply-regeneration",
            json={"candidate": job["result"]["candidate"]},
        )
        discarding = pool.submit(client.post, f"/api/jobs/{job['id']}/discard-regeneration")
        results = [saving.result(), discarding.result()]
    assert sorted(r.status_code for r in results) == [200, 409]
    with app.state.db.session() as db:
        card = db.get(Card, original["id"])
        assert card.version == original["version"] + int(results[0].status_code == 200)


def test_regeneration_keeps_a_draft_a_draft(client, app):
    _, original, _, _ = fixture(client, app)
    with app.state.db.session() as db:
        db.get(Card, original["id"]).status = "draft"
    job = request(client, original).json()
    run_job(app.state.db, app.state.ai, job["id"])
    candidate = client.get(f"/api/jobs/{job['id']}").json()["result"]["candidate"]
    result = client.post(f"/api/jobs/{job['id']}/apply-regeneration", json={"candidate": candidate})
    assert result.status_code == 200 and result.json()["status"] == "draft"


def test_real_sdk_regenerates_with_structured_output_and_three_transient_attempts(
    tmp_path, monkeypatch
):
    import httpx
    from test_retry import ai_client
    from test_retry import completed as sdk_completed

    monkeypatch.setattr("app.retry.time.sleep", lambda delay: None)
    attempts = []
    candidate = GeneratedCard(
        topic_id=1,
        question="Reka?",
        answer="Nil",
        mode="quiz",
        options=["Nil", "Don"],
        correct_indices=[0],
        sources=[{"document_id": 1, "page": 1}],
        language="pl",
    )

    def respond(request):
        import json

        body = json.loads(request.content)
        assert body["text"]["format"]["type"] == "json_schema"
        assert body["text"]["format"]["strict"] is True
        attempts.append(request)
        return (
            httpx.Response(503)
            if len(attempts) < 3
            else httpx.Response(
                200,
                json=sdk_completed({"card": candidate.model_dump(), "insufficient_reason": None}),
            )
        )

    ai, sdk = ai_client(tmp_path, respond)
    with sdk:
        result = ai.regenerate(
            {"topic_id": 1, "language": "pl"}, [{"document_id": 1, "page": 1, "text": "Nil"}]
        )
    assert len(attempts) == 3 and result.card.language == "pl"


def test_contradictory_model_result_is_rejected_without_replacing_question(client, app):
    _, original, _, _ = fixture(client, app)
    regenerate = app.state.ai.regenerate

    def contradictory(*args):
        result = regenerate(*args)
        result.insufficient_reason = "Not enough material"
        return result

    app.state.ai.regenerate = contradictory
    job = request(client, original).json()
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"


@pytest.mark.parametrize("kind", ["written", "gap", "ending", "matching", "ordering"])
def test_typed_regeneration_preserves_type_and_validated_complete_solution(client, app, kind):
    from exercise_cases import CASES
    from test_exercise_study import saved_exercise

    topic, original = saved_exercise(client, app, kind)
    app.state.ai.regenerate = lambda snapshot, sources: SimpleNamespace(
        card=GeneratedCard(
            topic_id=topic,
            question="Updated typed question",
            answer="",
            mode="quiz",
            options=[],
            question_type=kind,
            exercise=CASES[kind],
            sources=[{"document_id": sources[0]["document_id"], "page": sources[0]["page"]}],
            language=snapshot["language"],
        ),
        insufficient_reason=None,
    )
    response = request(client, original)
    assert response.status_code == 200, response.text
    run_job(app.state.db, app.state.ai, response.json()["id"])
    job = client.get(f"/api/jobs/{response.json()['id']}").json()
    assert job["status"] == "succeeded", job
    candidate = job["result"]["candidate"]
    result = client.post(f"/api/jobs/{job['id']}/apply-regeneration", json={"candidate": candidate})
    assert result.status_code == 200, result.text
    assert result.json()["question_type"] == kind and result.json()["answer"] == candidate["answer"]

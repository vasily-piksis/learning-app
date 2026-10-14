import copy
from types import SimpleNamespace

import pytest
from app.jobs import run_job
from app.models import Job
from app.schemas import Generated, GeneratedCard, SourceRef
from conftest import make_topic
from exercise_cases import CASES
from fakes import FixtureAI, ready_document


class TypedFixtureAI(FixtureAI):
    def generate(self, topic_id, sources, mode, count, **kwargs):
        self.inputs.append(kwargs)
        quotas = kwargs.get("type_counts", {"choice": count})
        cards = []
        for kind, amount in quotas.items():
            for index in range(amount):
                cards.append(
                    GeneratedCard.model_validate(
                        {
                            "topic_id": topic_id,
                            "question": f"{kind} {index}",
                            "answer": "generated formatting",
                            "mode": mode,
                            "question_type": kind,
                            "exercise": copy.deepcopy(CASES.get(kind)),
                            "options": ["generated formatting", "other"]
                            if kind == "choice"
                            else [],
                            "correct_index": 0 if kind == "choice" else None,
                            "sources": [
                                {
                                    "document_id": sources[0]["document_id"],
                                    "page": sources[0]["page"],
                                }
                            ],
                        }
                    )
                )
        return Generated(cards=cards, insufficient_reason=None)


def setup_generation(client, app):
    app.state.ai = FixtureAI()
    topic = make_topic(client)
    ready_document(client, app, topic)
    app.state.ai = TypedFixtureAI()
    return topic


def test_generation_preserves_requested_types_and_distributes_total_quota(client, app):
    topic = setup_generation(client, app)
    response = client.post(
        "/api/generate",
        json={
            "topic_ids": [topic],
            "question_types": list(CASES),
            "practice_goal": "language",
            "count": 7,
        },
    )
    assert response.status_code == 200, response.text
    run_job(app.state.db, app.state.ai, response.json()["id"])
    result = client.get(f"/api/jobs/{response.json()['id']}").json()
    assert result["status"] == "succeeded", result
    cards = client.get(f"/api/cards?job_id={result['id']}").json()
    assert len(cards) == 7 and {c["question_type"] for c in cards} == set(CASES)
    assert cards[0]["answer"] == "stalas / lentelė" and cards[0]["options"] == []
    assert app.state.ai.inputs[0]["type_counts"] == {
        "written": 2,
        "gap": 2,
        "ending": 1,
        "matching": 1,
        "ordering": 1,
    }


@pytest.mark.parametrize(
    "body",
    [
        {"question_types": ["ending"], "practice_goal": "content"},
        {"question_types": ["ordering"], "practice_goal": "content"},
        {"question_types": []},
        {"question_types": ["choice", "choice"]},
        {"question_types": ["written", "gap"], "count": 1},
        {"target_language": "ru"},
    ],
)
def test_invalid_generation_request_makes_no_model_job(client, app, body):
    topic = setup_generation(client, app)
    response = client.post("/api/generate", json={"topic_ids": [topic], "count": 2, **body})
    assert response.status_code == 422, response.text
    assert not app.state.ai.inputs


def test_generation_http_replays_do_not_create_another_job(client, app):
    topic = setup_generation(client, app)
    body = {
        "topic_ids": [topic],
        "count": 1,
        "question_types": ["written"],
        "idempotency_key": "generate-once",
    }
    first = client.post("/api/generate", json=body).json()
    assert client.post("/api/generate", json=body).json()["id"] == first["id"]
    run_job(app.state.db, app.state.ai, first["id"])
    assert client.post("/api/generate", json=body).json()["id"] == first["id"]
    assert len(app.state.ai.inputs) == 1
    assert client.post("/api/generate", json={**body, "count": 2}).status_code == 409
    fresh = client.post("/api/generate", json={**body, "idempotency_key": "intentional-new"}).json()
    run_job(app.state.db, app.state.ai, fresh["id"])
    assert client.get(f"/api/cards?job_id={fresh['id']}").json() == []


def test_unsupported_type_is_reported_without_substituting_another_type(client, app):
    topic = setup_generation(client, app)

    def unsupported(*args, **kwargs):
        return SimpleNamespace(
            cards=[],
            insufficient_reason=None,
            unsupported_types=[
                SimpleNamespace(question_type="ending", reason="No grammatical context")
            ],
        )

    app.state.ai.generate = unsupported
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
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert result["status"] == "succeeded" and result["result"]["card_ids"] == []
    assert result["result"]["unsupported_types"] == [
        {"question_type": "ending", "reason": "No grammatical context"}
    ]
    assert "No grammatical context" in " ".join(result["result"]["warnings"])


def test_old_pending_translation_is_blocked_without_model_call(client, app):
    topic = setup_generation(client, app)
    job = client.post("/api/generate", json={"topic_ids": [topic], "count": 1}).json()
    with app.state.db.session() as db:
        row = db.get(Job, job["id"])
        row.payload = {**row.payload, "target_language": "ru"}
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"
    assert not app.state.ai.inputs


def test_sdk_response_schema_is_closed_and_has_nested_typed_exercises():
    from openai.lib._pydantic import to_strict_json_schema

    schema = to_strict_json_schema(Generated)
    assert "exercise" in schema["$defs"]["GeneratedCard"]["properties"]
    assert "anyOf" not in schema

    def check(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value.get("properties", {}))
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(schema)


@pytest.mark.parametrize(
    "fault", ["foreign_source", "foreign_topic", "wrong_type", "over_quota", "unsupported_conflict"]
)
def test_invalid_model_result_never_saves_partial_questions(client, app, fault):
    topic = setup_generation(client, app)
    original = app.state.ai.generate

    def corrupt(*args, **kwargs):
        result = original(*args, **kwargs)
        card = result.cards[0]
        if fault == "foreign_source":
            card.sources = [SourceRef(document_id=99999, page=1)]
        elif fault == "foreign_topic":
            card.topic_id = 99999
        elif fault == "wrong_type":
            card.question_type = "choice"
        elif fault == "over_quota":
            result.cards.append(card.model_copy())
        else:
            from app.schemas import UnsupportedType

            result.unsupported_types = [
                UnsupportedType(question_type="written", reason="No sources")
            ]
        return result

    app.state.ai.generate = corrupt
    job = client.post(
        "/api/generate", json={"topic_ids": [topic], "count": 1, "question_types": ["written"]}
    ).json()
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"
    assert client.get(f"/api/cards?job_id={job['id']}").json() == []

import json

import httpx
import pytest
from app.ai import AI, AIError
from app.config import Settings
from app.schemas import Extraction
from openai import OpenAI


def completed(data):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "model": "gpt-6-luna",
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps(data), "annotations": []}],
            }
        ],
    }


def extraction():
    return {"page": 1, "text": "Obywatel.", "warnings": [], "language": "pl"}


def ai_client(tmp_path, handler):
    # Deliberately use the SDK default retry setting: AI must prevent nested retries.
    sdk = OpenAI(
        api_key="test-only", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    return AI(Settings(_env_file=None, data_dir=tmp_path), client=sdk), sdk


def test_first_success_has_no_retry_delay(tmp_path, retry_waits):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=completed(extraction()))

    ai, sdk = ai_client(tmp_path, handler)
    with sdk:
        assert ai.parse(Extraction, [], 2000).text == "Obywatel."
    assert len(calls) == 1 and retry_waits == []


@pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503, 504])
def test_ai_retries_transient_http_within_three_attempts(tmp_path, retry_waits, status):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(
                status, json={"error": {"code": "temporary", "message": "unavailable"}}
            )
        return httpx.Response(200, json=completed(extraction()))

    ai, sdk = ai_client(tmp_path, handler)
    with sdk:
        assert ai.parse(Extraction, [], 2000).language == "pl"
    assert len(calls) == 3 and retry_waits == [1, 2]
    payloads = [json.loads(request.content) for request in calls]
    assert all(payload == payloads[0] for payload in payloads)
    assert payloads[0]["store"] is False


def test_ai_exhaustion_never_multiplies_sdk_and_application_retries(tmp_path, retry_waits):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"error": {"message": "sensitive-provider-detail"}})

    ai, sdk = ai_client(tmp_path, handler)
    with sdk, pytest.raises(AIError) as error:
        ai.parse(Extraction, [], 2000)
    assert len(calls) == 3 and retry_waits == [1, 2]
    assert "sensitive-provider-detail" not in str(error.value)


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
def test_ai_retries_network_failures(tmp_path, retry_waits, failure):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            raise failure("temporary", request=request)
        return httpx.Response(200, json=completed(extraction()))

    ai, sdk = ai_client(tmp_path, handler)
    with sdk:
        assert ai.parse(Extraction, [], 2000).text == "Obywatel."
    assert len(calls) == 3 and retry_waits == [1, 2]


@pytest.mark.parametrize(
    "status,code,kind",
    [
        (400, "invalid_prompt", "invalid_request_error"),
        (401, "invalid_api_key", "invalid_request_error"),
        (403, "permission_denied", "invalid_request_error"),
        (404, "model_not_found", "invalid_request_error"),
        (422, "invalid_request", "invalid_request_error"),
        (429, "insufficient_quota", "insufficient_quota"),
        (429, "credit_balance_exhausted", "insufficient_quota"),
        (429, "project_spend_limit_exceeded", "insufficient_quota"),
        (429, "organization_spend_limit_exceeded", "insufficient_quota"),
        (429, "organization_usage_limit_exceeded", "insufficient_quota"),
    ],
)
def test_ai_permanent_failure_is_not_retried(tmp_path, retry_waits, status, code, kind):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, json={"error": {"message": "unavailable", "code": code, "type": kind}}
        )

    ai, sdk = ai_client(tmp_path, handler)
    with sdk, pytest.raises(AIError):
        ai.parse(Extraction, [], 2000)
    assert len(calls) == 1 and retry_waits == []


@pytest.mark.parametrize(
    "headers,waits,count",
    [
        ({"Retry-After": "5"}, [5], 2),
        ({"Retry-After": "120"}, [], 1),
        ({"retry-after-ms": "5000"}, [5], 2),
    ],
)
def test_ai_honors_server_retry_after(tmp_path, retry_waits, headers, waits, count):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers=headers, json={"error": {"message": "busy"}})
        return httpx.Response(200, json=completed(extraction()))

    ai, sdk = ai_client(tmp_path, handler)
    with sdk:
        if count == 1:
            with pytest.raises(AIError):
                ai.parse(Extraction, [], 2000)
        else:
            assert ai.parse(Extraction, [], 2000).text == "Obywatel."
    assert len(calls) == count and retry_waits == waits


@pytest.mark.parametrize(
    "code,retried",
    [("server_error", True), ("rate_limit_exceeded", True), ("invalid_prompt", False)],
)
def test_ai_classifies_failed_response_before_saving(tmp_path, retry_waits, code, retried):
    calls = []

    def handler(request):
        calls.append(request)
        response = completed(extraction())
        if len(calls) < 3:
            response.update(
                status="failed",
                output=[],
                error={"code": code, "message": "sensitive-provider-detail"},
            )
        return httpx.Response(200, json=response)

    ai, sdk = ai_client(tmp_path, handler)
    with sdk:
        if retried:
            assert ai.parse(Extraction, [], 2000).text == "Obywatel."
        else:
            with pytest.raises(AIError):
                ai.parse(Extraction, [], 2000)
    assert len(calls) == (3 if retried else 1)
    assert retry_waits == ([1, 2] if retried else [])


@pytest.mark.parametrize(
    "headers,count,waits",
    [
        ({"Retry-After": "5"}, 2, [5]),
        ({"retry-after-ms": "5000"}, 2, [5]),
        ({"Retry-After": "120"}, 1, []),
        ({"retry-after-ms": "120000"}, 1, []),
        ({"Retry-After": "Tue, 13 Oct 2026 00:00:05 GMT"}, 2, [5]),
        ({"x-should-retry": "false"}, 1, []),
    ],
)
def test_failed_http_200_response_honors_server_directives(
    tmp_path, monkeypatch, retry_waits, headers, count, waits
):
    import time

    monkeypatch.setattr(time, "time", lambda: 1791849600)
    calls = []

    def handler(request):
        calls.append(request)
        response = completed(extraction())
        if len(calls) == 1:
            response.update(
                status="failed", output=[], error={"code": "rate_limit_exceeded", "message": "busy"}
            )
        return httpx.Response(200, json=response, headers=headers)

    ai, sdk = ai_client(tmp_path, handler)
    with sdk:
        if count == 1:
            with pytest.raises(AIError):
                ai.parse(Extraction, [], 2000)
        else:
            assert ai.parse(Extraction, [], 2000).text == "Obywatel."
    assert len(calls) == count and retry_waits == waits


def test_ai_honors_explicit_server_no_retry(tmp_path, retry_waits):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            503, headers={"x-should-retry": "false"}, json={"error": {"message": "busy"}}
        )

    ai, sdk = ai_client(tmp_path, handler)
    with sdk, pytest.raises(AIError):
        ai.parse(Extraction, [], 2000)
    assert len(calls) == 1 and retry_waits == []


def test_ai_retries_transient_status_even_with_malformed_error_metadata(tmp_path, retry_waits):
    calls = []

    def handler(request):
        calls.append(request)
        return (
            httpx.Response(503, json={"error": {"code": [], "type": {}}})
            if len(calls) == 1
            else httpx.Response(200, json=completed(extraction()))
        )

    ai, sdk = ai_client(tmp_path, handler)
    with sdk:
        assert ai.parse(Extraction, [], 2000).text == "Obywatel."
    assert len(calls) == 2 and retry_waits == [1]


def test_production_ai_client_cannot_multiply_retry_budget(tmp_path, monkeypatch, retry_waits):
    from app import ai as module

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"error": {"message": "busy"}})

    class BoundarySDK(OpenAI):
        def __init__(self, **kwargs):
            super().__init__(
                http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs
            )

    monkeypatch.setattr(module, "OpenAI", BoundarySDK)
    ai = AI(Settings(_env_file=None, data_dir=tmp_path, openai_api_key="test-only"))
    with ai.client, pytest.raises(AIError):
        ai.parse(Extraction, [], 2000)
    assert len(calls) == 3 and retry_waits == [1, 2]


def test_retry_delays_include_bounded_jitter(tmp_path, monkeypatch, retry_waits):
    import secrets

    monkeypatch.setattr(secrets, "randbelow", lambda _: 249)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"error": {"message": "busy"}})

    ai, sdk = ai_client(tmp_path, handler)
    with sdk, pytest.raises(AIError):
        ai.parse(Extraction, [], 2000)
    assert len(calls) == 3 and retry_waits == [1.249, 2.249]


@pytest.mark.parametrize("change", ["invalid_json", "refusal", "incomplete"])
def test_ai_content_errors_are_not_paid_for_again(tmp_path, retry_waits, change):
    response = completed(extraction())
    if change == "invalid_json":
        response["output"][0]["content"][0]["text"] = "not JSON"
    elif change == "refusal":
        response["output"][0]["content"] = [{"type": "refusal", "refusal": "cannot answer"}]
    else:
        response["status"] = "incomplete"
        response["incomplete_details"] = {"reason": "max_output_tokens"}
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response)

    ai, sdk = ai_client(tmp_path, handler)
    with sdk, pytest.raises(AIError):
        ai.parse(Extraction, [], 2000)
    assert len(calls) == 1 and retry_waits == []


def test_generation_retry_is_atomic_and_can_be_repeated_manually(client, app, retry_waits):
    from app.jobs import run_job
    from conftest import make_topic
    from fakes import FixtureAI, ready_document

    app.state.ai = FixtureAI()
    topic = make_topic(client)
    ready_document(client, app, topic)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) <= 3:
            return httpx.Response(503, json={"error": {"message": "busy"}})
        context = json.loads(json.loads(request.content)["input"][1]["content"])
        source = context["sources"][0]
        return httpx.Response(
            200,
            json=completed(
                {
                    "cards": [
                        {
                            "topic_id": topic,
                            "question": "Kim jest obywatel?",
                            "answer": "Członek państwa.",
                            "mode": "quiz",
                            "options": ["Członek państwa.", "Miasto."],
                            "correct_index": 0,
                            "language": "pl",
                            "sources": [
                                {"document_id": source["document_id"], "page": source["page"]}
                            ],
                        }
                    ],
                    "insufficient_reason": None,
                }
            ),
        )

    ai, sdk = ai_client(app.state.settings.data_dir, handler)
    app.state.ai = ai
    job = client.post("/api/generate", json={"topic_ids": [topic], "count": 1}).json()
    with sdk:
        run_job(app.state.db, ai, job["id"])
        assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"
        assert client.get(f"/api/cards?job_id={job['id']}").json() == []
        assert len(calls) == 3
        assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 200
        run_job(app.state.db, ai, job["id"])
        run_job(app.state.db, ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "succeeded"
    assert len(client.get(f"/api/cards?job_id={job['id']}").json()) == 1
    assert len(calls) == 4 and retry_waits == [1, 2]

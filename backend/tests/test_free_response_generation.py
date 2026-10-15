import copy
import json

import httpx
import pytest
from app.jobs import run_job
from app.models import SourcePage
from app.schemas import GenerateBody
from conftest import make_topic
from fakes import FixtureAI, ready_document
from test_evaluation_ai import assert_closed
from test_free_response_schemas import exercise_data
from test_retry import ai_client, completed


def settings(**changes):
    return {
        "goal": "content",
        "language": "lt",
        "level": None,
        "min_words": None,
        "max_words": None,
        **changes,
    }


def candidate(topic=1, ref=None):
    ref = ref or {"document_id": 1, "page": 2}
    exercise = exercise_data()
    exercise["source_fragments"][0]["source"] = ref
    exercise["expected_points"][0]["sources"] = [ref]
    return {
        "topic_id": topic,
        "question": "Kas yra ąžuolas?",
        "answer": "Ąžuolas yra medis.",
        "mode": "quiz",
        "options": [],
        "correct_indices": [],
        "correct_index": None,
        "sources": [ref],
        "language": "lt",
        "question_type": "free_response",
        "exercise": exercise,
    }


def setup_generation(client, app):
    app.state.ai = FixtureAI()
    topic = make_topic(client)
    document = ready_document(client, app, topic)
    with app.state.db.session() as db:
        page = db.query(SourcePage).filter_by(document_id=document["id"]).one()
        page.text = "Ąžuolas yra medis. Jis auga miške."
        page.language = "lt"
        ref = {"document_id": document["id"], "page": page.number}
    return topic, ref


def body(topic, **changes):
    return {
        "topic_ids": [topic],
        "count": 1,
        "question_types": ["free_response"],
        "free_response_settings": settings(),
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"question_types": ["free_response", "choice"], "count": 2},
        {"topic_ids": [1, 2], "count": 2},
        {"mode": "flashcard"},
        {"free_response_settings": None},
        {"free_response_settings": settings(goal="language")},
        {"free_response_settings": settings(level="A1")},
        {"target_language": "en"},
    ],
)
def test_free_generation_requires_one_family_topic_and_explicit_coherent_settings(changes):
    with pytest.raises(ValueError):
        GenerateBody.model_validate(body(1, **changes))


def test_explicit_language_settings_have_no_implicit_cefr_word_minimum():
    parsed = GenerateBody.model_validate(
        body(1, free_response_settings=settings(goal="language", level="A1"))
    )
    assert parsed.free_response_settings.min_words is None
    assert parsed.free_response_settings.level == "A1"


def test_unknown_language_requires_explicit_confirmation_and_known_language_is_locked(client, app):
    topic, ref = setup_generation(client, app)
    assert (
        client.post(
            "/api/generate", json=body(topic, free_response_settings=settings(language="pl"))
        ).status_code
        == 422
    )
    with app.state.db.session() as db:
        db.query(SourcePage).filter_by(document_id=ref["document_id"]).one().language = None
    missing = settings()
    missing.pop("language")
    assert (
        client.post("/api/generate", json=body(topic, free_response_settings=missing)).status_code
        == 422
    )
    assert client.post("/api/generate", json=body(topic)).status_code == 200


def test_mixed_source_languages_and_no_sources_fail_before_job(client, app):
    topic, ref = setup_generation(client, app)
    with app.state.db.session() as db:
        db.add(
            SourcePage(
                document_id=ref["document_id"], number=2, text="English", language="en", warnings=[]
            )
        )
    assert client.post("/api/generate", json=body(topic)).status_code == 422
    empty = make_topic(client, "Empty")
    assert client.post("/api/generate", json=body(empty)).status_code == 422


def test_snapshot_freezes_exact_prepared_fragments_and_criteria():
    from app.quiz import build_free_snapshot

    card = candidate()
    fragments = copy.deepcopy(card["exercise"]["source_fragments"])
    card["sources"] = [{"document_id": 1, "page": 2, "text": "FULL PAGE SHOULD NOT SURVIVE"}]
    result = build_free_snapshot(card, fragments)
    card["exercise"]["rubric"][0]["weight"] = 60
    fragments[0]["text"] = "changed"
    assert result["snapshot_version"] == 3
    assert result["exercise"]["rubric"][0]["weight"] == 50
    assert result["exercise"]["source_fragments"][0]["text"] == "Ąžuolas yra medis."
    assert "FULL PAGE SHOULD NOT SURVIVE" not in json.dumps(result)
    with pytest.raises(ValueError):
        build_free_snapshot(candidate(), fragments)


def prepared_output(topic=1, ref=None):
    card = candidate(topic, ref)
    card["exercise"]["rubric"][0]["dimensions"] = ["accuracy", "coverage"]
    card["exercise"]["rubric"][1]["dimensions"] = ["explanation"]
    return {
        "cards": [card],
        "insufficient_reason": None,
        "unsupported_types": [],
        "source_language_matches": True,
    }


def provider(app, output, during_send=None):
    def handler(request):
        if during_send:
            during_send()
        payload = json.loads(request.content)
        assert_closed(payload["text"]["format"]["schema"])
        return httpx.Response(200, json=completed(output))

    ai, sdk = ai_client(app.state.settings.data_dir, handler)
    app.state.ai = ai
    return sdk


def generate_card(client, app):
    topic, ref = setup_generation(client, app)
    with provider(app, prepared_output(topic, ref)):
        response = client.post("/api/generate", json=body(topic, idempotency_key="prepare"))
        assert response.status_code == 200, response.text
        job = response.json()
        run_job(app.state.db, app.state.ai, job["id"])
    value = client.get(f"/api/jobs/{job['id']}").json()
    assert value["status"] == "succeeded", value
    card = client.get(f"/api/cards?job_id={job['id']}").json()[0]
    return topic, ref, job, card


def test_raw_generation_persists_private_evidence_and_replays_without_duplicates(client, app):
    topic, ref, job, card = generate_card(client, app)
    assert card["status"] == "draft" and card["exercise"]["source_fragments"][0]["source"] == ref
    assert "dimensions" not in card["exercise"]["rubric"][0]
    replay = client.post("/api/generate", json=body(topic, idempotency_key="prepare"))
    assert replay.json()["id"] == job["id"]
    assert client.post("/api/cards/save", json={"card_ids": [card["id"]]}).status_code == 200


@pytest.mark.parametrize(
    "change",
    [
        "foreign_ref",
        "fabricated_excerpt",
        "changed_settings",
        "changed_language",
        "bad_dimensions",
        "oversize",
    ],
)
def test_untrusted_preparation_never_persists_invalid_card(client, app, change):
    topic, ref = setup_generation(client, app)
    output = prepared_output(topic, ref)
    item = output["cards"][0]
    if change == "foreign_ref":
        item["exercise"]["source_fragments"][0]["source"] = {"document_id": 999, "page": 1}
        item["exercise"]["expected_points"][0]["sources"] = [{"document_id": 999, "page": 1}]
    if change == "fabricated_excerpt":
        item["exercise"]["source_fragments"][0]["text"] = "Fabricated fact"
    if change == "changed_settings":
        item["exercise"]["min_words"] = 10
    if change == "changed_language":
        item["language"] = "pl"
        item["exercise"]["language"] = "pl"
    if change == "bad_dimensions":
        item["exercise"]["rubric"][0]["dimensions"] = ["grammar"]
    if change == "oversize":
        item["exercise"]["source_fragments"][0]["text"] = "x" * 4001
    with provider(app, output):
        job = client.post("/api/generate", json=body(topic)).json()
        run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"
    assert client.get(f"/api/cards?job_id={job['id']}").json() == []


@pytest.mark.parametrize(
    "reason,matches",
    [("Prieštaringi šaltiniai", True), ("Per platus klausimas", True), ("Nesutampa kalba", False)],
)
def test_insufficient_preparation_records_reason_and_source_fingerprint(
    client, app, reason, matches
):
    topic, ref = setup_generation(client, app)
    output = {
        "cards": [],
        "insufficient_reason": reason,
        "unsupported_types": [],
        "source_language_matches": matches,
    }
    with provider(app, output):
        job = client.post("/api/generate", json=body(topic)).json()
        run_job(app.state.db, app.state.ai, job["id"])
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert result["status"] == "succeeded", result
    assert result["result"]["warnings"] == [reason]
    assert result["result"]["outcomes_by_topic"][0]["source_fingerprint"]
    assert result["result"]["card_ids"] == []


def test_preparation_source_change_during_provider_call_cannot_publish_stale_draft(client, app):
    topic, ref = setup_generation(client, app)

    def change_source():
        with app.state.db.session() as db:
            db.query(SourcePage).filter_by(document_id=ref["document_id"]).one().text = "Changed"

    with provider(app, prepared_output(topic, ref), change_source):
        job = client.post("/api/generate", json=body(topic)).json()
        run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"
    assert client.get(f"/api/cards?job_id={job['id']}").json() == []


def test_parent_criteria_edits_preserve_fragments_and_old_snapshot(client, app):
    from app.quiz import build_free_snapshot

    _, _, _, card = generate_card(client, app)
    frozen = build_free_snapshot(card, card["exercise"]["source_fragments"])
    edit = copy.deepcopy(card["exercise"])
    edit["rubric"][0]["weight"] = 60
    edit["rubric"][1]["weight"] = 40
    edit.pop("source_fragments")
    response = client.patch(
        f"/api/cards/{card['id']}",
        json={"version": card["version"], "question": card["question"], "exercise": edit},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["exercise"]["source_fragments"] == card["exercise"]["source_fragments"]
    assert frozen["exercise"]["rubric"][0]["weight"] == 50
    assert (
        build_free_snapshot(updated, updated["exercise"]["source_fragments"])["exercise"]["rubric"][
            0
        ]["weight"]
        == 60
    )
    assert (
        client.patch(
            f"/api/cards/{card['id']}", json={"version": card["version"], "question": "Stale"}
        ).status_code
        == 409
    )
    edit = copy.deepcopy(updated["exercise"])
    edit["source_fragments"][0]["text"] = "Fabrication"
    assert (
        client.patch(
            f"/api/cards/{card['id']}",
            json={"version": updated["version"], "question": card["question"], "exercise": edit},
        ).status_code
        == 422
    )


def test_free_regeneration_apply_replay_discard_and_settings_guards(client, app):
    topic, ref, _, card = generate_card(client, app)
    output = prepared_output(topic, ref)
    output["cards"][0]["question"] = "Paaiškink apie ąžuolą."
    regenerated = {
        "card": output["cards"][0],
        "insufficient_reason": None,
        "source_language_matches": True,
    }
    with provider(app, regenerated):
        job = client.post(
            f"/api/cards/{card['id']}/regenerate",
            json={"version": card["version"], "idempotency_key": "regen"},
        ).json()
        run_job(app.state.db, app.state.ai, job["id"])
    job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "succeeded", job
    candidate = job["result"]["candidate"]
    changed = copy.deepcopy(candidate)
    changed["exercise"]["max_words"] = 100
    route = f"/api/jobs/{job['id']}/apply-regeneration"
    assert client.post(route, json={"candidate": changed}).status_code == 409
    applied = client.post(route, json={"candidate": candidate})
    assert applied.status_code == 200, applied.text
    assert applied.json()["version"] == card["version"] + 1
    assert client.post(route, json={"candidate": candidate}).json() == applied.json()
    assert client.post(route, json={"candidate": changed}).status_code == 409
    current = applied.json()
    with provider(app, regenerated):
        second = client.post(
            f"/api/cards/{card['id']}/regenerate",
            json={"version": current["version"], "idempotency_key": "regen2"},
        ).json()
        run_job(app.state.db, app.state.ai, second["id"])
    assert client.post(f"/api/jobs/{second['id']}/discard-regeneration").status_code == 200
    assert (
        client.post(
            f"/api/jobs/{second['id']}/apply-regeneration", json={"candidate": candidate}
        ).status_code
        == 409
    )


def test_legacy_provider_schema_contains_only_old_exercise_family(tmp_path):
    schemas = []

    def handler(request):
        schemas.append(json.loads(request.content)["text"]["format"]["schema"])
        return httpx.Response(
            200,
            json=completed(
                {"cards": [], "insufficient_reason": "No material", "unsupported_types": []}
            ),
        )

    ai, sdk = ai_client(tmp_path, handler)
    with sdk:
        ai.generate(1, [], "quiz", 1)
    assert "free_response" not in json.dumps(schemas[0])


def test_snapshot_keeps_source_labels_with_only_selected_excerpts():
    from app.quiz import build_free_snapshot

    card = candidate()
    card["sources"] = [
        {
            "document_id": 1,
            "page": 2,
            "name": "Botanika",
            "page_id": 7,
            "text": "Ąžuolas yra medis. Unselected details. Jis auga.",
            "language": "lt",
        }
    ]
    card["exercise"]["source_fragments"].append(
        {"source": {"document_id": 1, "page": 2}, "text": "Jis auga."}
    )
    frozen = build_free_snapshot(card, card["exercise"]["source_fragments"])
    assert len(frozen["sources"]) == 1
    assert frozen["sources"][0]["name"] == "Botanika"
    assert frozen["sources"][0]["text"] == "Ąžuolas yra medis.\n\nJis auga."
    assert "Unselected details" not in json.dumps(frozen)


@pytest.mark.parametrize(
    "field,value",
    [
        ("question_type", "choice"),
        ("mode", "flashcard"),
        ("language", "en"),
        ("target_language", "en"),
    ],
)
def test_snapshot_rejects_incoherent_card_settings(field, value):
    from app.quiz import build_free_snapshot

    card = candidate()
    card[field] = value
    with pytest.raises(ValueError):
        build_free_snapshot(card, card["exercise"]["source_fragments"])


def test_stale_preparation_is_rejected_before_provider_send(client, app):
    topic, ref = setup_generation(client, app)
    job = client.post("/api/generate", json=body(topic)).json()
    with app.state.db.session() as db:
        db.query(SourcePage).filter_by(
            document_id=ref["document_id"]
        ).one().text = "Changed before worker"
    calls = []
    with provider(app, prepared_output(topic, ref), lambda: calls.append("send")):
        run_job(app.state.db, app.state.ai, job["id"])
    assert calls == []
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"


def test_free_generation_dedupe_context_excludes_unselected_old_evidence_and_images(tmp_path):
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json=completed(
                {
                    "cards": [],
                    "insufficient_reason": "Too little",
                    "unsupported_types": [],
                    "source_language_matches": True,
                }
            ),
        )

    ai, sdk = ai_client(tmp_path, handler)
    old = candidate()
    old["exercise"]["source_fragments"][0]["text"] = "PRIVATE UNSELECTED EVIDENCE"
    old["images"] = [{"url": "PRIVATE ILLUSTRATION"}]
    with sdk:
        ai.generate(
            1,
            [
                {
                    "document_id": 1,
                    "page": 2,
                    "text": "Selected",
                    "language": "lt",
                    "images": old["images"],
                }
            ],
            "quiz",
            1,
            existing=[old],
            question_types=["free_response"],
            free_response_settings=settings(),
        )
    sent = json.dumps(captured)
    assert "PRIVATE UNSELECTED EVIDENCE" not in sent
    assert "PRIVATE ILLUSTRATION" not in sent


@pytest.mark.parametrize(
    "goal,level,dimensions",
    [
        ("content", None, ["accuracy", "coverage", "explanation"]),
        ("language", "A1", ["task_completion", "grammar", "vocabulary", "coherence"]),
        ("language", "B2", ["task_completion", "grammar", "vocabulary", "coherence"]),
    ],
)
def test_one_criterion_can_cover_goal_dimensions_without_invented_word_minimum(
    client, app, goal, level, dimensions
):
    topic, ref = setup_generation(client, app)
    output = prepared_output(topic, ref)
    exercise = output["cards"][0]["exercise"]
    exercise.update(
        goal=goal,
        level=level,
        rubric=[
            {
                "id": "chosen-by-preparer",
                "label": "Paaiškinimas",
                "weight": 100,
                "dimensions": dimensions,
            }
        ],
    )
    with provider(app, output):
        job = client.post(
            "/api/generate",
            json=body(topic, free_response_settings=settings(goal=goal, level=level)),
        ).json()
        run_job(app.state.db, app.state.ai, job["id"])
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert result["status"] == "succeeded", result
    saved = client.get(f"/api/cards?job_id={job['id']}").json()[0]["exercise"]
    assert saved["level"] == level and saved["min_words"] is None
    assert saved["rubric"] == [{"id": "chosen-by-preparer", "label": "Paaiškinimas", "weight": 100}]


def test_old_generation_request_fingerprints_still_replay_after_settings_field_is_added(
    client, app
):
    from app.jobs import fingerprint
    from app.models import Job

    topic, _ = setup_generation(client, app)
    request_body = {"topic_ids": [topic], "count": 1, "idempotency_key": "old-request"}
    first = client.post("/api/generate", json=request_body).json()
    legacy_body = GenerateBody.model_validate(request_body).model_dump(
        exclude={"idempotency_key", "free_response_settings"}
    )
    with app.state.db.session() as db:
        job = db.get(Job, first["id"])
        job.payload = {
            **job.payload,
            "request_keys": [{"key": "old-request", "fingerprint": fingerprint(legacy_body)}],
            "scope": fingerprint(
                {
                    "body": legacy_body,
                    "sources": [
                        {"id": t["id"], "sources": t["sources"]} for t in job.payload["topics"]
                    ],
                }
            ),
        }
    replay = client.post("/api/generate", json=request_body)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first["id"]
    active = client.post("/api/generate", json={"topic_ids": [topic], "count": 1}).json()
    assert active["id"] == first["id"]

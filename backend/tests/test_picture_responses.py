import io

import pytest
from app.models import Card
from conftest import make_topic
from PIL import Image
from sqlalchemy import select


def picture():
    out = io.BytesIO()
    Image.new("RGB", (30, 20), "green").save(out, format="PNG")
    return out.getvalue()


def upload(client, topic, key="picture", language="pl", level="A1"):
    return client.post(
        f"/api/topics/{topic}/picture-drafts",
        data={
            "language": language,
            "level": level,
            "key": key,
        },
        files={"image": ("scene.png", picture(), "image/png")},
    )


@pytest.mark.parametrize(
    "language,question",
    [
        ("pl", "Opisz obrazek."),
        ("en", "Describe the picture."),
        ("ru", "Опиши картинку."),
        ("lt", "Aprašyk paveikslėlį."),
    ],
)
def test_image_only_upload_is_idempotent_draft(client, app, language, question):
    topic = make_topic(client)
    first = upload(client, topic, language=language)
    assert first.status_code == 200, first.text
    card = first.json()
    assert card["question"] == question
    assert card["sources"] == []
    assert card["exercise"]["preparation_state"] == "needs_criteria"
    assert card["images"]["question"]["image_role"] == "source"
    assert upload(client, topic, language=language).json()["id"] == card["id"]
    assert upload(client, topic, language=language, level="B2").status_code == 409
    assert client.post("/api/cards/save", json={"card_ids": [card["id"]]}).status_code == 409
    with app.state.db.session() as db:
        row = db.get(Card, card["id"])
        row.status = "deleted"
    assert upload(client, topic, language=language).status_code == 410
    with app.state.db.session() as db:
        assert len(list(db.scalars(select(Card)))) == 1


def criteria(source, language="pl"):
    return {
        "goal": "language",
        "language": language,
        "level": "A1",
        "min_words": None,
        "max_words": None,
        "model_answer": "Na obrazku jest zielone pole.",
        "rubric": [{"id": "task", "label": "Opis", "weight": 100}],
        "expected_points": [
            {"id": "green", "text": "Zielone pole", "essential": True, "sources": [source]}
        ],
        "source": source,
    }


def prepared(client, app, monkeypatch):
    from app.jobs import run_job
    from app.models import Job

    topic = make_topic(client)
    app.state.settings.__dict__.update(
        picture_description_enabled=True, openai_vision_enabled=True, openai_api_key="fixture"
    )
    card = upload(client, topic).json()
    body = {"version": 1, "language": "pl", "level": "A1", "idempotency_key": "prepare"}
    response = client.post(f"/api/cards/{card['id']}/prepare-picture", json=body)
    assert response.status_code == 200, response.text
    job_id = response.json()["id"]
    assert (
        client.post(
            f"/api/cards/{card['id']}/prepare-picture", json={**body, "idempotency_key": "alias"}
        ).json()["id"]
        == job_id
    )
    captured = []

    def parse(schema, messages, tokens, **kwargs):
        captured.append(messages)
        with app.state.db.session() as db:
            source = db.get(Job, job_id).payload["picture_source"]
        return schema.model_validate(criteria(source))

    monkeypatch.setattr(app.state.ai, "parse", parse)
    run_job(app.state.db, app.state.ai, job_id)
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded", job
    assert captured[0][1]["content"][1]["image_url"].startswith("data:image/webp;base64,")
    candidate = job["result"]["candidate"]
    response = client.post(f"/api/jobs/{job_id}/apply-regeneration", json={"candidate": candidate})
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert (
        client.post(f"/api/jobs/{job_id}/apply-regeneration", json={"candidate": candidate}).json()
        == response.json()
    )
    assert client.post("/api/cards/save", json={"card_ids": [card["id"]]}).status_code == 200
    return topic, response.json(), job_id


def test_complete_image_only_prepare_snapshot_replace_repeat(client, app, monkeypatch):
    from app.models import Job, JobImage, SessionCard
    from app.picture_responses import get_picture_evidence

    topic, card, job_id = prepared(client, app, monkeypatch)
    start = client.post(
        "/api/study",
        json={
            "topic_ids": [topic],
            "mode": "quiz",
            "question_types": ["picture_description"],
            "include_ai_evaluated": True,
        },
    )
    assert start.status_code == 200, start.text
    session = start.json()
    assert "model_answer" not in str(session)
    with app.state.db.session() as db:
        frozen = db.scalar(select(SessionCard).where(SessionCard.session_id == session["id"]))
        assert frozen.snapshot["snapshot_version"] == 4
        evidence = get_picture_evidence(db, frozen.id, 1)
        assert evidence.data
        assert not list(db.scalars(select(JobImage).where(JobImage.job_id == job_id)))
        with pytest.raises(ValueError):
            get_picture_evidence(db, frozen.id, 2)
    # Sending stale criteria alongside removal must still invalidate them.
    removed = client.patch(
        f"/api/cards/{card['id']}",
        json={
            "version": 2,
            "question": card["question"],
            "exercise": card["exercise"],
            "image_updates": {"question": {"asset_id": None}},
        },
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["status"] == "draft"
    assert removed.json()["exercise"]["preparation_state"] == "needs_criteria"
    with app.state.db.session() as db:
        assert get_picture_evidence(db, frozen.id, 1).sha256 == evidence.sha256
    pending = client.post(
        f"/api/study/{session['id']}/answer",
        json={"position": 0, "idempotency_key": "answer", "free_text": "Zielone pole."},
    )
    assert pending.status_code == 202, pending.text
    with app.state.db.session() as db:
        assert (
            db.scalar(select(JobImage).where(JobImage.job_id == pending.json()["job_id"])).role
            == "context"
        )
        assert db.get(Job, pending.json()["job_id"]).status == "queued"


def test_vision_model_requires_actual_bytes_and_validates_evidence(client, app, monkeypatch):
    import base64
    import hashlib

    from app.evaluation_ai import EvaluationAI
    from app.picture_responses import VerifiedImageBytes

    source = {
        "kind": "image",
        "asset_id": "a" * 32,
        "sha256": hashlib.sha256(b"actual bytes").hexdigest(),
    }
    snapshot = {
        "snapshot_version": 4,
        "question_type": "picture_description",
        "mode": "quiz",
        "language": "pl",
        "question": "Opisz obrazek.",
        "exercise": criteria(source),
    }
    ai = EvaluationAI(app.state.settings)
    calls = []

    def parse(schema, messages, tokens, before_request):
        calls.append(messages)
        before_request()
        return schema.model_validate(
            {
                "assessability": "assessable",
                "reason": None,
                "language_match": True,
                "summary": "Dobrze.",
                "suggestions": [],
                "corrections": [],
                "rubric_scores": [{"criterion_id": "task", "score": 4, "explanation": "Dobrze."}],
                "point_checks": [{"point_id": "green", "met": True, "evidence": [source]}],
            }
        )

    monkeypatch.setattr(ai, "parse", parse)
    evidence = VerifiedImageBytes(source["asset_id"], source["sha256"], b"actual bytes")
    with pytest.raises(ValueError):
        ai.evaluate(snapshot, "Zielone pole.", lambda: None, evidence=evidence)
    app.state.settings.openai_vision_enabled = True
    with pytest.raises(ValueError):
        ai.evaluate(snapshot, "Zielone pole.", lambda: None)
    with pytest.raises(ValueError):
        ai.evaluate(
            snapshot,
            "Zielone pole.",
            lambda: None,
            evidence=VerifiedImageBytes(source["asset_id"], source["sha256"], b"wrong bytes"),
        )
    ai.evaluate(snapshot, "Zielone pole.", lambda: None, evidence=evidence)
    assert len(calls) == 1
    assert (
        calls[0][1]["content"][1]["image_url"].split(",")[1]
        == base64.b64encode(evidence.data).decode()
    )


def test_deleted_source_and_changed_candidate_rejected_before_model(client, app, monkeypatch):
    from app.models import ImageAsset
    from app.question_images import asset_path

    topic = make_topic(client)
    app.state.settings.__dict__.update(
        picture_description_enabled=True, openai_vision_enabled=True, openai_api_key="fixture"
    )
    card = upload(client, topic).json()
    with app.state.db.session() as db:
        asset = db.get(ImageAsset, card["images"]["question"]["asset_id"])
        asset_path(app.state.db, asset).write_bytes(b"changed")
    response = client.post(
        f"/api/cards/{card['id']}/prepare-picture",
        json={"version": 1, "language": "pl", "level": "A1", "idempotency_key": "prepare"},
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "unavailable",
    [
        None,
        "picture_description_enabled",
        "openai_vision_enabled",
        "openai_api_key",
        "openai_model",
        "free_response_daily_request_limit",
        "budget_timezone",
    ],
)
def test_picture_evaluation_completion_repeat_and_context_cleanup(
    client, app, monkeypatch, unavailable
):
    import app.evaluations as evaluations
    from app.free_responses import FreeResponseEvaluation
    from app.jobs import run_job
    from app.models import JobImage, SessionCard

    topic, card, _ = prepared(client, app, monkeypatch)
    session = client.post(
        "/api/study",
        json={
            "topic_ids": [topic],
            "mode": "quiz",
            "question_types": ["picture_description"],
            "include_ai_evaluated": True,
        },
    ).json()

    class Evaluator:
        def __init__(self, settings):
            pass

        def evaluate(self, snapshot, answer, before_request, evidence):
            assert evidence.data and evidence.sha256 == snapshot["exercise"]["source"]["sha256"]
            before_request()
            return FreeResponseEvaluation.model_validate(
                {
                    "assessability": "assessable",
                    "reason": None,
                    "language_match": True,
                    "summary": "Dobrze.",
                    "suggestions": [],
                    "corrections": [],
                    "rubric_scores": [
                        {"criterion_id": "task", "score": 2, "explanation": "Dobrze."}
                    ],
                    "point_checks": [
                        {
                            "point_id": "green",
                            "met": True,
                            "evidence": [snapshot["exercise"]["source"]],
                        }
                    ],
                }
            )

    monkeypatch.setattr(evaluations, "EvaluationAI", Evaluator)
    pending = client.post(
        f"/api/study/{session['id']}/answer",
        json={"position": 0, "idempotency_key": "answer", "free_text": "Zielone pole."},
    ).json()
    run_job(app.state.db, app.state.ai, pending["job_id"])
    result = client.get(f"/api/study/{session['id']}").json()
    assert result["status"] == "completed", result
    assert result["review"][0]["score"] == 50
    with app.state.db.session() as db:
        assert not list(db.scalars(select(JobImage).where(JobImage.job_id == pending["job_id"])))
    if unavailable:
        from test_evaluation_history import assert_unavailable_repeat

        assert_unavailable_repeat(client, app, session["id"], unavailable)
        return
    repeat = client.post(f"/api/study/{session['id']}/repeat", json={})
    assert repeat.status_code == 200, repeat.text
    with app.state.db.session() as db:
        copied = db.scalar(select(SessionCard).where(SessionCard.session_id == repeat.json()["id"]))
        assert copied.snapshot["snapshot_version"] == 4
        assert copied.snapshot["exercise"] == card["exercise"]


def test_generic_generation_rejects_picture_before_job(client, app):
    from app.models import Job

    topic = make_topic(client)
    response = client.post(
        "/api/generate",
        json={
            "topic_ids": [topic],
            "mode": "quiz",
            "count": 1,
            "question_types": ["picture_description"],
            "practice_goal": "language",
        },
    )
    assert response.status_code == 422
    assert "picture-drafts" in response.text
    with app.state.db.session() as db:
        assert not list(db.scalars(select(Job)))


def test_duplicate_upload_concurrency_and_changed_source_apply_guard(client, app, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from app.models import ImageAsset

    topic = make_topic(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: upload(client, topic), range(2)))
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1
    with app.state.db.session() as db:
        assert len(list(db.scalars(select(ImageAsset)))) == 1


def test_source_swap_cannot_apply_old_candidate_and_discard_releases_context(
    client, app, monkeypatch
):
    from app.jobs import run_job
    from app.models import Job, JobImage

    topic, card, _ = prepared(client, app, monkeypatch)
    job = client.post(
        f"/api/cards/{card['id']}/prepare-picture",
        json={"version": 2, "language": "pl", "level": "A1", "idempotency_key": "second"},
    ).json()

    def parse(schema, messages, tokens, **kwargs):
        kwargs["before_request"]()
        with app.state.db.session() as db:
            source = db.get(Job, job["id"]).payload["picture_source"]
        return schema.model_validate(criteria(source))

    monkeypatch.setattr(app.state.ai, "parse", parse)
    run_job(app.state.db, app.state.ai, job["id"])
    result = client.get(f"/api/jobs/{job['id']}").json()
    candidate = client.post(
        f"/api/cards/{card['id']}/image-candidates",
        data={"slot": "question", "version": 2},
        files={"file": ("other.png", picture(), "image/png")},
    ).json()
    applied = client.post(
        f"/api/jobs/{job['id']}/apply-regeneration",
        json={
            "candidate": result["result"]["candidate"],
            "image_updates": {"question": {"asset_id": candidate["id"]}},
        },
    )
    assert applied.status_code == 409
    with app.state.db.session() as db:
        assert db.get(Card, card["id"]).version == 2
    queued = client.post(
        f"/api/cards/{card['id']}/prepare-picture",
        json={
            "version": 2,
            "language": "pl",
            "level": "A1",
            "idempotency_key": "third",
            "another_variant": True,
        },
    ).json()
    assert queued["id"] != job["id"]
    assert client.post(f"/api/jobs/{queued['id']}/discard-regeneration").status_code == 200
    with app.state.db.session() as db:
        assert not list(db.scalars(select(JobImage).where(JobImage.job_id == queued["id"])))


def test_last_reference_history_deletion_cleans_source_and_late_job(client, app, monkeypatch):
    from app.jobs import run_job
    from app.models import ImageAsset, JobImage
    from app.question_images import asset_path

    topic, card, _ = prepared(client, app, monkeypatch)
    session = client.post(
        "/api/study",
        json={
            "topic_ids": [topic],
            "mode": "quiz",
            "question_types": ["picture_description"],
            "include_ai_evaluated": True,
        },
    ).json()
    pending = client.post(
        f"/api/study/{session['id']}/answer",
        json={"position": 0, "idempotency_key": "late", "free_text": "Pole."},
    ).json()
    with app.state.db.session() as db:
        asset = db.get(ImageAsset, card["images"]["question"]["asset_id"])
        path = asset_path(app.state.db, asset)
    assert client.delete(f"/api/cards/{card['id']}").status_code == 200
    assert path.is_file()
    assert (
        client.post("/api/study/delete", json={"session_ids": [session["id"]]}).status_code == 200
    )
    assert not path.exists()
    run_job(app.state.db, app.state.ai, pending["job_id"])
    assert not path.exists()
    with app.state.db.session() as db:
        assert not list(db.scalars(select(JobImage).where(JobImage.asset_id == asset.id)))


def test_picture_regenerate_transport_replay_uses_same_preparation_job(client, app):
    topic = make_topic(client)
    app.state.settings.__dict__.update(
        picture_description_enabled=True, openai_vision_enabled=True, openai_api_key="fixture"
    )
    card = upload(client, topic).json()
    body = {"version": 1, "idempotency_key": "same-route"}
    first = client.post(f"/api/cards/{card['id']}/regenerate", json=body)
    second = client.post(f"/api/cards/{card['id']}/regenerate", json=body)
    assert first.status_code == second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]


def test_upload_key_binds_raw_bytes_but_not_filename(client, app):
    from PIL.PngImagePlugin import PngInfo

    topic = make_topic(client)
    first = upload(client, topic).json()
    data = {"language": "pl", "level": "A1", "key": "picture"}
    renamed = client.post(
        f"/api/topics/{topic}/picture-drafts",
        data=data,
        files={"image": ("renamed.png", picture(), "image/png")},
    )
    assert renamed.status_code == 200 and renamed.json()["id"] == first["id"]
    metadata = PngInfo()
    metadata.add_text("description", "same pixels, changed original bytes")
    changed = io.BytesIO()
    Image.open(io.BytesIO(picture())).save(changed, format="PNG", pnginfo=metadata)
    from app.question_images import normalize_image

    assert normalize_image(picture())[0] == normalize_image(changed.getvalue())[0]
    response = client.post(
        f"/api/topics/{topic}/picture-drafts",
        data=data,
        files={"image": ("scene.png", changed.getvalue(), "image/png")},
    )
    assert response.status_code == 409, response.text


def test_actual_sdk_picture_preparation_and_evaluation_schemas(tmp_path):
    import hashlib
    import json

    import httpx
    from app.evaluation_ai import EvaluationAI
    from app.picture_responses import VerifiedImageBytes, prepare_with_ai, setup_of
    from test_evaluation_ai import assert_closed
    from test_retry import ai_client, completed

    source = {
        "kind": "image",
        "asset_id": "a" * 32,
        "sha256": hashlib.sha256(picture()).hexdigest(),
    }
    exercise = criteria(source)
    feedback = {
        "assessability": "assessable",
        "reason": None,
        "language_match": True,
        "summary": "Dobrze.",
        "suggestions": [],
        "corrections": [],
        "rubric_scores": [{"criterion_id": "task", "score": 4, "explanation": "Dobrze."}],
        "point_checks": [{"point_id": "green", "met": True, "evidence": [source]}],
    }
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert_closed(payload["text"]["format"]["schema"])
        assert payload["input"][1]["content"][1]["image_url"].startswith("data:image/webp;base64,")
        return httpx.Response(200, json=completed(exercise if len(requests) == 1 else feedback))

    ai, sdk = ai_client(tmp_path, handler)
    ai.settings.openai_api_key = "test-only"
    ai.settings.picture_description_enabled = True
    ai.settings.openai_vision_enabled = True
    evidence = VerifiedImageBytes(source["asset_id"], source["sha256"], picture())
    snap = {
        "topic_id": 1,
        "snapshot_version": 4,
        "question_type": "picture_description",
        "mode": "quiz",
        "question": "Opisz obrazek.",
        "language": "pl",
        "exercise": exercise,
    }
    with sdk:
        prepared = prepare_with_ai(ai, snap, setup_of(exercise).model_dump(), evidence)
        assert prepared.exercise.model_dump() == exercise
        result = EvaluationAI(ai.settings, client=sdk).evaluate(
            snap, "Zielone pole.", lambda: None, evidence
        )
        assert result.point_checks[0].evidence[0].model_dump() == source
    assert len(requests) == 2
    wire = requests[1]["text"]["format"]["schema"]
    assert '"anyOf"' in json.dumps(wire)

import httpx
from app.jobs import run_job
from openai import OpenAI
from sqlalchemy import select
from test_answer_audio import setup_audio, upload


def install_transcriber(monkeypatch, app, handler=None):
    import app.answer_audio as module
    from app.transcription import Transcriber

    sdk = OpenAI(
        api_key="test",
        max_retries=0,
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                handler
                or (
                    lambda r: httpx.Response(
                        200, json={"text": "Tai yra medis", "languages": [{"code": "lt"}]}
                    )
                )
            )
        ),
    )
    monkeypatch.setattr(module, "Transcriber", lambda settings: Transcriber(settings, client=sdk))
    return sdk


def test_transcript_durable_cleanup_and_one_send(client, app, monkeypatch):
    session = setup_audio(client, app)
    result = upload(client, session).json()
    with install_transcriber(monkeypatch, app):
        run_job(app.state.db, None, result["job_id"])
        run_job(app.state.db, None, result["job_id"])
    current = client.get(f"/api/audio-answers/{result['audio_answer_id']}").json()
    assert current["status"] == "ready" and current["original_transcript"] == "Tai yra medis"
    assert current["language_mismatch"] is False
    assert (
        client.get(f"/api/audio-answers/{result['audio_answer_id']}/recording").status_code == 404
    )
    assert not list((app.state.settings.data_dir / "answer-audio").iterdir())
    from app.models import TranscriptionRequest

    with app.state.db.session() as db:
        rows = list(db.scalars(select(TranscriptionRequest)))
        assert len(rows) == 1 and rows[0].seconds == 1 and rows[0].status == "succeeded"
    assert client.get(f"/api/study/{session}").json()["answered"] == 0


def test_timeout_unknown_manual_retry_debits_again(client, app, monkeypatch):
    session = setup_audio(client, app)
    result = upload(client, session).json()
    sends = []

    def timeout(request):
        sends.append(request)
        raise httpx.ReadTimeout("private", request=request)

    with install_transcriber(monkeypatch, app, timeout):
        run_job(app.state.db, None, result["job_id"])
    assert len(sends) == 1
    url = f"/api/audio-answers/{result['audio_answer_id']}"
    assert client.get(url).json()["status"] == "unknown"
    assert client.post(f"/api/jobs/{result['job_id']}/retry").status_code == 409
    assert (
        client.post(
            url + "/retry", json={"idempotency_key": "again", "acknowledge_extra_cost": False}
        ).status_code
        == 422
    )
    assert (
        client.post(
            url + "/retry", json={"idempotency_key": "again", "acknowledge_extra_cost": True}
        ).status_code
        == 202
    )
    with install_transcriber(monkeypatch, app):
        run_job(app.state.db, None, result["job_id"])
    from app.models import TranscriptionRequest

    with app.state.db.session() as db:
        assert len(list(db.scalars(select(TranscriptionRequest)))) == 2


def test_wire_languages_regional_and_override(client, app, monkeypatch):
    from app.models import SessionCard

    for model, expected in [
        ("gpt-transcribe", b'name="languages[]"'),
        ("gpt-4o-mini-transcribe", b'name="language"'),
    ]:
        session = setup_audio(client, app)
        app.state.settings.openai_transcription_model = model
        with app.state.db.session() as db:
            card = db.scalar(select(SessionCard).where(SessionCard.session_id == session))
            card.snapshot = {
                **card.snapshot,
                "exercise": {**card.snapshot["exercise"], "language": "en-GB"},
            }
        result = upload(client, session, key=model).json()
        wires = []

        def response(request, wires=wires):
            wires.append(request.read())
            assert request.url.path == "/v1/audio/transcriptions"
            return httpx.Response(
                200, json={"text": "An English answer", "languages": [{"code": "en"}]}
            )

        with install_transcriber(monkeypatch, app, response):
            run_job(app.state.db, None, result["job_id"])
        assert len(wires) == 1 and expected in wires[0]
        assert b"en-GB" not in wires[0] and b"\r\n\r\nen\r\n" in wires[0]
        if model == "gpt-transcribe":
            assert b'name="language"' not in wires[0]
        current = client.get(f"/api/audio-answers/{result['audio_answer_id']}").json()
        assert current["expected_language"] == "en-GB" and current["language_mismatch"] is False


def test_edited_transcript_authoritative_grading(client, app, monkeypatch):
    from app.models import Attempt
    from test_evaluations import install_evaluator

    session = setup_audio(client, app)
    audio = upload(client, session).json()
    with install_transcriber(monkeypatch, app):
        run_job(app.state.db, None, audio["job_id"])
    body = {
        "position": 0,
        "idempotency_key": "grade",
        "free_text": "Tai yra didelis medis",
        "audio_answer_id": audio["audio_answer_id"],
    }
    assert (
        client.post(f"/api/study/{session}/answer", json={**body, "was_edited": False}).status_code
        == 422
    )
    result = client.post(f"/api/study/{session}/answer", json=body)
    assert result.status_code == 202, result.text
    assert client.delete(f"/api/audio-answers/{audio['audio_answer_id']}").status_code == 409
    with install_evaluator(monkeypatch, app):
        run_job(app.state.db, None, result.json()["job_id"])
    with app.state.db.session() as db:
        attempt = db.scalar(select(Attempt))
        assert attempt.value["free_text"] == "Tai yra didelis medis"
        grade = attempt.value["_grading"]
        assert grade["input_method"] == "voice" and grade["word_count"] == 4
        assert grade["voice"] == {
            "original_transcript": "Tai yra medis",
            "original_word_count": 3,
            "was_edited": True,
        }


def test_family_quota_concurrent_round_up_no_refund(client, app, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from app.models import TranscriptionRequest

    app.state.settings.transcription_daily_seconds_limit = 1
    first = upload(client, setup_audio(client, app), key="one").json()
    second = upload(client, setup_audio(client, app), key="two").json()
    with install_transcriber(monkeypatch, app):
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda r: run_job(app.state.db, None, r["job_id"]), [first, second]))
    values = [
        client.get(f"/api/audio-answers/{r['audio_answer_id']}").json() for r in [first, second]
    ]
    assert sorted(v["status"] for v in values) == ["failed", "ready"]
    assert next(v for v in values if v["status"] == "failed")["error_code"] == "quota_exceeded"
    for r in [first, second]:
        assert client.delete(f"/api/audio-answers/{r['audio_answer_id']}").status_code == 200
    with app.state.db.session() as db:
        rows = list(db.scalars(select(TranscriptionRequest)))
        assert len(rows) == 1 and rows[0].seconds == 1


def test_no_runtime_settings_before_send(client, app, monkeypatch):
    from app.models import TranscriptionRequest

    for key, value in [
        ("transcription_enabled", False),
        ("openai_api_key", ""),
        ("openai_transcription_model", ""),
    ]:
        session = setup_audio(client, app)
        app.state.settings.openai_transcription_model = "gpt-transcribe"
        result = upload(client, session, key=key).json()
        setattr(app.state.settings, key, value)
        with install_transcriber(
            monkeypatch, app, lambda r: (_ for _ in ()).throw(AssertionError("external send"))
        ):
            run_job(app.state.db, None, result["job_id"])
        assert (
            client.get(f"/api/audio-answers/{result['audio_answer_id']}").json()["error_code"]
            == "runtime_unavailable"
        )
    with app.state.db.session() as db:
        assert list(db.scalars(select(TranscriptionRequest))) == []


def test_quota_dst_calendar_boundary(client, app, monkeypatch):
    from datetime import UTC, datetime

    import app.answer_audio as module
    from app.models import TranscriptionRequest

    app.state.settings.transcription_daily_seconds_limit = 1
    first = upload(client, setup_audio(client, app), key="dst-one").json()
    monkeypatch.setattr(module, "utc_now", lambda: datetime(2026, 10, 25, 20, 30, tzinfo=UTC))
    with install_transcriber(monkeypatch, app):
        run_job(app.state.db, None, first["job_id"])
    # Vilnius changed clocks today: 21:30 UTC is still October25, 22:00 starts October26.
    second = upload(client, setup_audio(client, app), key="dst-two").json()
    monkeypatch.setattr(module, "utc_now", lambda: datetime(2026, 10, 25, 21, 30, tzinfo=UTC))
    with install_transcriber(monkeypatch, app):
        run_job(app.state.db, None, second["job_id"])
    assert (
        client.get(f"/api/audio-answers/{second['audio_answer_id']}").json()["error_code"]
        == "quota_exceeded"
    )
    assert (
        client.post(
            f"/api/audio-answers/{second['audio_answer_id']}/retry",
            json={"idempotency_key": "dst-next", "acknowledge_extra_cost": True},
        ).status_code
        == 202
    )
    monkeypatch.setattr(module, "utc_now", lambda: datetime(2026, 10, 25, 22, 0, tzinfo=UTC))
    with install_transcriber(monkeypatch, app):
        run_job(app.state.db, None, second["job_id"])
    with app.state.db.session() as db:
        assert len(list(db.scalars(select(TranscriptionRequest)))) == 2


def test_missing_raw_retry_requires_recording_again(client, app, monkeypatch):
    from app.models import AudioAnswer

    session = setup_audio(client, app)
    audio = upload(client, session).json()

    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)

    with install_transcriber(monkeypatch, app, timeout):
        run_job(app.state.db, None, audio["job_id"])
    with app.state.db.session() as db:
        row = db.get(AudioAnswer, audio["audio_answer_id"])
        (app.state.settings.data_dir / "answer-audio" / row.raw_path).unlink()
    response = client.post(
        f"/api/audio-answers/{audio['audio_answer_id']}/retry",
        json={"idempotency_key": "missing", "acknowledge_extra_cost": True},
    )
    assert response.status_code == 409 and response.json()["detail"]["code"] == "record_again"


def test_quota_is_shared_between_family_users(client, app, monkeypatch):
    from fastapi.testclient import TestClient

    first = upload(client, setup_audio(client, app)).json()
    app.state.settings.transcription_daily_seconds_limit = 1
    with install_transcriber(monkeypatch, app):
        run_job(app.state.db, None, first["job_id"])
    with TestClient(app) as parent:
        login = parent.post(
            "/api/auth/login",
            json={"username": "parent", "password": "parent-password"},
            headers={"Origin": "http://testserver"},
        )
        parent.headers.update(
            {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf_token"]}
        )
        second = upload(parent, setup_audio(parent, app)).json()
        with install_transcriber(monkeypatch, app):
            run_job(app.state.db, None, second["job_id"])
        assert (
            parent.get(f"/api/audio-answers/{second['audio_answer_id']}").json()["error_code"]
            == "quota_exceeded"
        )

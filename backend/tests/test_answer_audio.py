import hashlib
import io
import subprocess
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor

import pytest
from app.jobs import run_job
from sqlalchemy import select
from test_evaluations import setup_free, start_free


def wav_bytes(seconds=0.2):
    data = io.BytesIO()
    with wave.open(data, "wb") as out:
        out.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        out.writeframes(b"\0\0" * round(16000 * seconds))
    return data.getvalue()


def setup_audio(client, app):
    session = start_free(client, setup_free(client, app))
    app.state.settings.__dict__.update(transcription_enabled=True)
    return session


def upload(client, session, data=None, key="audio"):
    return client.post(
        f"/api/study/{session}/audio",
        data={"position": "0", "idempotency_key": key},
        files={"file": ("spoof.mp4", data if data is not None else wav_bytes(), "video/fake")},
    )


def test_upload_binds_original_bytes_and_recovers_lost_ack(client, app):
    session = setup_audio(client, app)
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: upload(client, session), range(2)))
    assert [r.status_code for r in responses] == [202, 202]
    assert responses[0].json() == responses[1].json()
    result = responses[0].json()
    assert upload(client, session, wav_bytes(0.3)).status_code == 409
    lookup = client.get(f"/api/study/{session}/audio?position=0").json()
    assert lookup["audio_answer"]["audio_answer_id"] == result["audio_answer_id"]
    assert lookup["available"] is True
    assert client.get(f"/api/study/{session}").json()["answered"] == 0
    recording = client.get(f"/api/audio-answers/{result['audio_answer_id']}/recording")
    assert recording.status_code == 200
    assert recording.headers["cache-control"] == "no-store"
    assert recording.headers["x-content-type-options"] == "nosniff"
    from app.models import AudioAnswer

    with app.state.db.session() as db:
        row = db.scalar(select(AudioAnswer))
        assert row.sha256 == hashlib.sha256(wav_bytes()).hexdigest()
        assert row.duration == 0.2
        path = app.state.settings.data_dir / "answer-audio" / row.raw_path
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
    assert "raw_path" not in result and str(path) not in str(lookup)


def test_disabled_invalid_and_csrf_never_create_job(client, app):
    session = setup_audio(client, app)
    app.state.settings.transcription_enabled = False
    assert upload(client, session).status_code == 409
    assert (
        client.get(f"/api/study/{session}/audio?position=0").json()["reason"]
        == "runtime_unavailable"
    )
    app.state.settings.transcription_enabled = True
    for data in [
        b"not audio",
        b"#EXTM3U\n/etc/passwd\n",
        b"ffconcat version 1.0\nfile /etc/passwd\n",
        b"x" * (15 * 1024 * 1024 + 1),
    ]:
        assert upload(client, session, data).status_code == 422
    client.headers.pop("X-CSRF-Token")
    assert upload(client, session).status_code == 403
    assert not list((app.state.settings.data_dir / "answer-audio").glob("*"))


@pytest.mark.parametrize(
    "extension,codec",
    [("wav", "pcm_s16le"), ("mp4", "aac"), ("webm", "libopus"), ("ogg", "libopus")],
)
def test_real_containers_normalize(tmp_path, extension, codec):
    from app.answer_audio import validate_audio

    source = tmp_path / f"{uuid.uuid4().hex}.{extension}"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.2",
            "-c:a",
            codec,
            str(source),
        ],
        check=True,
    )
    result = validate_audio(source)
    assert 0.19 <= result.duration <= 0.3
    with wave.open(str(result.normalized_path)) as stream:
        assert stream.getnchannels() == 1 and stream.getframerate() == 16000


def test_real_overlong_video_symlink_rejected(tmp_path):
    from app.answer_audio import validate_audio

    source = tmp_path / f"{uuid.uuid4().hex}.wav"
    source.write_bytes(wav_bytes(180.01))
    with pytest.raises(ValueError):
        validate_audio(source)
    video = tmp_path / f"{uuid.uuid4().hex}.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=size=16x16:duration=0.1",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=0.1",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            str(video),
        ],
        check=True,
    )
    with pytest.raises(ValueError):
        validate_audio(video)
    link = tmp_path / f"{uuid.uuid4().hex}.part"
    link.symlink_to(source)
    with pytest.raises(ValueError):
        validate_audio(link)
    assert not list(tmp_path.glob("*.normalized.wav"))


def test_foreign_private_routes_and_wrong_card(client, app, monkeypatch):
    from fastapi.testclient import TestClient
    from test_transcription import install_transcriber

    session = setup_audio(client, app)
    result = upload(client, session).json()
    with TestClient(app) as parent:
        login = parent.post(
            "/api/auth/login",
            json={"username": "parent", "password": "parent-password"},
            headers={"Origin": "http://testserver"},
        )
        parent.headers.update(
            {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf_token"]}
        )
        root = f"/api/audio-answers/{result['audio_answer_id']}"
        for path in [root, root + "/recording", f"/api/study/{session}/audio?position=0"]:
            assert parent.get(path).status_code == 404
        assert parent.delete(root).status_code == 404
        assert (
            parent.post(
                root + "/retry", json={"idempotency_key": "foreign", "acknowledge_extra_cost": True}
            ).status_code
            == 404
        )
        assert upload(parent, session).status_code == 404
    with install_transcriber(monkeypatch, app):
        run_job(app.state.db, None, result["job_id"])
    second = setup_audio(client, app)
    assert (
        client.post(
            f"/api/study/{second}/answer",
            json={
                "position": 0,
                "idempotency_key": "wrong",
                "free_text": "Tai yra medis",
                "audio_answer_id": result["audio_answer_id"],
            },
        ).status_code
        == 409
    )


def test_unknown_metadata_uses_actual_samples_and_rejects_nonfinite(tmp_path, monkeypatch):
    import json

    import app.answer_audio as module
    from app.answer_audio import validate_audio

    source = tmp_path / f"{uuid.uuid4().hex}.wav"
    source.write_bytes(wav_bytes(0.2))
    real_run = subprocess.run
    observed = []

    def run(argv, **kwargs):
        observed.append((argv, kwargs))
        result = real_run(argv, **kwargs)
        if argv[0] == "ffprobe":
            meta = json.loads(result.stdout)
            meta["format"].pop("duration", None)
            result.stdout = json.dumps(meta).encode()
        return result

    monkeypatch.setattr(module.subprocess, "run", run)
    result = validate_audio(source)
    assert result.duration == 0.2
    result.normalized_path.unlink()
    assert [x[1]["timeout"] for x in observed] == [10, 30]
    assert all(x[1]["shell"] is False and x[1]["stdin"] == subprocess.DEVNULL for x in observed)
    assert all("file,pipe" in x[0] and "-format_whitelist" in x[0] for x in observed)
    for duration in ["inf", "nan"]:

        def invalid(argv, duration=duration, **kwargs):
            result = real_run(argv, **kwargs)
            if argv[0] == "ffprobe":
                meta = json.loads(result.stdout)
                meta["format"]["duration"] = duration
                result.stdout = json.dumps(meta).encode()
            return result

        monkeypatch.setattr(module.subprocess, "run", invalid)
        with pytest.raises(ValueError):
            validate_audio(source)
    source.write_bytes(wav_bytes(180.01))
    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(ValueError):
        validate_audio(source)
    assert not list(tmp_path.glob("*.normalized.wav"))


def test_external_mp4_reference_and_playlist_never_reach_decoder(tmp_path, monkeypatch):
    import app.answer_audio as module

    def atom(kind, body):
        return (len(body) + 8).to_bytes(4, "big") + kind + body

    external = atom(b"ftyp", b"isom\0\0\0\0") + atom(
        b"moov",
        atom(
            b"dref",
            b"\0" * 4 + (1).to_bytes(4, "big") + atom(b"url ", b"\0" * 4 + b"/etc/passwd\0"),
        ),
    )
    monkeypatch.setattr(
        module.subprocess, "run", lambda *a, **k: pytest.fail("Disguised container reached decoder")
    )
    for value in [external, b"#EXTM3U\n/etc/passwd\n", b"ffconcat version 1.0\nfile /etc/passwd\n"]:
        source = tmp_path / f"{uuid.uuid4().hex}.part"
        source.write_bytes(value)
        with pytest.raises(ValueError):
            module.validate_audio(source)


def test_client_duration_language_and_unready_id_cannot_override_assignment(client, app):
    session = setup_audio(client, app)
    result = client.post(
        f"/api/study/{session}/audio",
        data={"position": 0, "idempotency_key": "bound", "duration": 0, "language": "ru"},
        files={"file": ("anything", wav_bytes(1.2), "text/html")},
    )
    assert result.status_code == 202
    audio = result.json()
    assert audio["duration"] == 1.2 and audio["expected_language"] == "lt"
    body = {
        "position": 0,
        "idempotency_key": "grade",
        "free_text": "Tai yra medis",
        "audio_answer_id": audio["audio_answer_id"],
    }
    assert client.post(f"/api/study/{session}/answer", json=body).status_code == 409
    from app.models import SessionCard

    with app.state.db.session() as db:
        card = db.scalar(select(SessionCard).where(SessionCard.session_id == session))
        card.snapshot = {
            **card.snapshot,
            "question_type": "written",
            "exercise": {"accepted_answers": ["medis"], "case_sensitive": False},
        }
    assert (
        client.post(
            f"/api/study/{session}/answer",
            json={
                "position": 0,
                "idempotency_key": "classic",
                "text": "medis",
                "audio_answer_id": audio["audio_answer_id"],
            },
        ).status_code
        == 422
    )


def test_decoder_timeout_removes_partial_normalized_file(tmp_path, monkeypatch):
    import app.answer_audio as module

    source = tmp_path / f"{uuid.uuid4().hex}.wav"
    source.write_bytes(wav_bytes())
    real_run = subprocess.run

    def timeout(argv, **kwargs):
        if argv[0] == "ffmpeg":
            kwargs["stdout"].write(b"partial")
            raise subprocess.TimeoutExpired(argv, 30)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", timeout)
    with pytest.raises(ValueError):
        module.validate_audio(source)
    assert not list(tmp_path.glob("*.normalized.wav"))


def test_unknown_metadata_marker_still_uses_actual_samples(tmp_path, monkeypatch):
    import json

    import app.answer_audio as module

    source = tmp_path / f"{uuid.uuid4().hex}.wav"
    source.write_bytes(wav_bytes())
    real_run = subprocess.run

    def unknown(argv, **kwargs):
        result = real_run(argv, **kwargs)
        if argv[0] == "ffprobe":
            metadata = json.loads(result.stdout)
            metadata["format"]["duration"] = "N/A"
            result.stdout = json.dumps(metadata).encode()
        return result

    monkeypatch.setattr(module.subprocess, "run", unknown)
    assert module.validate_audio(source).duration == 0.2

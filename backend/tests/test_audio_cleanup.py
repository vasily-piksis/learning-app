from datetime import timedelta

from app.jobs import run_job
from sqlalchemy import select
from test_answer_audio import setup_audio, upload
from test_transcription import install_transcriber


def test_discard_and_late_completion_never_restore(client, app, monkeypatch):
    import httpx

    session = setup_audio(client, app)
    first = upload(client, session).json()
    url = f"/api/audio-answers/{first['audio_answer_id']}"

    def response(request):
        assert client.delete(url).status_code == 200
        return httpx.Response(200, json={"text": "private late text", "languages": []})

    with install_transcriber(monkeypatch, app, response):
        run_job(app.state.db, None, first["job_id"])
    assert client.get(url).json()["status"] == "discarded"
    assert client.get(url).json()["original_transcript"] is None
    second = upload(client, session, key="replacement").json()
    assert second["audio_answer_id"] != first["audio_answer_id"]


def test_recovery_and_ttl_no_resend(client, app):
    from app.answer_audio import cleanup_answer_audio, recover_answer_audio
    from app.models import AudioAnswer, Job, now

    session = setup_audio(client, app)
    result = upload(client, session).json()
    with app.state.db.session() as db:
        audio = db.scalar(select(AudioAnswer))
        audio.status = "running"
        audio.expires_at = now() - timedelta(seconds=1)
        db.get(Job, result["job_id"]).status = "running"
        path = app.state.settings.data_dir / "answer-audio" / audio.raw_path
    cleanup_answer_audio(app.state.db)
    assert path.exists()
    recover_answer_audio(app.state.db)
    assert not path.exists()
    assert (
        client.get(f"/api/audio-answers/{result['audio_answer_id']}").json()["status"] == "unknown"
    )


def test_unlink_failure_retries_without_provider_and_retains_transcript(client, app, monkeypatch):
    from pathlib import Path

    from app.answer_audio import cleanup_answer_audio

    session = setup_audio(client, app)
    audio = upload(client, session).json()
    original = Path.unlink

    def fail(path, *args, **kwargs):
        if path.name.endswith(".normalized.wav"):
            raise PermissionError("test")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail)
        with install_transcriber(patch, app):
            run_job(app.state.db, None, audio["job_id"])
    assert (
        client.get(f"/api/audio-answers/{audio['audio_answer_id']}").json()["original_transcript"]
        == "Tai yra medis"
    )
    assert list((app.state.settings.data_dir / "answer-audio").iterdir())
    cleanup_answer_audio(app.state.db)
    assert not list((app.state.settings.data_dir / "answer-audio").iterdir())


def test_history_delete_during_send_scrubs_and_preserves_debit(client, app, monkeypatch):
    import httpx
    from app.models import AudioAnswer, Job, TranscriptionRequest

    session = setup_audio(client, app)
    audio = upload(client, session).json()

    def response(request):
        assert client.post("/api/study/delete", json={"session_ids": [session]}).status_code == 200
        return httpx.Response(200, json={"text": "late private", "languages": []})

    with install_transcriber(monkeypatch, app, response):
        run_job(app.state.db, None, audio["job_id"])
    assert client.get(f"/api/audio-answers/{audio['audio_answer_id']}").status_code == 404
    with app.state.db.session() as db:
        assert list(db.scalars(select(AudioAnswer))) == []
        assert len(list(db.scalars(select(TranscriptionRequest)))) == 1
        job = db.get(Job, audio["job_id"])
        assert job.payload == {} and job.result is None and job.status == "deleted"
    assert not list((app.state.settings.data_dir / "answer-audio").iterdir())


def test_ram_only_transcript_commit_failure_unknown(client, app, monkeypatch):
    import app.answer_audio as module

    session = setup_audio(client, app)
    audio = upload(client, session).json()
    monkeypatch.setattr(
        module, "persist_transcript", lambda *args: (_ for _ in ()).throw(OSError("storage failed"))
    )
    with install_transcriber(monkeypatch, app):
        run_job(app.state.db, None, audio["job_id"])
    result = client.get(f"/api/audio-answers/{audio['audio_answer_id']}").json()
    assert result["status"] == "unknown" and result["original_transcript"] is None
    assert result["recording_available"] is True


def test_retention_removes_only_old_unreferenced_and_old_ledger(client, app, monkeypatch):
    import os
    import uuid

    from app.answer_audio import cleanup_answer_audio
    from app.models import TranscriptionRequest, now

    session = setup_audio(client, app)
    audio = upload(client, session).json()
    with install_transcriber(monkeypatch, app):
        run_job(app.state.db, None, audio["job_id"])
    with app.state.db.session() as db:
        db.scalar(select(TranscriptionRequest)).reserved_at = now() - timedelta(days=31)
    directory = app.state.settings.data_dir / "answer-audio"
    old = directory / f"{uuid.uuid4().hex}.part"
    old.write_bytes(b"old")
    fresh = directory / f"{uuid.uuid4().hex}.part"
    fresh.write_bytes(b"active")
    os.utime(old, (0, 0))
    cleanup_answer_audio(app.state.db)
    assert not old.exists() and fresh.exists()
    with app.state.db.session() as db:
        assert list(db.scalars(select(TranscriptionRequest))) == []


def test_upload_deleted_during_validation_cannot_restore_session(client, app, monkeypatch):
    import app.answer_audio as module
    from app.models import AudioAnswer

    session = setup_audio(client, app)
    validate = module.validate_audio

    def during(path):
        result = validate(path)
        assert client.post("/api/study/delete", json={"session_ids": [session]}).status_code == 200
        return result

    monkeypatch.setattr(module, "validate_audio", during)
    assert upload(client, session).status_code == 404
    with app.state.db.session() as db:
        assert list(db.scalars(select(AudioAnswer))) == []
    assert not list((app.state.settings.data_dir / "answer-audio").iterdir())


def test_recovered_old_worker_cannot_replace_new_revision(client, app, monkeypatch):
    import httpx
    from app.answer_audio import recover_answer_audio

    session = setup_audio(client, app)
    audio = upload(client, session).json()

    def late(request):
        recover_answer_audio(app.state.db)
        result = client.post(
            f"/api/audio-answers/{audio['audio_answer_id']}/retry",
            json={"idempotency_key": "new-revision", "acknowledge_extra_cost": True},
        )
        assert result.status_code == 202
        return httpx.Response(200, json={"text": "old stale text", "languages": []})

    with install_transcriber(monkeypatch, app, late):
        run_job(app.state.db, None, audio["job_id"])
    result = client.get(f"/api/audio-answers/{audio['audio_answer_id']}").json()
    assert result["status"] == "queued" and result["original_transcript"] is None
    with install_transcriber(monkeypatch, app):
        run_job(app.state.db, None, audio["job_id"])
    assert (
        client.get(f"/api/audio-answers/{audio['audio_answer_id']}").json()["original_transcript"]
        == "Tai yra medis"
    )


def test_migration_0010_copy_preserves_all_old_rows_and_files(tmp_path):
    import hashlib
    import shutil
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from app.models import (
        Attempt,
        Evaluation,
        EvaluationRequest,
        ImageAsset,
        Job,
        SessionCard,
        SessionImage,
        StudySession,
        Subject,
        Topic,
        User,
        now,
    )
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.orm import Session

    original = tmp_path / "before.sqlite3"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    engine = create_engine(f"sqlite:///{original}")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0010")
    with Session(engine) as db:
        db.add(User(id=1, username="fixture", display_name="Private fixture", password_hash="fake"))
        db.flush()
        db.add(Subject(id=1, name="Subject"))
        db.flush()
        db.add(Topic(id=1, subject_id=1, name="Topic"))
        db.flush()
        db.add(
            StudySession(
                id=1, user_id=1, topic_ids=[1], mode="quiz", status="completed", position=1
            )
        )
        db.flush()
        db.add(
            SessionCard(
                id=1,
                session_id=1,
                position=0,
                snapshot={
                    "snapshot_version": 4,
                    "question_type": "picture_description",
                    "exercise": {
                        "source": {"kind": "image", "asset_id": "a" * 32, "sha256": "b" * 64}
                    },
                },
            )
        )
        db.flush()
        db.add(
            Attempt(
                user_id=1,
                session_card_id=1,
                idempotency_key="answer",
                value={"free_text": "Private old text", "_grading": {"version": 2}},
                correct=True,
            )
        )
        db.add(
            Job(
                id=1,
                user_id=1,
                kind="evaluate_response",
                payload={"revision": 1},
                status="succeeded",
            )
        )
        db.flush()
        db.add(
            Evaluation(
                session_card_id=1,
                user_id=1,
                job_id=1,
                request_key="answer",
                fingerprint="c" * 64,
                request_keys=["answer"],
                submission={"free_text": "Private old text"},
                status="completed",
                applied_result={"version": 2},
            )
        )
        db.add(
            EvaluationRequest(
                job_id=1,
                user_id=1,
                attempt_no=1,
                request_key="answer",
                reserved_at=now(),
                model="test",
                status="succeeded",
            )
        )
        db.add(ImageAsset(id="a" * 32, filename="private.webp", owner_user_id=1, stage="ready"))
        db.flush()
        db.add(
            SessionImage(session_card_id=1, asset_id="a" * 32, slot="question", image_role="source")
        )
        db.commit()
    engine.dispose()
    clone = tmp_path / "copy.sqlite3"
    shutil.copy2(original, clone)
    original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    private = tmp_path / "private.webp"
    private.write_bytes(b"private image placeholder")
    engine = create_engine(f"sqlite:///{clone}")
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        names = [
            name for name in inspect(connection).get_table_names() if name != "alembic_version"
        ]
        before = {name: connection.execute(text(f'SELECT * FROM "{name}"')).all() for name in names}
        config.attributes["connection"] = connection
        command.upgrade(config, "0011")
        assert {
            name: connection.execute(text(f'SELECT * FROM "{name}"')).all() for name in names
        } == before
        assert connection.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        assert {"audio_answers", "transcription_requests"} <= set(
            inspect(connection).get_table_names()
        )
    engine.dispose()
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_hash
    assert private.read_bytes() == b"private image placeholder"


def test_text_completion_cancels_queued_audio_without_send(client, app, monkeypatch):
    from app.models import TranscriptionRequest
    from test_evaluations import install_evaluator, submit

    session = setup_audio(client, app)
    audio = upload(client, session).json()
    evaluation = submit(client, session).json()
    with install_evaluator(monkeypatch, app):
        run_job(app.state.db, None, evaluation["job_id"])
    with install_transcriber(
        monkeypatch,
        app,
        lambda request: (_ for _ in ()).throw(AssertionError("paid after completion")),
    ):
        run_job(app.state.db, None, audio["job_id"])
    assert (
        client.get(f"/api/audio-answers/{audio['audio_answer_id']}").json()["status"] == "discarded"
    )
    with app.state.db.session() as db:
        assert list(db.scalars(select(TranscriptionRequest))) == []
    assert not list((app.state.settings.data_dir / "answer-audio").iterdir())

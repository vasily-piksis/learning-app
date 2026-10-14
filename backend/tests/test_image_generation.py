"""Image attempts are explicit, private, counted once, and never retried by workers."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from app.jobs import recover_jobs, run_job
from app.models import Card, Job
from sqlalchemy import select
from test_question_images import image_bytes, question, upload


@pytest.fixture
def enabled(app, monkeypatch):
    global images
    from app import image_generation as images

    settings = app.state.settings
    settings.image_generation_enabled = True
    settings.openai_image_model = "operator-image-model"
    settings.openai_api_key = "test-secret"
    calls = []

    def generate(self, prompt):
        calls.append((self.model, prompt))
        return images.GeneratedImage(image_bytes(), {"usage": {"total_tokens": 12}})

    monkeypatch.setattr(images.ImageGenerator, "generate", generate)
    return calls


def start(client, card, key="first", **extra):
    return client.post(
        f"/api/cards/{card['id']}/generate-image",
        json={
            "version": card["version"],
            "slot": "question",
            "prompt": "A blue bird",
            "idempotency_key": key,
            **extra,
        },
    )


def run(app, identifier):
    run_job(app.state.db, app.state.ai, identifier)


def attempts(app):
    from app.models import ImageRequest

    with app.state.db.session() as db:
        return list(db.scalars(select(ImageRequest).order_by(ImageRequest.id)))


def test_disabled_and_missing_model_leave_upload_available(client, app):
    _, card = question(client, app)
    assert start(client, card).status_code == 503
    state = client.get("/api/image-generation").json()
    assert state["status"] == "disabled" and state["remaining"] == 10
    app.state.settings.image_generation_enabled = True
    assert start(client, card).status_code == 503
    assert client.get("/api/image-generation").json()["status"] == "missing_model"
    assert upload(client, card).status_code == 200
    assert attempts(app) == []


def test_single_private_candidate_idempotency_and_captured_settings(client, app, enabled):
    _, card = question(client, app)
    job = start(client, card).json()
    assert start(client, card).json()["id"] == job["id"]
    assert start(client, card, prompt="different").status_code == 409
    assert start(client, card, "second").status_code == 409
    assert start(client, card, "bad", quality="high").status_code == 422
    assert not attempts(app)
    app.state.settings.openai_image_model = "changed-model"
    run(app, job["id"])
    run(app, job["id"])
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert result["status"] == "succeeded"
    candidate = result["result"]["candidate"]
    assert candidate["origin"] == "generated"
    assert client.get(candidate["url"]).status_code == 200
    assert (
        client.get(f"/api/cards/{card['id']}/image-candidates").json()["items"][0]["id"]
        == candidate["id"]
    )
    assert enabled == [("operator-image-model", "A blue bird")]
    ledger = attempts(app)
    assert len(ledger) == 1 and ledger[0].status == "succeeded"
    assert ledger[0].settings == images.FIXED_SETTINGS
    assert "prompt" not in ledger[0].usage
    with app.state.db.session() as db:
        assert db.get(Card, card["id"]).version == card["version"]
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 409


def test_unknown_manual_retries_exhaust_shared_budget(client, app, enabled, monkeypatch):
    _, card = question(client, app)
    calls = []

    def timeout(self, prompt):
        calls.append(prompt)
        raise images.ImageOutcomeUnknown()

    monkeypatch.setattr(images.ImageGenerator, "generate", timeout)
    job = start(client, card).json()
    for number in range(10):
        if number:
            response = client.post(
                f"/api/jobs/{job['id']}/retry-image",
                json={"idempotency_key": f"retry-{number}", "acknowledge_extra_cost": True},
            )
            assert response.status_code == 200, response.text
            assert (
                client.post(
                    f"/api/jobs/{job['id']}/retry-image",
                    json={"idempotency_key": f"retry-{number}", "acknowledge_extra_cost": True},
                ).json()["id"]
                == job["id"]
            )
        run(app, job["id"])
        assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "unknown"
        recover_jobs(app.state.db)
    assert len(calls) == len(attempts(app)) == 10
    response = client.post(
        f"/api/jobs/{job['id']}/retry-image",
        json={"idempotency_key": "eleventh", "acknowledge_extra_cost": True},
    )
    assert response.status_code == 429
    assert client.get("/api/image-generation").json()["remaining"] == 0
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 409


def test_local_save_retry_never_sends_another_request(client, app, enabled, monkeypatch):
    _, card = question(client, app)
    job = start(client, card).json()
    original = images.finish_candidate
    monkeypatch.setattr(
        images, "finish_candidate", lambda *args: (_ for _ in ()).throw(OSError("disk failure"))
    )
    run(app, job["id"])
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert result["status"] == "failed" and result["result"]["can_retry_save"]
    assert (
        client.post(
            f"/api/jobs/{job['id']}/retry-image",
            json={"idempotency_key": "paid-again", "acknowledge_extra_cost": True},
        ).status_code
        == 409
    )
    monkeypatch.setattr(images, "finish_candidate", original)
    recover_jobs(app.state.db)
    assert client.post(f"/api/jobs/{job['id']}/retry-image-save").json()["status"] == "succeeded"
    assert len(enabled) == len(attempts(app)) == 1


def test_version_change_retains_obsolete_candidate_delete_retains_ledger(
    client, app, enabled, monkeypatch
):
    _, card = question(client, app)

    def changed(self, prompt):
        with app.state.db.session() as db:
            db.get(Card, card["id"]).version += 1
        return images.GeneratedImage(image_bytes())

    monkeypatch.setattr(images.ImageGenerator, "generate", changed)
    job = start(client, card).json()
    run(app, job["id"])
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert result["result"]["candidate"]["stage"] == "obsolete"
    assert client.delete(f"/api/cards/{card['id']}").status_code == 200
    assert len(attempts(app)) == 1
    with app.state.db.session() as db:
        job = db.get(Job, job["id"])
        assert "prompt" not in job.payload and job.result is None


@pytest.mark.parametrize("day,hours", [("2026-03-29", 23), ("2026-10-25", 25)])
def test_budget_dst(day, hours):
    from app import image_generation as images

    start_day, end_day = images.budget_window(
        datetime.fromisoformat(day).replace(tzinfo=UTC), "Europe/Vilnius"
    )
    assert (end_day - start_day).total_seconds() == hours * 3600


def test_concurrent_workers_reserve_last_slot_once(client, app, enabled):
    _, card = question(client, app)
    app.state.settings.image_daily_request_limit = 1
    first = start(client, card).json()
    second = start(client, card, "answer", slot="answer").json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda identifier: run(app, identifier), [first["id"], second["id"]]))
    assert len(enabled) == len(attempts(app)) == 1
    assert sorted(client.get(f"/api/jobs/{j['id']}").json()["status"] for j in [first, second]) == [
        "failed",
        "succeeded",
    ]


def test_private_job_and_other_user_busy(client, app, enabled):
    from fastapi.testclient import TestClient

    _, card = question(client, app)
    job = start(client, card).json()
    with TestClient(app) as other:
        login = other.post(
            "/api/auth/login",
            json={"username": "parent", "password": "parent-password"},
            headers={"Origin": "http://testserver"},
        )
        other.headers.update(
            {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf_token"]}
        )
        assert other.get(f"/api/jobs/{job['id']}").status_code == 404
        assert job["id"] not in [item["id"] for item in other.get("/api/jobs").json()]
        assert start(other, card, "other-user").status_code == 409
        for route, body in [
            ("retry", {}),
            ("retry-image", {"idempotency_key": "retry", "acknowledge_extra_cost": True}),
            ("retry-image-save", {}),
            ("discard-image", {}),
        ]:
            assert other.post(f"/api/jobs/{job['id']}/{route}", json=body).status_code == 404


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
def test_adapter_status_errors_are_sanitized_and_not_retried(
    client, app, enabled, monkeypatch, status
):
    from types import SimpleNamespace

    import httpx
    from openai import APIStatusError

    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        response = httpx.Response(status, request=httpx.Request("POST", "https://example.invalid"))
        raise APIStatusError("secret provider body", response=response, body={"secret": "prompt"})

    def create_client(**kwargs):
        assert kwargs["max_retries"] == 0
        return SimpleNamespace(images=SimpleNamespace(generate=generate))

    monkeypatch.undo()
    monkeypatch.setattr(images, "OpenAI", create_client)
    _, card = question(client, app)
    job = start(client, card).json()
    run(app, job["id"])
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert result["status"] == ("unknown" if status >= 500 else "failed")
    assert "secret" not in str(result)
    assert len(calls) == len(attempts(app)) == 1
    assert calls[0] == {
        "model": "operator-image-model",
        "prompt": "A blue bird",
        **images.FIXED_SETTINGS,
    }
    if status in {401, 403}:
        assert client.get("/api/image-generation").json()["access_status"] == "denied"
    assert upload(client, card).status_code == 200


@pytest.mark.parametrize("change", ["disabled", "version", "deleted", "cancelled"])
def test_change_before_send_consumes_no_attempt(client, app, enabled, change):
    _, card = question(client, app)
    job = start(client, card).json()
    if change == "disabled":
        app.state.settings.image_generation_enabled = False
    elif change == "version":
        with app.state.db.session() as db:
            db.get(Card, card["id"]).version += 1
    elif change == "deleted":
        client.delete(f"/api/cards/{card['id']}")
    else:
        client.post(f"/api/jobs/{job['id']}/discard-image")
    run(app, job["id"])
    assert enabled == [] and attempts(app) == []


@pytest.mark.parametrize("action", ["delete", "cancel"])
def test_late_response_after_delete_or_cancel_cannot_resurrect_asset(
    client, app, enabled, monkeypatch, action
):
    from app.models import ImageAsset, JobImage

    _, card = question(client, app)
    job = start(client, card).json()

    def response(self, prompt):
        if action == "delete":
            client.delete(f"/api/cards/{card['id']}")
        else:
            client.post(f"/api/jobs/{job['id']}/discard-image")
        return images.GeneratedImage(image_bytes())

    monkeypatch.setattr(images.ImageGenerator, "generate", response)
    run(app, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "cancelled"
    assert len(attempts(app)) == 1
    with app.state.db.session() as db:
        assert list(db.scalars(select(ImageAsset))) == []
        assert list(db.scalars(select(JobImage))) == []
    assert not list((app.state.settings.data_dir / "question-images").glob("*"))


def test_job_queued_yesterday_is_counted_on_send_day(client, app, enabled, monkeypatch):
    _, card = question(client, app)
    job = start(client, card).json()
    with app.state.db.session() as db:
        db.get(Job, job["id"]).created = datetime(2020, 1, 1)
    current = datetime(2026, 10, 14, 21, 1, tzinfo=UTC)  # Oct 15 in Vilnius
    monkeypatch.setattr(images, "utc_now", lambda: current)
    run(app, job["id"])
    ledger = attempts(app)
    assert ledger[0].reserved_at == current.replace(tzinfo=None)
    state = client.get("/api/image-generation").json()
    assert state["used"] == 1 and state["next_reset_at"] == "2026-10-15T21:00:00+00:00"


def test_crash_after_send_never_auto_retries(client, app, enabled, monkeypatch):
    _, card = question(client, app)
    job = start(client, card).json()

    def crash(self, prompt):
        raise SystemExit("simulated process death after provider send")

    monkeypatch.setattr(images.ImageGenerator, "generate", crash)
    with pytest.raises(SystemExit):
        run(app, job["id"])
    assert attempts(app)[0].status == "sent"
    recover_jobs(app.state.db)
    run(app, job["id"])
    assert attempts(app)[0].status == "unknown"
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert result["status"] == "unknown" and not result["result"]["can_retry_save"]


def test_ram_only_response_loss_has_no_local_retry(client, app, enabled, monkeypatch):
    _, card = question(client, app)
    job = start(client, card).json()
    monkeypatch.setattr(
        images, "stage_image", lambda *args: (_ for _ in ()).throw(OSError("lost bytes"))
    )
    run(app, job["id"])
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert result["status"] == "unknown"
    assert not (result["result"] or {}).get("can_retry_save")
    assert client.post(f"/api/jobs/{job['id']}/retry-image-save").status_code == 409
    assert len(enabled) == len(attempts(app)) == 1


def test_discard_generated_candidate_clears_job_prompt_and_result(client, app, enabled):
    _, card = question(client, app)
    job = start(client, card).json()
    run(app, job["id"])
    candidate = client.get(f"/api/jobs/{job['id']}").json()["result"]["candidate"]
    assert client.delete(f"/api/image-candidates/{candidate['id']}").status_code == 200
    with app.state.db.session() as db:
        stored = db.get(Job, job["id"])
        assert "prompt" not in stored.payload and stored.result is None
    assert len(attempts(app)) == 1


def test_missing_staged_bytes_detach_reference_without_recovering_active_upload(
    client, app, enabled, monkeypatch
):
    from app.models import ImageAsset, JobImage

    _, card = question(client, app)
    job = start(client, card).json()
    finish = images.finish_candidate
    monkeypatch.setattr(
        images, "finish_candidate", lambda *args: (_ for _ in ()).throw(OSError("disk"))
    )
    run(app, job["id"])
    with app.state.db.session() as db:
        asset = images.staged_asset(db, job["id"])
        images.Path(str(images.asset_path(app.state.db, asset)) + ".part").unlink()
        db.add(
            ImageAsset(
                id="active",
                filename="active.webp",
                owner_user_id=1,
                target_card_id=card["id"],
                target_version=card["version"],
                slot="answer",
            )
        )
    monkeypatch.setattr(images, "finish_candidate", finish)
    response = client.post(f"/api/jobs/{job['id']}/retry-image-save")
    assert response.json()["status"] == "unknown"
    with app.state.db.session() as db:
        assert db.get(ImageAsset, "active").stage == "writing"
        assert list(db.scalars(select(JobImage).where(JobImage.job_id == job["id"]))) == []


def test_paid_retry_requires_boolean_acknowledgement(client, app, enabled, monkeypatch):
    _, card = question(client, app)
    job = start(client, card).json()
    monkeypatch.setattr(
        images.ImageGenerator,
        "generate",
        lambda *args: (_ for _ in ()).throw(images.ImageOutcomeUnknown()),
    )
    run(app, job["id"])
    for acknowledgement in [False, 1, "true"]:
        response = client.post(
            f"/api/jobs/{job['id']}/retry-image",
            json={"idempotency_key": "retry", "acknowledge_extra_cost": acknowledgement},
        )
        assert response.status_code == 422


def test_job_dto_identifies_target_slot_without_prompt(client, app, enabled):
    _, card = question(client, app)
    job = start(client, card).json()
    assert job["card_id"] == card["id"] and job["slot"] == "question"
    assert "prompt" not in job


def test_durable_file_before_state_commit_offers_local_retry(client, app, enabled, monkeypatch):
    _, card = question(client, app)
    job = start(client, card).json()
    original = images.stage_image

    def interrupted(database, identifier, generated):
        original(database, identifier, generated)
        with database.session() as db:
            db.get(
                Job, identifier
            ).result = None  # emulate loss of state commit after fsynced bytes
        raise OSError("interrupted")

    monkeypatch.setattr(images, "stage_image", interrupted)
    run(app, job["id"])
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert result["status"] == "failed" and result["result"]["can_retry_save"]
    assert client.post(f"/api/jobs/{job['id']}/retry-image-save").json()["status"] == "succeeded"
    assert len(enabled) == 1


def test_replay_after_deletion_keeps_tombstone_and_consumed_quota(client, app, enabled):
    _, card = question(client, app)
    job = start(client, card).json()
    run(app, job["id"])
    client.delete(f"/api/cards/{card['id']}")
    replay = start(client, card)
    assert replay.status_code == 200 and replay.json()["id"] == job["id"]
    assert replay.json()["status"] == "cancelled" and replay.json()["result"] is None
    assert start(client, card, prompt="changed").status_code == 409
    assert client.get("/api/image-generation").json()["used"] == 1


@pytest.mark.parametrize("outcome", ["success", "timeout", "connection", "refusal"])
def test_adapter_bytes_transport_errors_and_missing_result(monkeypatch, app, outcome):
    import base64
    from types import SimpleNamespace

    import httpx
    from app import image_generation as images
    from openai import APIConnectionError, APITimeoutError

    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        if outcome == "timeout":
            raise APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
        if outcome == "connection":
            raise APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))
        data = (
            [SimpleNamespace(b64_json=base64.b64encode(image_bytes()).decode())]
            if outcome == "success"
            else []
        )
        return SimpleNamespace(data=data, usage=None)

    def client(**kwargs):
        assert kwargs["max_retries"] == 0
        return SimpleNamespace(images=SimpleNamespace(generate=generate))

    monkeypatch.setattr(images, "OpenAI", client)
    adapter = images.ImageGenerator(app.state.settings, "selected")
    if outcome == "success":
        assert adapter.generate("bird").data == image_bytes()
    else:
        with pytest.raises(images.ImageOutcomeUnknown):
            adapter.generate("bird")
    assert len(calls) == 1


def test_migration_0008_preserves_all_prior_rows_and_files(tmp_path):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine(f"sqlite:///{tmp_path / 'old.sqlite3'}")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    saved = tmp_path / "original.webp"
    saved.write_bytes(image_bytes("WEBP"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0007")
        connection.execute(text("INSERT INTO users VALUES(1,'child','Learner','hash',1)"))
        connection.execute(
            text("INSERT INTO subjects(id,name,created) VALUES(1,'Subject','2026-01-01')")
        )
        tables = inspect(connection).get_table_names()
        before = {
            table: list(connection.execute(text(f"SELECT * FROM {table}")))
            for table in tables
            if table != "alembic_version"
        }
        command.upgrade(config, "0008")
        after = {
            table: list(connection.execute(text(f"SELECT * FROM {table}")))
            for table in tables
            if table != "alembic_version"
        }
        assert before == after
        assert "image_requests" in inspect(connection).get_table_names()
        assert connection.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    assert saved.read_bytes() == image_bytes("WEBP")


def test_recovered_candidate_missing_file_never_reports_success(client, app, enabled, monkeypatch):
    _, card = question(client, app)
    job = start(client, card).json()
    original = images.finish_candidate
    monkeypatch.setattr(
        images, "finish_candidate", lambda *args: (_ for _ in ()).throw(OSError("disk"))
    )
    run(app, job["id"])
    recover_jobs(app.state.db)
    with app.state.db.session() as db:
        asset = images.staged_asset(db, job["id"])
        assert asset.stage == "draft"
        images.asset_path(app.state.db, asset).unlink()
    monkeypatch.setattr(images, "finish_candidate", original)
    response = client.post(f"/api/jobs/{job['id']}/retry-image-save")
    assert response.json()["status"] == "unknown"
    assert not response.json()["result"]["can_retry_save"]


def test_quota_and_reservation_use_same_instant_at_midnight(client, app, enabled, monkeypatch):
    _, card = question(client, app)
    job = start(client, card).json()
    times = iter(
        [
            datetime(2026, 10, 14, 20, 59, 59, tzinfo=UTC),
            datetime(2026, 10, 14, 21, 0, 0, tzinfo=UTC),
        ]
    )
    monkeypatch.setattr(images, "utc_now", lambda: next(times))
    run(app, job["id"])
    assert attempts(app)[0].reserved_at == datetime(2026, 10, 14, 20, 59, 59)


def test_candidate_applied_between_file_write_and_job_finish_stays_successful(
    client, app, enabled, monkeypatch
):
    from test_question_images import save

    _, card = question(client, app)
    job = start(client, card).json()
    original = images.write_candidate

    def publish_and_apply(*args):
        candidate = original(*args)
        assert (
            save(
                client, card, {"question": {"asset_id": candidate["id"], "alt": "Bird"}}
            ).status_code
            == 200
        )
        return candidate

    monkeypatch.setattr(images, "write_candidate", publish_and_apply)
    run(app, job["id"])
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert result["status"] == "succeeded"
    assert result["result"]["applied_asset_id"]
    assert result["result"]["can_retry_save"] is False


def test_cancel_during_local_save_failure_keeps_cancelled_tombstone(
    client, app, enabled, monkeypatch
):
    _, card = question(client, app)
    job = start(client, card).json()
    monkeypatch.setattr(
        images, "finish_candidate", lambda *args: (_ for _ in ()).throw(OSError("disk"))
    )
    run(app, job["id"])

    def cancelled_then_missing(database, identifier):
        assert client.post(f"/api/jobs/{identifier}/discard-image").status_code == 200
        raise images.ImageOutcomeUnknown()

    monkeypatch.setattr(images, "finish_candidate", cancelled_then_missing)
    response = client.post(f"/api/jobs/{job['id']}/retry-image-save")
    assert response.json()["status"] == "cancelled"
    assert response.json()["result"] is None


@pytest.mark.parametrize("failure", [OSError, SystemExit])
@pytest.mark.parametrize("after_replace", [False, True])
def test_publication_interruption_preserves_staged_bytes_for_free_retry(
    client, app, enabled, monkeypatch, failure, after_replace
):
    from pathlib import Path

    _, card = question(client, app)
    job = start(client, card).json()
    publish = images.write_candidate
    original_bytes = []
    candidate_paths = []

    def interrupted_publication(*args):
        database, identifier = args[:2]
        with database.session() as db:
            asset = images.staged_asset(db, job["id"])
            path = images.asset_path(database, asset)
        staged = Path(str(path) + ".part")
        original_bytes.append(staged.read_bytes())
        candidate_paths.extend([staged, path])
        original_open, original_replace = Path.open, Path.replace

        class BrokenWrite:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return self.stream.__exit__(*exc)

            def write(self, data):
                raise failure("interrupted destructive publication write")

        def open_file(target, mode="r", *positional, **kwargs):
            stream = original_open(target, mode, *positional, **kwargs)
            if target == staged and mode == "wb":
                return BrokenWrite(stream)
            return stream

        def replace_file(source, target):
            if source == staged:
                if after_replace:
                    original_replace(source, target)
                raise failure("interrupted atomic publication")
            return original_replace(source, target)

        with monkeypatch.context() as publication_patch:
            publication_patch.setattr(Path, "open", open_file)
            publication_patch.setattr(Path, "replace", replace_file)
            return publish(*args)

    monkeypatch.setattr(images, "write_candidate", interrupted_publication)
    if failure is SystemExit:
        with pytest.raises(SystemExit):
            run(app, job["id"])
    else:
        run(app, job["id"])
    assert any(path.exists() and path.read_bytes() == original_bytes[0] for path in candidate_paths)
    monkeypatch.setattr(images, "write_candidate", publish)
    # A process death requires recovery; a handled write error retries immediately.
    # Either path discovers the original .part or the atomically published file.
    if failure is SystemExit:
        recover_jobs(app.state.db)
    response = client.post(f"/api/jobs/{job['id']}/retry-image-save")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "succeeded"
    assert client.get(result["result"]["candidate"]["url"]).content == original_bytes[0]
    assert len(enabled) == len(attempts(app)) == 1


def test_publication_fsync_failure_does_not_discard_already_durable_bytes(
    client, app, enabled, monkeypatch
):
    _, card = question(client, app)
    job = start(client, card).json()
    publish = images.write_candidate
    fsync = images.os.fsync
    original_bytes = []
    candidate_paths = []

    def publication_with_disk_failure(*args):
        with app.state.db.session() as db:
            asset = images.staged_asset(db, job["id"])
            path = images.asset_path(app.state.db, asset)
        staged = images.Path(str(path) + ".part")
        original_bytes.append(staged.read_bytes())
        candidate_paths.extend([staged, path])
        monkeypatch.setattr(
            images.os, "fsync", lambda _: (_ for _ in ()).throw(OSError("disk unavailable"))
        )
        return publish(*args)

    monkeypatch.setattr(images, "write_candidate", publication_with_disk_failure)
    run(app, job["id"])
    assert any(path.exists() and path.read_bytes() == original_bytes[0] for path in candidate_paths)
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert result["status"] == "failed" and result["result"]["can_retry_save"]
    monkeypatch.setattr(images.os, "fsync", fsync)
    monkeypatch.setattr(images, "write_candidate", publish)
    response = client.post(f"/api/jobs/{job['id']}/retry-image-save")
    assert response.json()["status"] == "succeeded"
    assert client.get(response.json()["result"]["candidate"]["url"]).content == original_bytes[0]
    assert len(enabled) == len(attempts(app)) == 1


def test_card_image_job_filter_recovers_older_owned_work_before_limit(client, app, enabled):
    _, card = question(client, app)
    old = start(client, card).json()
    with app.state.db.session() as db:
        image_job = db.get(Job, old["id"])
        owner = image_job.user_id
        image_job.status = "unknown"
        db.add_all(
            Job(kind="generate", user_id=owner, status="succeeded", payload={}, result={})
            for _ in range(101)
        )
        db.add(
            Job(
                kind="generate_image",
                user_id=owner,
                status="failed",
                payload={"card_id": card["id"] + 1, "slot": "question"},
            )
        )
    assert old["id"] not in [job["id"] for job in client.get("/api/jobs").json()]
    path = f"/api/jobs?card_id={card['id']}&kind=generate_image"
    recovered = client.get(path)
    assert recovered.status_code == 200
    assert [(job["id"], job["status"]) for job in recovered.json()] == [(old["id"], "unknown")]
    assert client.get("/api/jobs?card_id=0&kind=generate_image").status_code == 422
    assert client.get(f"/api/jobs?card_id={card['id']}&kind=explain").status_code == 422
    login = client.post(
        "/api/auth/login", json={"username": "parent", "password": "parent-password"}
    ).json()
    client.headers.update({"X-CSRF-Token": login["csrf_token"]})
    assert client.get(path).json() == []

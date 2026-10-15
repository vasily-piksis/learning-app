from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from app.jobs import recover_jobs, run_job
from app.models import Attempt, Job, StudySession
from sqlalchemy import func, select
from test_evaluations import install_evaluator, setup_free, start_free, submit


def test_stage_recovers_without_new_request(client, app, monkeypatch):
    import app.evaluations as module
    from app.models import Evaluation, EvaluationRequest

    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()
    original = module.finalize_evaluation
    monkeypatch.setattr(
        module, "finalize_evaluation", lambda *args: (_ for _ in ()).throw(RuntimeError("crash"))
    )
    with install_evaluator(monkeypatch, app):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    with app.state.db.session() as db:
        assert db.get(Evaluation, pending["evaluation_id"]).staged_result is not None
        assert db.scalar(select(func.count(Attempt.id))) == 0
    monkeypatch.setattr(module, "finalize_evaluation", original)
    recover_jobs(app.state.db)
    recover_jobs(app.state.db)
    assert submit(client, session).json()["score"] == 88
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(EvaluationRequest.id))) == 1
        assert db.scalar(select(func.count(Attempt.id))) == 1
        assert db.get(StudySession, session).position == 1


def test_running_unknown_restart_never_resends(client, app):
    from app.evaluations import reserve_evaluation_request
    from app.models import Evaluation, EvaluationRequest

    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()
    with app.state.db.session() as db:
        db.get(Job, pending["job_id"]).status = "running"
        db.get(Evaluation, pending["evaluation_id"]).status = "running"
    reserve_evaluation_request(app.state.db, pending["job_id"], "initial")
    recover_jobs(app.state.db)
    run_job(app.state.db, None, pending["job_id"])
    assert client.get(f"/api/study/{session}/evaluations?position=0").json()["status"] == "unknown"
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(EvaluationRequest.id))) == 1
        assert db.scalar(select(func.count(Attempt.id))) == 0


def test_family_quota_100_concurrent_no_refund_and_timezone(client, app, monkeypatch):
    import app.evaluations as module
    from app.models import Evaluation, EvaluationRequest

    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()
    with app.state.db.session() as db:
        db.get(Job, pending["job_id"]).status = "running"
        db.get(Evaluation, pending["evaluation_id"]).status = "running"
    current = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    monkeypatch.setattr(module, "utc_now", lambda: current)

    def reserve(_):
        try:
            module.reserve_evaluation_request(app.state.db, pending["job_id"], "initial")
            return True
        except module.EvaluationQuotaExceeded:
            return False

    with ThreadPoolExecutor(8) as pool:
        assert sum(pool.map(reserve, range(101))) == 100
    with app.state.db.session() as db:
        rows = list(db.scalars(select(EvaluationRequest)))
        assert len(rows) == 100 and all(r.usage is None for r in rows)
    current = datetime(2026, 10, 25, 22, 1, tzinfo=UTC)
    assert reserve(0)
    current += timedelta(days=31)
    module.cleanup_evaluation_requests(app.state.db)
    module.cleanup_evaluation_requests(app.state.db)
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(EvaluationRequest.id))) == 0


def test_stale_revision_cannot_charge_stage_or_finalize_after_manual_retry(client, app):
    from app.evaluations import (
        EvaluationCancelled,
        finalize_evaluation,
        reserve_evaluation_request,
        stage_evaluation,
    )
    from app.free_responses import FreeResponseEvaluation
    from app.models import Evaluation, EvaluationRequest
    from test_evaluations import valid_result

    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()
    with app.state.db.session() as db:
        db.get(Job, pending["job_id"]).status = "running"
        db.get(Evaluation, pending["evaluation_id"]).status = "running"
    reserve_evaluation_request(app.state.db, pending["job_id"], "initial")
    recover_jobs(app.state.db)
    assert (
        client.post(
            f"/api/evaluations/{pending['evaluation_id']}/retry",
            json={"idempotency_key": "new", "acknowledge_extra_cost": True},
        ).status_code
        == 202
    )
    with app.state.db.session() as db:
        db.get(Job, pending["job_id"]).status = "running"
        db.get(Evaluation, pending["evaluation_id"]).status = "running"
    with pytest.raises(EvaluationCancelled):
        reserve_evaluation_request(app.state.db, pending["job_id"], "initial")
    with pytest.raises(EvaluationCancelled):
        stage_evaluation(
            app.state.db,
            pending["evaluation_id"],
            1,
            FreeResponseEvaluation.model_validate(valid_result()),
        )
    with pytest.raises(EvaluationCancelled):
        finalize_evaluation(app.state.db, pending["evaluation_id"], 1, {})
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(EvaluationRequest.id))) == 1
        assert db.scalar(select(func.count(Attempt.id))) == 0


def test_commit_ack_loss_replay_applies_exactly_once(client, app, monkeypatch):
    import app.evaluations as module
    from app.models import EvaluationRequest

    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()
    original = module.finalize_evaluation

    def lost_ack(*args):
        original(*args)
        raise TimeoutError("commit response lost")

    monkeypatch.setattr(module, "finalize_evaluation", lost_ack)
    with install_evaluator(monkeypatch, app):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    monkeypatch.setattr(module, "finalize_evaluation", original)
    recover_jobs(app.state.db)
    assert submit(client, session).json()["score"] == 88
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(Attempt.id))) == 1
        assert db.scalar(select(func.count(EvaluationRequest.id))) == 1
        assert db.get(StudySession, session).position == 1


def test_real_0008_database_copy_upgrade_preserves_rows_json_files_and_foreign_keys(tmp_path):
    import shutil
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import IntegrityError
    from test_question_images import image_bytes

    old = tmp_path / "old"
    old.mkdir()
    (old / "files").mkdir()
    (old / "files" / "original.webp").write_bytes(image_bytes("WEBP"))
    (old / "files" / "source.txt").write_bytes("Ąžuolas yra medis.\n".encode())
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    engine = create_engine(f"sqlite:///{old / 'learning.sqlite3'}")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0008")
        connection.execute(text("INSERT INTO users VALUES(1,'child','Learner','hash',1)"))
        connection.execute(
            text("INSERT INTO subjects(id,name,deleted,created) VALUES(1,'Subject',0,'2026-01-01')")
        )
        connection.execute(
            text(
                "INSERT INTO topics(id,subject_id,name,version,deleted,created) VALUES(1,1,'Topic',1,0,'2026-01-01')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO study_sessions VALUES(1,1,'[1]','quiz',1,'completed','2026-01-01','2026-01-01')"
            )
        )
        connection.execute(
            text("INSERT INTO session_cards VALUES(1,1,0,:snapshot,0)"),
            {
                "snapshot": '{ "question": "Ąžuolas?", "mode": "quiz", "options": ["medis"], "correct_index": 0, "sources": [] }'
            },
        )
        connection.execute(
            text("INSERT INTO attempts VALUES(1,1,1,'legacy',:value,1,'2026-01-01')"),
            {"value": '{ "choice": 0 }'},
        )
        connection.execute(
            text(
                "INSERT INTO jobs VALUES(1,1,'generate','succeeded',:payload,:result,NULL,'2026-01-01','2026-01-01')"
            ),
            {"payload": '{ "topic_ids": [1] }', "result": '{ "card_ids": [] }'},
        )
        connection.execute(
            text(
                "INSERT INTO image_requests VALUES(1,1,1,1,'old-key','hash','2026-01-01','unknown','disabled-model','{}','{}',NULL)"
            )
        )
    engine.dispose()
    copied = tmp_path / "copy"
    shutil.copytree(old, copied)
    files = {p.name: p.read_bytes() for p in (copied / "files").iterdir()}
    engine = create_engine(f"sqlite:///{copied / 'learning.sqlite3'}")
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
        tables = [t for t in inspect(connection).get_table_names() if t != "alembic_version"]
        before = {t: connection.execute(text(f"SELECT * FROM {t}")).all() for t in tables}
        config.attributes["connection"] = connection
        command.upgrade(config, "0009")
        connection.commit()
        assert {t: connection.execute(text(f"SELECT * FROM {t}")).all() for t in tables} == before
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0009"
        )
        assert connection.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO evaluation_requests(job_id,user_id,attempt_no,request_key,reserved_at,status,model) VALUES(999,1,1,'bad','2026-01-01','reserved','model')"
                )
            )
        connection.rollback()
    assert {p.name: p.read_bytes() for p in (copied / "files").iterdir()} == files
    original_engine = create_engine(f"sqlite:///{old / 'learning.sqlite3'}")
    with original_engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0008"
        )
    engine.dispose()
    original_engine.dispose()


def test_staged_result_stays_private_and_paid_success_survives_local_failure(
    client, app, monkeypatch
):
    import app.evaluations as module
    from app.models import EvaluationRequest

    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()
    monkeypatch.setattr(
        module,
        "finalize_evaluation",
        lambda *args: (_ for _ in ()).throw(TimeoutError("local commit")),
    )
    with install_evaluator(monkeypatch, app):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    status = client.get(f"/api/study/{session}/evaluations?position=0").json()
    assert status["status"] == "running"
    assert "feedback" not in status and "rubric_scores" not in str(status)
    assert client.get(f"/api/jobs/{pending['job_id']}").json()["result"] is None
    with app.state.db.session() as db:
        record = db.scalar(select(EvaluationRequest))
        assert record.status == "succeeded" and record.error_code is None


def test_worker_purges_expired_ledger_without_restarting(client, app, monkeypatch):
    import app.evaluations as module
    import app.jobs as jobs
    from app.models import EvaluationRequest

    current = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(module, "utc_now", lambda: current)
    with app.state.db.session() as db:
        job = Job(user_id=1, kind="evaluate_response", status="deleted", payload={})
        db.add(job)
        db.flush()
        db.add(
            EvaluationRequest(
                job_id=job.id,
                user_id=1,
                attempt_no=1,
                request_key="old",
                reserved_at=current.replace(tzinfo=None),
                status="unknown",
                model="model",
                usage=None,
            )
        )
    ticks = iter([0, 3601])
    # Real worker loop, fake only passage of time and its stop event.
    monkeypatch.setattr(jobs, "maintenance_clock", lambda: next(ticks), raising=False)

    class Stop:
        loops = 0

        def is_set(self):
            self.loops += 1
            return self.loops > 2

        def wait(self, _):
            nonlocal current
            current += timedelta(days=31)

    jobs.worker_loop(app.state.db, None, Stop())
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(EvaluationRequest.id))) == 0
        assert db.get(Job, job.id).status == "deleted"


def test_deleted_evaluation_id_cannot_be_reused_by_a_late_worker(client, app):
    from app.evaluations import EvaluationCancelled, stage_evaluation
    from app.free_responses import FreeResponseEvaluation
    from app.models import Evaluation
    from test_evaluations import valid_result

    topic = setup_free(client, app)
    old_session = start_free(client, topic)
    old = submit(client, old_session).json()
    assert client.post("/api/study/delete", json={"session_ids": [old_session]}).status_code == 200
    new_session = start_free(client, topic)
    new = submit(client, new_session, key="new").json()
    with app.state.db.session() as db:
        db.get(Job, new["job_id"]).status = "running"
        db.get(Evaluation, new["evaluation_id"]).status = "running"
    assert new["evaluation_id"] != old["evaluation_id"]
    with pytest.raises(EvaluationCancelled):
        stage_evaluation(
            app.state.db,
            old["evaluation_id"],
            1,
            FreeResponseEvaluation.model_validate(valid_result()),
        )


def test_old_worker_failure_cannot_fail_current_manual_retry(client, app, monkeypatch):
    import httpx
    from app.models import Evaluation, EvaluationRequest

    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()

    def handler(request):
        recover_jobs(app.state.db)
        assert (
            client.post(
                f"/api/evaluations/{pending['evaluation_id']}/retry",
                json={"idempotency_key": "manual", "acknowledge_extra_cost": True},
            ).status_code
            == 202
        )
        return httpx.Response(400, json={"error": {"message": "old error"}})

    with install_evaluator(monkeypatch, app, handler):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    with app.state.db.session() as db:
        evaluation = db.get(Evaluation, pending["evaluation_id"])
        assert evaluation.status == "queued" and evaluation.revision == 2
        assert db.get(Job, pending["job_id"]).status == "queued"
        assert db.scalar(select(func.count(EvaluationRequest.id))) == 1


@pytest.mark.parametrize(
    "current,boundary",
    [
        (datetime(2026, 3, 29, 12, tzinfo=UTC), datetime(2026, 3, 28, 22, tzinfo=UTC)),
        (datetime(2026, 10, 25, 12, tzinfo=UTC), datetime(2026, 10, 24, 21, tzinfo=UTC)),
    ],
)
def test_dst_budget_boundaries_and_config_changes_count_same_utc_ledger(
    client, app, monkeypatch, current, boundary
):
    import app.evaluations as module
    from app.models import Evaluation, EvaluationRequest

    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()
    with app.state.db.session() as db:
        db.get(Job, pending["job_id"]).status = "running"
        db.get(Evaluation, pending["evaluation_id"]).status = "running"
        for i, stamp in enumerate([boundary - timedelta(microseconds=1), boundary]):
            db.add(
                EvaluationRequest(
                    job_id=pending["job_id"],
                    user_id=1,
                    attempt_no=i + 1,
                    request_key="initial",
                    reserved_at=stamp.replace(tzinfo=None),
                    status="unknown",
                    model="old-model",
                    usage=None,
                )
            )
    app.state.settings.free_response_daily_request_limit = 1
    monkeypatch.setattr(module, "utc_now", lambda: current)
    with pytest.raises(module.EvaluationQuotaExceeded):
        module.reserve_evaluation_request(app.state.db, pending["job_id"], "initial")
    # Changing model doesn't erase charges; raising a configured limit adds only capacity.
    app.state.settings.openai_model = "another-model"
    with pytest.raises(module.EvaluationQuotaExceeded):
        module.reserve_evaluation_request(app.state.db, pending["job_id"], "initial")
    app.state.settings.free_response_daily_request_limit = 2
    module.reserve_evaluation_request(app.state.db, pending["job_id"], "initial")
    app.state.settings.budget_timezone = "UTC"
    with pytest.raises(module.EvaluationQuotaExceeded):
        # UTC day now contains the fresh debit. Lowering limit still counts it.
        app.state.settings.free_response_daily_request_limit = 1
        module.reserve_evaluation_request(app.state.db, pending["job_id"], "initial")
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(EvaluationRequest.id))) == 3


def test_two_local_finalizers_race_on_same_durable_stage_once(client, app, monkeypatch):
    import app.evaluations as module
    from app.models import Evaluation, EvaluationRequest

    session = start_free(client, setup_free(client, app))
    pending = submit(client, session).json()
    original = module.finalize_evaluation
    monkeypatch.setattr(module, "finalize_evaluation", lambda *args: None)
    with install_evaluator(monkeypatch, app):
        run_job(app.state.db, app.state.ai, pending["job_id"])
    with app.state.db.session() as db:
        staged = db.get(Evaluation, pending["evaluation_id"]).staged_result
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(
                lambda _: original(app.state.db, pending["evaluation_id"], 1, staged), range(2)
            )
        )
    assert results[0] == results[1]
    assert results[0]["score"] == 88
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(Attempt.id))) == 1
        assert db.get(StudySession, session).position == 1
        assert db.scalar(select(func.count(EvaluationRequest.id))) == 1

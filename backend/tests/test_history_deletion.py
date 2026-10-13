import pytest
from app.jobs import run_job
from app.models import Attempt, Explanation, Job, SessionCard, StudySession
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from test_study import saved_cards


def start(client, topic, mode="quiz"):
    response = client.post("/api/study", json={"topic_ids": [topic], "mode": mode})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def remove(client, identifiers):
    return client.post("/api/study/delete", json={"session_ids": identifiers})


def test_bulk_removal_erases_selected_history_and_keeps_library_files(client, app):
    topic, cards = saved_cards(client, app, count=1)
    completed, active, retained = [start(client, topic) for _ in range(3)]
    client.post(
        f"/api/study/{completed}/answer",
        json={"position": 0, "choice": 0, "idempotency_key": "history-delete"},
    )
    first = client.post(f"/api/study/{completed}/explain", json={"position": 0}).json()
    run_job(app.state.db, app.state.ai, first["id"])
    parent = client.get(f"/api/jobs/{first['id']}").json()["result"]["explanation_id"]
    second = client.post(
        f"/api/study/{completed}/explain", json={"position": 0, "parent_id": parent}
    ).json()
    run_job(app.state.db, app.state.ai, second["id"])
    queued = client.post(f"/api/study/{completed}/explain", json={"position": 0}).json()
    library = {
        path: client.get(path).json()
        for path in ("/api/subjects", "/api/topics", "/api/cards", f"/api/topics/{topic}/documents")
    }
    files = {p.name: p.read_bytes() for p in (app.state.settings.data_dir / "files").iterdir()}
    response = remove(client, [completed, active, completed])
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted_count": 2}
    assert [s["id"] for s in client.get("/api/study").json()] == [retained]
    assert client.get(f"/api/study/{retained}").json()["count"] == 1
    assert cards[0]["id"] in {c["id"] for c in client.get("/api/cards").json()}
    for path, value in library.items():
        assert client.get(path).json() == value
    assert {
        p.name: p.read_bytes() for p in (app.state.settings.data_dir / "files").iterdir()
    } == files
    for identifier in (completed, active):
        assert client.get(f"/api/study/{identifier}").status_code == 404
        assert client.post(f"/api/study/{identifier}/repeat").status_code == 404
    for job in (first, second, queued):
        assert client.get(f"/api/jobs/{job['id']}").status_code == 404
        assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 404
    run_job(app.state.db, app.state.ai, queued["id"])
    with app.state.db.session() as db:
        assert list(db.scalars(select(Attempt))) == []
        assert list(db.scalars(select(Explanation))) == []
        assert [s.session_id for s in db.scalars(select(SessionCard))] == [retained]
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
        for identifier in (completed, active):
            # Empty tombstones prevent stale browser requests from hitting reused IDs.
            session = db.get(StudySession, identifier)
            assert session.status == "deleted" and session.topic_ids == []
        for job in (first, second, queued):
            value = db.get(Job, job["id"])
            assert value.status == "deleted" and value.payload == {} and value.result is None
    visible_jobs = {j["id"] for j in client.get("/api/jobs").json()}
    assert visible_jobs.isdisjoint({first["id"], second["id"], queued["id"]})
    assert start(client, topic) > retained


def test_bulk_removal_is_atomic_and_cannot_delete_another_users_history(client, app):
    topic, _ = saved_cards(client, app, count=1)
    own = start(client, topic)
    with TestClient(app) as parent:
        login = parent.post(
            "/api/auth/login",
            json={"username": "parent", "password": "parent-password"},
            headers={"Origin": "http://testserver"},
        )
        parent.headers.update(
            {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf_token"]}
        )
        foreign = start(parent, topic)
        assert remove(client, [own, foreign]).status_code == 404
        assert client.get(f"/api/study/{own}").status_code == 200
        assert parent.get(f"/api/study/{foreign}").status_code == 200
        assert remove(client, [own, 99999]).status_code == 404
        assert client.get(f"/api/study/{own}").status_code == 200
        assert remove(parent, [foreign]).status_code == 200
        assert client.get(f"/api/study/{own}").status_code == 200


@pytest.mark.parametrize("ids", [[], [True], ["1"], [0], [-1], list(range(1, 202))])
def test_bulk_removal_rejects_invalid_batches(client, ids):
    assert remove(client, ids).status_code == 422


def test_history_removal_requires_authentication_and_csrf(client, app):
    with TestClient(app) as anonymous:
        assert remove(anonymous, [1]).status_code in {401, 403}
    client.headers.pop("X-CSRF-Token")
    assert remove(client, [1]).status_code == 403


@pytest.mark.parametrize("fails", [False, True])
def test_in_flight_explanation_cannot_restore_deleted_history(client, app, fails):
    topic, _ = saved_cards(client, app, count=1)
    session = start(client, topic)
    client.post(
        f"/api/study/{session}/answer", json={"position": 0, "choice": 0, "idempotency_key": "race"}
    )
    job = client.post(f"/api/study/{session}/explain", json={"position": 0}).json()
    original_explain = app.state.ai.explain

    def explain(snapshot, question, history):
        assert remove(client, [session]).status_code == 200
        if fails:
            raise ValueError("Upstream failure after deletion")
        return original_explain(snapshot, question, history)

    app.state.ai.explain = explain
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get("/api/study").json() == []
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
    with app.state.db.session() as db:
        assert list(db.scalars(select(Explanation))) == []
        assert db.get(Job, job["id"]).payload == {}


def test_removing_highest_session_does_not_reuse_its_identifier(client, app):
    topic, _ = saved_cards(client, app, count=1)
    old = start(client, topic)
    assert remove(client, [old]).status_code == 200
    assert start(client, topic) > old
    assert client.get(f"/api/study/{old}").status_code == 404
    assert (
        client.post(
            f"/api/study/{old}/answer",
            json={"position": 0, "choice": 0, "idempotency_key": "stale-deleted"},
        ).status_code
        == 404
    )


def test_repeat_and_deletion_serialize_before_reading_snapshots(client, app, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event

    from app import study

    topic, _ = saved_cards(client, app, count=1)
    identifier = start(client, topic)
    client.post(
        f"/api/study/{identifier}/answer",
        json={"position": 0, "choice": 1, "idempotency_key": "repeat-delete"},
    )
    captured, release = Event(), Event()
    original_new_session = study.new_session

    def pause(*args, **kwargs):
        captured.set()
        assert release.wait(5)
        return original_new_session(*args, **kwargs)

    monkeypatch.setattr(study, "new_session", pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        repeating = pool.submit(client.post, f"/api/study/{identifier}/repeat")
        assert captured.wait(5)
        deleting = pool.submit(remove, client, [identifier])
        try:
            # A deletion cannot commit after repeat captured the old snapshots.
            with pytest.raises(TimeoutError):
                deleting.result(timeout=0.2)
        finally:
            release.set()
        repeated, deleted = repeating.result(), deleting.result()
    assert repeated.status_code == 200 and deleted.status_code == 200
    assert client.get(f"/api/study/{identifier}").status_code == 404
    assert [s["id"] for s in client.get("/api/study").json()] == [repeated.json()["id"]]


def test_bulk_deletion_handles_many_cards_with_bounded_sql_parameters(client, app):
    import sqlite3

    from sqlalchemy import event

    topic, _ = saved_cards(client, app, count=4)
    identifiers = [start(client, topic) for _ in range(10)]

    def bounded_parameters(connection, _):
        connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 32)

    event.listen(app.state.db.engine, "connect", bounded_parameters)
    app.state.db.engine.dispose()
    response = remove(client, identifiers)
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted_count": 10}

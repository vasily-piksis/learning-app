import pytest
from app.jobs import run_job
from app.models import CardSource, Document, Job, SourcePage, Topic
from conftest import make_topic, pdf_bytes
from fakes import FixtureAI, ready_document
from sqlalchemy import func, select, text
from test_study import saved_cards


def subject_of(client, topic):
    return client.get(f"/api/topics/{topic}").json()["subject_id"]


def test_subject_removes_all_descendants_files_and_preserves_other_subject_and_history(client, app):
    topic, _ = saved_cards(client, app, count=1)
    subject = subject_of(client, topic)
    second = client.post("/api/topics", json={"name": "Вторая тема", "subject_id": subject}).json()[
        "id"
    ]
    ready_document(client, app, second)
    job = client.post(
        "/api/generate", json={"topic_ids": [second], "count": 1, "mode": "quiz"}
    ).json()
    run_job(app.state.db, app.state.ai, job["id"])
    card_ids = [card["id"] for card in client.get(f"/api/cards?topic_id={second}").json()]
    client.post("/api/cards/save", json={"card_ids": card_ids})
    other = make_topic(client, "Другой предмет")
    retained = ready_document(client, app, other)
    session = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    client.post(
        f"/api/study/{session['id']}/answer",
        json={
            "position": 0,
            "choice": session["card"]["options"].index("Дон"),
            "idempotency_key": "subject-history",
        },
    )
    with app.state.db.session() as db:
        documents = list(db.scalars(select(Document).where(Document.topic_id.in_([topic, second]))))
        removed_files = [
            app.state.settings.data_dir / "files" / document.filename for document in documents
        ]
        retained_file = (
            app.state.settings.data_dir / "files" / db.get(Document, retained["id"]).filename
        )
    assert all(file.is_file() for file in removed_files)
    preview = client.get(f"/api/subjects/{subject}/deletion")
    assert preview.status_code == 200, preview.text
    assert {
        key: preview.json()[key] for key in ("topic_count", "document_count", "card_count")
    } == {"topic_count": 2, "document_count": 2, "card_count": 2}
    response = client.request(
        "DELETE", f"/api/subjects/{subject}", json={"revision": preview.json()["revision"]}
    )
    assert response.status_code == 200, response.text
    assert [item["id"] for item in client.get("/api/subjects").json()] == [
        subject_of(client, other)
    ]
    assert [item["id"] for item in client.get("/api/topics").json()] == [other]
    assert client.get("/api/cards").json() == []
    assert all(not file.exists() for file in removed_files)
    assert retained_file.is_file()
    assert sorted((app.state.settings.data_dir / "files").iterdir()) == [retained_file]
    for document in documents:
        assert client.get(f"/api/documents/{document.id}/download").status_code == 404
    assert (
        client.post("/api/topics", json={"name": "Запрещено", "subject_id": subject}).status_code
        == 404
    )
    assert client.patch(f"/api/subjects/{subject}", json={"name": "Вернуть"}).status_code == 404
    assert client.get(f"/api/subjects/{subject}/deletion").status_code == 404
    history = client.get(f"/api/study/{session['id']}").json()
    assert history["topic_names"] == ["Древний Египет"] and history["active_topic_ids"] == []
    assert history["review"][0]["card"]["sources"][0]["available"] is False
    assert client.post(f"/api/study/{session['id']}/repeat").status_code == 200
    explanation = client.post(f"/api/study/{session['id']}/explain", json={"position": 0}).json()
    run_job(app.state.db, app.state.ai, explanation["id"])
    assert client.get(f"/api/jobs/{explanation['id']}").json()["status"] == "succeeded"
    with app.state.db.session() as db:
        assert (
            db.scalar(
                select(func.count(SourcePage.id)).where(
                    SourcePage.document_id.in_([d.id for d in documents])
                )
            )
            == 0
        )
        assert db.scalar(select(func.count(CardSource.id))) == 0
        assert list(db.execute(text("PRAGMA foreign_key_check"))) == []


def test_empty_subject_can_be_deleted_and_recreated_without_id_reuse(client):
    subject = client.post("/api/subjects", json={"name": "Тестовый"}).json()["id"]
    preview = client.get(f"/api/subjects/{subject}/deletion").json()
    assert preview["topic_count"] == preview["document_count"] == preview["card_count"] == 0
    assert client.delete(f"/api/subjects/{subject}").status_code == 200
    assert client.get("/api/subjects").json() == []
    new = client.post("/api/subjects", json={"name": "Тестовый"}).json()
    assert new["id"] != subject


def test_subject_confirmation_includes_empty_topics_and_allows_other_subject_changes(client):
    topic = make_topic(client)
    subject = subject_of(client, topic)
    preview = client.get(f"/api/subjects/{subject}/deletion").json()
    client.post("/api/topics", json={"name": "Новая пустая тема", "subject_id": subject})
    response = client.request(
        "DELETE", f"/api/subjects/{subject}", json={"revision": preview.get("revision", "missing")}
    )
    assert response.status_code == 409
    current = client.get(f"/api/subjects/{subject}/deletion").json()
    assert current["topic_count"] == 2
    make_topic(client, "Чужая тема")
    assert (
        client.request(
            "DELETE", f"/api/subjects/{subject}", json={"revision": current["revision"]}
        ).status_code
        == 200
    )


def test_subject_removal_is_atomic_even_when_some_topics_were_already_deleted(client, app):
    app.state.ai = FixtureAI()
    topic = make_topic(client)
    subject = subject_of(client, topic)
    ready_document(client, app, topic)
    client.delete(f"/api/topics/{topic}")
    second = client.post("/api/topics", json={"name": "Живая тема", "subject_id": subject}).json()[
        "id"
    ]
    ready_document(client, app, second)
    queued = client.post(
        f"/api/topics/{second}/documents", files={"file": ("another.pdf", pdf_bytes(2))}
    ).json()
    generation = client.post(
        "/api/generate", json={"topic_ids": [second], "count": 1, "allow_partial": True}
    ).json()
    assert client.delete(f"/api/subjects/{subject}").status_code == 200
    for job_id in (queued["job_id"], generation["id"]):
        assert client.get(f"/api/jobs/{job_id}").json()["status"] == "cancelled"
        run_job(app.state.db, app.state.ai, job_id)
        assert client.post(f"/api/jobs/{job_id}/retry").status_code == 409
    assert client.get("/api/topics").json() == []
    assert list((app.state.settings.data_dir / "files").iterdir()) == []


def test_subject_delete_during_model_request_cannot_restore_questions(client, app):
    app.state.ai = FixtureAI()
    topic = make_topic(client)
    subject = subject_of(client, topic)
    ready_document(client, app, topic)
    generate = app.state.ai.generate

    def deleting_generate(*args, **kwargs):
        result = generate(*args, **kwargs)
        assert client.delete(f"/api/subjects/{subject}").status_code == 200
        return result

    app.state.ai.generate = deleting_generate
    job = client.post("/api/generate", json={"topic_ids": [topic], "count": 1}).json()
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "cancelled"
    assert client.get("/api/cards").json() == []
    assert list((app.state.settings.data_dir / "files").iterdir()) == []


def test_subject_delete_requires_login_and_csrf(client):
    subject = client.post("/api/subjects", json={"name": "Тестовый"}).json()["id"]
    assert (
        client.delete(f"/api/subjects/{subject}", headers={"X-CSRF-Token": ""}).status_code == 403
    )
    client.cookies.clear()
    assert client.get(f"/api/subjects/{subject}/deletion").status_code == 401
    assert client.delete(f"/api/subjects/{subject}").status_code == 401


def test_last_youtube_reference_removes_cached_source_but_other_subject_keeps_it(
    client, app, monkeypatch
):
    from test_downsub import URL, successful, transport

    app.state.settings.youtube_provider = "downsub"
    transport(monkeypatch, successful)
    first = make_topic(client)
    second = make_topic(client, "Другой предмет")
    for topic in (first, second):
        document = client.post(
            f"/api/topics/{topic}/youtube", json={"url": URL, "language": "pl"}
        ).json()
        run_job(app.state.db, app.state.ai, document["job_id"])
    cache = app.state.settings.data_dir / "youtube-cache"
    import json

    def transcripts():
        return [file for file in cache.glob("*.json") if "segments" in json.loads(file.read_text())]

    assert len(transcripts()) == 1
    assert client.delete(f"/api/subjects/{subject_of(client, first)}").status_code == 200
    assert len(transcripts()) == 1
    remaining = client.get(f"/api/topics/{second}/documents").json()[0]
    assert (
        client.get(f"/api/documents/{remaining['id']}/download").json()["segments"][0]["text"]
        == "Obywatel to członek państwa."
    )
    assert client.delete(f"/api/subjects/{subject_of(client, second)}").status_code == 200
    assert transcripts() == []
    assert list((app.state.settings.data_dir / "files").iterdir()) == []


def test_cancelled_downsub_import_does_not_leave_an_orphan_cache(client, app, monkeypatch):
    import json
    import time
    from concurrent.futures import ThreadPoolExecutor

    from test_downsub import URL, successful, transport

    app.state.settings.youtube_provider = "downsub"
    topic = make_topic(client)
    subject = subject_of(client, topic)
    deletion = None
    with ThreadPoolExecutor(max_workers=1) as pool:

        def responder(request):
            nonlocal deletion
            response = successful(request)
            if request.method == "GET":
                deletion = pool.submit(client.delete, f"/api/subjects/{subject}")
                # Observe committed cancellation, then release the independent network call.
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with app.state.db.session() as db:
                        if db.get(Job, document["job_id"]).status == "cancelled":
                            break
                    time.sleep(0.01)
                else:
                    pytest.fail("Concurrent deletion never committed cancellation")
            return response

        transport(monkeypatch, responder)
        document = client.post(
            f"/api/topics/{topic}/youtube", json={"url": URL, "language": "pl"}
        ).json()
        run_job(app.state.db, app.state.ai, document["job_id"])
        assert deletion.result(timeout=5).status_code == 200
    assert client.get(f"/api/jobs/{document['job_id']}").json()["status"] == "cancelled"
    assert list((app.state.settings.data_dir / "files").iterdir()) == []
    cache = app.state.settings.data_dir / "youtube-cache"
    assert not any("segments" in json.loads(file.read_text()) for file in cache.glob("*.json"))


@pytest.mark.parametrize("keep_live_reference", [False, True])
def test_old_deleted_youtube_rows_without_metadata_do_not_leave_orphan_transcripts(
    client, app, monkeypatch, keep_live_reference
):
    import json

    from app.deletion import cleanup_deleted_files
    from test_downsub import URL, successful, transport

    app.state.settings.youtube_provider = "downsub"
    transport(monkeypatch, successful)
    topic = make_topic(client)
    document = client.post(
        f"/api/topics/{topic}/youtube", json={"url": URL, "language": "pl"}
    ).json()
    run_job(app.state.db, app.state.ai, document["job_id"])
    if keep_live_reference:
        other = make_topic(client, "Живой предмет")
        client.post(f"/api/topics/{other}/youtube", json={"url": URL, "language": "pl"})
    with app.state.db.session() as db:
        old = db.get(Document, document["id"])
        old.status, old.sha256, old.source_meta = "deleted", f"deleted:{old.id}", {}
        db.get(Topic, topic).deleted = True
    cleanup_deleted_files(app.state.db)
    cache = app.state.settings.data_dir / "youtube-cache"
    transcripts = [
        file for file in cache.glob("*.json") if "segments" in json.loads(file.read_text())
    ]
    assert len(transcripts) == int(keep_live_reference)
    with app.state.db.session() as db:
        assert not (
            app.state.settings.data_dir / "files" / db.get(Document, document["id"]).filename
        ).exists()

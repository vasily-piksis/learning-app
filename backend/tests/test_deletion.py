import pytest
from app.jobs import run_job
from app.models import Document, Job, SourcePage
from conftest import make_topic, pdf_bytes
from fakes import FixtureAI, ready_document
from sqlalchemy import func, select
from test_study import saved_cards


def test_delete_material_removes_dependent_questions_file_and_allows_reupload(client, app):
    topic, cards = saved_cards(client, app, count=1)
    document = client.get(f"/api/topics/{topic}/documents").json()[0]
    with app.state.db.session() as db:
        filename = db.get(Document, document["id"]).filename
    preview = client.get(f"/api/documents/{document['id']}/deletion").json()
    assert preview["card_count"] == 1
    response = client.delete(f"/api/documents/{document['id']}")
    assert response.status_code == 200, response.text
    assert client.get(f"/api/topics/{topic}/documents").json() == []
    assert client.get(f"/api/cards?topic_id={topic}").json() == []
    assert not (app.state.settings.data_dir / "files" / filename).exists()
    assert client.get(f"/api/documents/{document['id']}/download").status_code == 404
    assert (
        client.patch(
            f"/api/cards/{cards[0]['id']}",
            json={
                **{
                    k: cards[0][k]
                    for k in ("question", "answer", "options", "correct_index", "correct_indices")
                },
                "version": 1,
            },
        ).status_code
        == 404
    )
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(SourcePage.id))) == 0
    new = client.post(f"/api/topics/{topic}/documents", files={"file": ("fixed.pdf", pdf_bytes())})
    assert new.status_code == 200 and not new.json()["duplicate"]
    assert new.json()["id"] != document["id"]


def test_delete_topic_preserves_session_history_repeat_explain_and_other_topics(client, app):
    topic, _ = saved_cards(client, app, count=1)
    other = make_topic(client, "Другая тема")
    session = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    client.post(
        f"/api/study/{session['id']}/answer",
        json={
            "position": 0,
            "choice": session["card"]["options"].index("Дон"),
            "idempotency_key": "wrong",
        },
    )
    assert client.delete(f"/api/topics/{topic}").status_code == 200
    assert client.get(f"/api/topics/{topic}").status_code == 404
    assert [t["id"] for t in client.get("/api/topics").json()] == [other]
    assert client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).status_code == 404
    history = client.get(f"/api/study/{session['id']}").json()
    assert history["topic_names"] == ["Древний Египет"]
    assert history["active_topic_ids"] == []
    assert history["review"][0]["card"]["sources"][0]["available"] is False
    assert client.post(f"/api/study/{session['id']}/repeat").status_code == 200
    job = client.post(f"/api/study/{session['id']}/explain", json={"position": 0}).json()
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "succeeded"


@pytest.mark.parametrize("stage", ["queued", "running", "failed"])
def test_deletion_cancels_import_and_blocks_retry(client, app, stage):
    app.state.ai = FixtureAI()
    topic = make_topic(client)
    document = client.post(
        f"/api/topics/{topic}/documents", files={"file": ("bad.pdf", pdf_bytes())}
    ).json()
    with app.state.db.session() as db:
        db.get(Job, document["job_id"]).status = stage
    assert client.delete(f"/api/documents/{document['id']}").status_code == 200
    run_job(app.state.db, app.state.ai, document["job_id"])
    assert client.get(f"/api/jobs/{document['job_id']}").json()["status"] == "cancelled"
    assert client.post(f"/api/jobs/{document['job_id']}/retry").status_code == 409


def test_running_generation_cannot_resurrect_deleted_material(client, app):
    app.state.ai = FixtureAI()
    topic = make_topic(client)
    document = ready_document(client, app, topic)
    original = app.state.ai.generate

    def generate(*args, **kwargs):
        result = original(*args, **kwargs)
        assert client.delete(f"/api/documents/{document['id']}").status_code == 200
        return result

    app.state.ai.generate = generate
    job = client.post(
        "/api/generate", json={"topic_ids": [topic], "mode": "quiz", "count": 1}
    ).json()
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "cancelled"
    assert client.get(f"/api/cards?topic_id={topic}").json() == []


def test_running_import_does_not_recreate_pages_or_file(client, app):
    app.state.ai = FixtureAI()
    topic = make_topic(client)
    document = client.post(
        f"/api/topics/{topic}/documents", files={"file": ("bad.pdf", pdf_bytes(2))}
    ).json()
    original = app.state.ai.extract

    def extract(*args):
        result = original(*args)
        assert client.delete(f"/api/documents/{document['id']}").status_code == 200
        return result

    app.state.ai.extract = extract
    run_job(app.state.db, app.state.ai, document["job_id"])
    assert client.get(f"/api/jobs/{document['job_id']}").json()["status"] == "cancelled"
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(SourcePage.id))) == 0
    assert list((app.state.settings.data_dir / "files").iterdir()) == []


def test_delete_question_keeps_material_and_cancels_quiz_preparation(client, app):
    topic, cards = saved_cards(client, app, "flashcard", 1)
    job = client.post("/api/study/prepare-options", json={"topic_ids": [topic]}).json()
    assert client.delete(f"/api/cards/{cards[0]['id']}").status_code == 200
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "cancelled"
    assert client.get(f"/api/cards?topic_id={topic}").json() == []
    assert len(client.get(f"/api/topics/{topic}/documents").json()) == 1
    assert client.post("/api/cards/save", json={"card_ids": [cards[0]["id"]]}).status_code == 404


def test_deletion_requires_authentication_and_csrf(client, app):
    topic = make_topic(client)
    assert client.delete(f"/api/topics/{topic}", headers={"X-CSRF-Token": ""}).status_code == 403
    client.cookies.clear()
    assert client.delete(f"/api/topics/{topic}").status_code == 401


def test_deleted_sources_are_marked_unavailable_in_saved_explanations(client, app):
    topic, _ = saved_cards(client, app, count=1)
    session = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    client.post(
        f"/api/study/{session['id']}/answer",
        json={"position": 0, "choice": 1, "idempotency_key": "explain"},
    )
    job = client.post(f"/api/study/{session['id']}/explain", json={"position": 0}).json()
    run_job(app.state.db, app.state.ai, job["id"])
    client.delete(f"/api/topics/{topic}")
    explanation = client.get(f"/api/study/{session['id']}/explanations?position=0").json()[0]
    assert explanation["sources"][0]["available"] is False
    result = client.get(f"/api/jobs/{job['id']}").json()["result"]
    assert result["sources"][0]["available"] is False
    jobs = client.get(f"/api/study/{session['id']}/explanation-jobs?position=0").json()
    assert jobs[0]["result"]["sources"][0]["available"] is False


def test_running_youtube_cannot_write_transcript_after_deletion(client, app, monkeypatch):
    from app import youtube
    from test_youtube import URL, fetched

    topic = make_topic(client)
    document = client.post(
        f"/api/topics/{topic}/youtube", json={"url": URL, "language": "ru"}
    ).json()

    def fetch(*args):
        assert client.delete(f"/api/documents/{document['id']}").status_code == 200
        return fetched()

    monkeypatch.setattr(youtube, "fetch_transcript", fetch)
    run_job(app.state.db, app.state.ai, document["job_id"])
    assert client.get(f"/api/jobs/{document['job_id']}").json()["status"] == "cancelled"
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(SourcePage.id))) == 0
    assert list((app.state.settings.data_dir / "files").iterdir()) == []


def test_multi_source_deletion_removes_whole_question_only(client, app):
    from app.models import CardSource
    from sqlalchemy import text

    topic, cards = saved_cards(client, app, count=1)
    original = client.get(f"/api/topics/{topic}/documents").json()[0]
    other = ready_document(client, app, topic, pages=2)
    with app.state.db.session() as db:
        page = db.scalar(select(SourcePage).where(SourcePage.document_id == other["id"]))
        db.add(CardSource(card_id=cards[0]["id"], page_id=page.id))
    assert client.delete(f"/api/documents/{original['id']}").status_code == 200
    assert client.get(f"/api/cards?topic_id={topic}").json() == []
    assert [d["id"] for d in client.get(f"/api/topics/{topic}/documents").json()] == [other["id"]]
    with app.state.db.session() as db:
        assert list(db.execute(text("PRAGMA foreign_key_check"))) == []


def test_deletion_rejects_stale_confirmation_after_generation(client, app):
    app.state.ai = FixtureAI()
    topic = make_topic(client)
    document = ready_document(client, app, topic)
    preview = client.get(f"/api/documents/{document['id']}/deletion").json()
    assert preview["card_count"] == 0
    job = client.post(
        "/api/generate", json={"topic_ids": [topic], "mode": "quiz", "count": 1}
    ).json()
    run_job(app.state.db, app.state.ai, job["id"])
    response = client.request(
        "DELETE",
        f"/api/documents/{document['id']}",
        json={"revision": preview.get("revision", "missing")},
    )
    assert response.status_code == 409
    assert len(client.get(f"/api/cards?topic_id={topic}").json()) == 1
    current = client.get(f"/api/documents/{document['id']}/deletion").json()
    assert current["card_count"] == 1 and current["revision"] != preview["revision"]
    response = client.request(
        "DELETE", f"/api/documents/{document['id']}", json={"revision": current["revision"]}
    )
    assert response.status_code == 200


def test_deletion_rejects_stale_topic_confirmation_after_upload(client, app):
    topic = make_topic(client)
    preview = client.get(f"/api/topics/{topic}/deletion").json()
    ready_document(client, app, topic)
    response = client.request(
        "DELETE", f"/api/topics/{topic}", json={"revision": preview.get("revision", "missing")}
    )
    assert response.status_code == 409
    assert client.get(f"/api/topics/{topic}").status_code == 200


def test_cancelled_multi_topic_generation_stops_before_another_model_call(client, app):
    app.state.ai = FixtureAI()
    first = make_topic(client)
    second = make_topic(client, "Вторая тема")
    document = ready_document(client, app, first)
    ready_document(client, app, second)
    original = app.state.ai.generate
    calls = []

    def generate(topic_id, *args, **kwargs):
        calls.append(topic_id)
        result = original(topic_id, *args, **kwargs)
        if topic_id == first:
            assert client.delete(f"/api/documents/{document['id']}").status_code == 200
        return result

    app.state.ai.generate = generate
    job = client.post(
        "/api/generate", json={"topic_ids": [first, second], "mode": "quiz", "count": 2}
    ).json()
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "cancelled"
    assert calls == [first]
    assert client.get("/api/cards").json() == []


def test_restart_recovers_file_cleanup_after_deletion_unlink_failure(client, app, monkeypatch):
    from pathlib import Path

    from app.jobs import recover_jobs

    topic, _ = saved_cards(client, app, count=1)
    document = client.get(f"/api/topics/{topic}/documents").json()[0]
    with app.state.db.session() as db:
        file = app.state.settings.data_dir / "files" / db.get(Document, document["id"]).filename
    original = Path.unlink

    def unlink(path, *args, **kwargs):
        if path == file:
            raise PermissionError("test filesystem failure")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "unlink", unlink)
        response = client.delete(f"/api/documents/{document['id']}")
        assert response.status_code == 200
        assert response.json()["cleanup_pending"] is True
    assert client.get(f"/api/documents/{document['id']}/download").status_code == 404
    assert file.exists()
    recover_jobs(app.state.db)
    assert not file.exists()

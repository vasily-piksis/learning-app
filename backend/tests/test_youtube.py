import json
from types import SimpleNamespace

import pytest
from app.jobs import recover_jobs, run_job
from app.models import Document, Job, SourcePage
from conftest import make_topic
from fakes import FixtureAI
from sqlalchemy import func, select

VIDEO = "dQw4w9WgXcQ"
URL = f"https://www.youtube.com/watch?v={VIDEO}"


def test_youtube_url_validation_and_canonicalization():
    from app.youtube import video_url

    for url in [
        URL,
        f"https://youtu.be/{VIDEO}?t=30",
        f"https://m.youtube.com/watch?v={VIDEO}&t=3",
        f"https://www.youtube.com/shorts/{VIDEO}",
    ]:
        assert video_url(url) == (VIDEO, URL)
    for url in [
        "http://localhost/watch?v=" + VIDEO,
        "https://youtube.com.evil.test/watch?v=" + VIDEO,
        "https://evil.test@youtube.com/watch?v=" + VIDEO,
        "https://youtube.com:443/watch?v=" + VIDEO,
        "https://youtube.com/watch?v=bad",
        "https://youtube.com/playlist?list=123",
        URL + "&v=aaaaaaaaaaa",
    ]:
        with pytest.raises(ValueError):
            video_url(url)


def fetched():
    return SimpleNamespace(
        language_code="ru",
        is_generated=True,
        snippets=[
            SimpleNamespace(text="Нил давал воду и плодородный ил.", start=5.5, duration=3),
            SimpleNamespace(text="Фараон правил Египтом.", start=65, duration=4),
        ],
    )


def test_youtube_import_persists_timestamps_and_scopes_generation(client, app, monkeypatch):
    from app import youtube

    calls = []

    def fetch(video, language):
        calls.append((video, language))
        return fetched()

    monkeypatch.setattr(youtube, "fetch_transcript", fetch)
    topic = make_topic(client)
    route = f"/api/topics/{topic}/youtube"
    first = client.post(route, json={"url": URL, "language": "ru"})
    assert first.status_code == 200, first.text
    document = first.json()
    assert document["status"] == "queued"
    duplicate = client.post(
        route, json={"url": f"https://youtu.be/{VIDEO}", "language": "ru"}
    ).json()
    assert duplicate["id"] == document["id"]
    assert calls == []
    run_job(app.state.db, app.state.ai, document["job_id"])
    run_job(app.state.db, app.state.ai, document["job_id"])
    assert calls == [(VIDEO, "ru")]
    listed = client.get(f"/api/topics/{topic}/documents").json()[0]
    assert listed["status"] == "ready"
    assert listed["source_url"] == URL
    assert listed["language"] == "ru"
    assert listed["is_generated"] is True
    transcript = json.loads(client.get(f"/api/documents/{document['id']}/download").content)
    assert transcript["segments"][0]["start"] == 5.5
    assert transcript["segments"][1]["text"] == "Фараон правил Египтом."
    with app.state.db.session() as db:
        pages = list(db.scalars(select(SourcePage).order_by(SourcePage.number)))
        assert len(pages) == 2 and pages[0].start_seconds == 5.5
    app.state.ai = FixtureAI()
    another = make_topic(client, "Рим")
    other = client.post(f"/api/topics/{another}/youtube", json={"url": URL}).json()
    assert other["id"] != document["id"]
    job = client.post(
        "/api/generate", json={"topic_ids": [topic], "mode": "quiz", "count": 1}
    ).json()
    run_job(app.state.db, app.state.ai, job["id"])
    assert {s["document_id"] for s in app.state.ai.inputs[0][1]} == {document["id"]}
    card = client.get(f"/api/cards?job_id={job['id']}").json()[0]
    assert card["sources"][0]["url"] == URL + "&t=5"
    assert card["sources"][0]["start_seconds"] == 5.5
    client.post("/api/cards/save", json={"card_ids": [card["id"]]})
    session = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    assert session["card"]["sources"][0]["url"] == URL + "&t=5"
    client.post(
        f"/api/study/{session['id']}/answer",
        json={"position": 0, "choice": 0, "idempotency_key": "youtube-answer"},
    )
    explanation = client.post(f"/api/study/{session['id']}/explain", json={"position": 0}).json()
    run_job(app.state.db, app.state.ai, explanation["id"])
    result = client.get(f"/api/study/{session['id']}/explanations?position=0").json()[0]
    assert result["sources"][0]["url"] == URL + "&t=5"
    assert "text" not in result["sources"][0]
    from app.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(app.state.settings, worker=False)) as reopened:
        reopened.cookies.update(client.cookies)
        assert (
            reopened.get(f"/api/study/{session['id']}").json()["review"][0]["card"]["sources"][0][
                "url"
            ]
            == URL + "&t=5"
        )
        assert reopened.get(f"/api/documents/{document['id']}/download").status_code == 200


def test_youtube_failure_retry_and_recovery(client, app, monkeypatch):
    from app import youtube

    def blocked(*args):
        raise ValueError("YouTube не разрешил получить субтитры")

    monkeypatch.setattr(youtube, "fetch_transcript", blocked)
    topic = make_topic(client)
    document = client.post(f"/api/topics/{topic}/youtube", json={"url": URL}).json()
    run_job(app.state.db, app.state.ai, document["job_id"])
    listed = client.get(f"/api/topics/{topic}/documents").json()[0]
    assert listed["status"] == "failed" and "YouTube" in listed["error"]
    assert (
        client.post(
            "/api/generate", json={"topic_ids": [topic], "mode": "quiz", "count": 1}
        ).status_code
        == 409
    )
    monkeypatch.setattr(youtube, "fetch_transcript", lambda *args: fetched())
    assert client.post(f"/api/jobs/{document['job_id']}/retry").status_code == 200
    assert client.get(f"/api/topics/{topic}/documents").json()[0]["status"] == "queued"
    run_job(app.state.db, app.state.ai, document["job_id"])
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(SourcePage.id))) == 2
        db.get(Document, document["id"]).status = "processing"
        db.get(Job, document["job_id"]).status = "running"
    recover_jobs(app.state.db)
    assert client.get(f"/api/topics/{topic}/documents").json()[0]["status"] == "failed"


def test_youtube_invalid_inputs_save_nothing(client, app):
    topic = make_topic(client)
    route = f"/api/topics/{topic}/youtube"
    for body in [
        {"url": "https://127.0.0.1"},
        {"url": URL, "language": ""},
        {"url": URL, "language": "../../x"},
    ]:
        assert client.post(route, json=body).status_code == 422
    assert client.get(f"/api/topics/{topic}/documents").json() == []


def test_transcript_limits_and_invalid_timing():
    from app.youtube import normalize_transcript

    for snippets in [
        [],
        [SimpleNamespace(text="x" * 100001, start=0, duration=1)],
        [SimpleNamespace(text="x", start=float("nan"), duration=1)],
        [SimpleNamespace(text="x", start=-1, duration=1)],
    ]:
        with pytest.raises(ValueError):
            normalize_transcript(
                SimpleNamespace(language_code="ru", is_generated=False, snippets=snippets)
            )


def test_cached_transcript_recovery_does_not_fetch_again(client, app, monkeypatch):
    from app import youtube

    def must_not_fetch(*args):
        raise AssertionError("Committed transcript cache must survive a restart")

    monkeypatch.setattr(youtube, "fetch_transcript", must_not_fetch)
    topic = make_topic(client)
    document = client.post(f"/api/topics/{topic}/youtube", json={"url": URL}).json()
    with app.state.db.session() as db:
        value = db.get(Document, document["id"])
        saved = youtube.normalize_transcript(fetched())
        saved.update(video_id=VIDEO, url=URL)
        (app.state.settings.data_dir / "files" / value.filename).write_text(json.dumps(saved))
        value.status = "processing"
        db.get(Job, document["job_id"]).status = "running"
    recover_jobs(app.state.db)
    client.post(f"/api/jobs/{document['job_id']}/retry")
    run_job(app.state.db, app.state.ai, document["job_id"])
    assert client.get(f"/api/topics/{topic}/documents").json()[0]["status"] == "ready"
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(SourcePage.id))) == 2

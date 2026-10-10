from app.models import Document, Job, SourcePage
from conftest import make_topic, pdf_bytes
from fakes import FixtureAI, ready_document
from sqlalchemy import func, select


def test_generate_scopes_topics_and_sources(client, app):
    from app.jobs import run_job

    app.state.ai = FixtureAI()
    first, second = make_topic(client), make_topic(client, "Рим")
    d1 = ready_document(client, app, first)
    d2 = ready_document(client, app, second)
    invalid = client.post(
        "/api/generate",
        json={"topic_ids": [first], "document_ids": [d2["id"]], "mode": "flashcard", "count": 3},
    )
    assert invalid.status_code == 422
    assert (
        client.post("/api/generate", json={"topic_ids": [], "mode": "quiz", "count": 1}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/generate", json={"topic_ids": [first, second], "mode": "quiz", "count": 1}
        ).status_code
        == 422
    )
    result = client.post(
        "/api/generate", json={"topic_ids": [first, second], "mode": "quiz", "count": 3}
    )
    assert result.status_code == 200, result.text
    run_job(app.state.db, app.state.ai, result.json()["id"])
    job = client.get(f"/api/jobs/{result.json()['id']}").json()
    assert job["status"] == "succeeded"
    cards = client.get(f"/api/cards?job_id={job['id']}").json()
    assert len(cards) == 3
    assert {c["topic_id"] for c in cards} == {first, second}
    for topic, sources in app.state.ai.inputs:
        assert {s["document_id"] for s in sources} == {d1["id"] if topic == first else d2["id"]}
    assert (
        client.post("/api/cards/save", json={"card_ids": [c["id"] for c in cards]}).status_code
        == 200
    )
    assert len(client.get(f"/api/cards?topic_id={first}&status=saved").json()) == 2


def test_invalid_citations_fail_atomically(client, app):
    from app.jobs import run_job

    app.state.ai = FixtureAI()
    topic = make_topic(client)
    ready_document(client, app, topic)
    app.state.ai.invalid_source = True
    job = client.post(
        "/api/generate", json={"topic_ids": [topic], "mode": "flashcard", "count": 2}
    ).json()
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"
    assert client.get(f"/api/cards?job_id={job['id']}").json() == []
    app.state.ai.invalid_source = False
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 200
    run_job(app.state.db, app.state.ai, job["id"])
    run_job(app.state.db, app.state.ai, job["id"])
    assert len(client.get(f"/api/cards?job_id={job['id']}").json()) == 2


def test_partial_sources_and_text_limit(client, app):
    app.state.ai = FixtureAI()
    topic = make_topic(client)
    ready_document(client, app, topic)
    client.post(f"/api/topics/{topic}/documents", files={"file": ("new.pdf", pdf_bytes(2))})
    body = {"topic_ids": [topic], "mode": "flashcard", "count": 2}
    assert client.post("/api/generate", json=body).status_code == 409
    assert client.post("/api/generate", json={**body, "allow_partial": True}).status_code == 200
    with app.state.db.session() as db:
        page = db.scalar(select(SourcePage))
        page.text = "x" * 100001
    assert client.post("/api/generate", json={**body, "allow_partial": True}).status_code == 422


def test_cached_pages_and_restart_recovery(client, app):
    from app.jobs import recover_jobs, run_job

    app.state.ai = FixtureAI()
    topic = make_topic(client)
    document = client.post(
        f"/api/topics/{topic}/documents", files={"file": ("lesson.pdf", pdf_bytes(2))}
    ).json()
    app.state.ai.fail_page = 2
    run_job(app.state.db, app.state.ai, document["job_id"])
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(SourcePage.id))) == 1
        assert db.get(Document, document["id"]).status == "failed"
    app.state.ai.fail_page = None
    client.post(f"/api/jobs/{document['job_id']}/retry")
    run_job(app.state.db, app.state.ai, document["job_id"])
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(SourcePage.id))) == 2
        assert db.get(Document, document["id"]).status == "ready"
        interrupted = Job(user_id=1, kind="generate", status="running", payload={})
        waiting = Job(user_id=1, kind="generate", payload={})
        db.add_all([interrupted, waiting])
        db.flush()
        running_id, queued_id = interrupted.id, waiting.id
    recover_jobs(app.state.db)
    with app.state.db.session() as db:
        assert db.get(Job, running_id).status == "failed"
        assert db.get(Job, queued_id).status == "queued"


def test_blank_page_is_cached_and_excluded_from_generation(client, app):
    from types import SimpleNamespace

    from app.jobs import run_job

    class BlankAI(FixtureAI):
        def extract(self, path, mime, page_number, local_text):
            if page_number == 2:
                return SimpleNamespace(page=2, text="", warnings=["Пустая страница"], is_blank=True)
            return super().extract(path, mime, page_number, local_text)

    app.state.ai = BlankAI()
    topic = make_topic(client)
    import pymupdf

    pdf = pymupdf.open()
    for number in range(1, 4):
        page = pdf.new_page()
        if number != 2:
            page.insert_text((50, 50), "Egypt is on the Nile.")
    document = client.post(
        f"/api/topics/{topic}/documents", files={"file": ("blank-page.pdf", pdf.tobytes())}
    ).json()
    run_job(app.state.db, app.state.ai, document["job_id"])
    listed = client.get(f"/api/topics/{topic}/documents").json()[0]
    assert listed["status"] == "ready"
    assert listed["warnings"] == [{"page": 2, "messages": ["Пустая страница"]}]
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(SourcePage.id))) == 3
    job = client.post(
        "/api/generate", json={"topic_ids": [topic], "mode": "flashcard", "count": 2}
    ).json()
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "succeeded"
    assert [s["page"] for s in app.state.ai.inputs[0][1]] == [1, 3]
    assert client.get(f"/api/documents/{document['id']}/download").status_code == 200


def test_unreadable_empty_page_does_not_become_ready(client, app):
    from types import SimpleNamespace

    class UnreadableAI(FixtureAI):
        def extract(self, *args):
            return SimpleNamespace(page=1, text="", warnings=["Неразборчиво"], is_blank=False)

    app.state.ai = UnreadableAI()
    topic = make_topic(client)
    ready_document(client, app, topic)
    assert client.get(f"/api/topics/{topic}/documents").json()[0]["status"] == "failed"
    with app.state.db.session() as db:
        assert db.scalar(select(func.count(SourcePage.id))) == 0

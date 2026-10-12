import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from app.jobs import run_job
from conftest import make_topic
from pydantic import SecretStr
from requests import Response, Session

VIDEO = "6crPrHg2MZc"
URL = f"https://www.youtube.com/watch?v={VIDEO}"


def enable(settings):
    settings.oxylabs_username = SecretStr("fixture-user")
    settings.oxylabs_password = SecretStr("fixture-password")


def captions(language="pl"):
    return {
        "auto_generated": {
            language: {
                "events": [
                    {"tStartMs": 0, "dDurationMs": 1000},
                    {
                        "tStartMs": 5894,
                        "dDurationMs": 2020,
                        "segs": [{"utf8": "Obywatel"}, {"utf8": " to członek państwa."}],
                    },
                ]
            }
        }
    }


def test_oxylabs_original_import_and_durable_cache_across_topics(client, app, monkeypatch):
    from app import oxylabs

    enable(app.state.settings)
    calls = []

    def content(settings, payload):
        calls.append(payload)
        if payload["source"] == "youtube_metadata":
            return {
                "parse_status_code": 12000,
                "results": {
                    "video_id": VIDEO,
                    "generated_subtitle_languages": ["pl"],
                    "user_subtitle_languages": ["en"],
                },
            }
        assert payload["context"] == [{"key": "language_code", "value": "pl"}]
        return captions()

    monkeypatch.setattr(oxylabs, "request_content", content)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(lambda _: oxylabs.list_tracks(app.state.settings, VIDEO), range(4)))
    assert len(calls) == 1
    topic = make_topic(client)
    assert (
        client.post("/api/youtube/resolve", json={"url": URL}).json()["selected_language"] == "pl"
    )
    document = client.post(f"/api/topics/{topic}/youtube", json={"url": URL}).json()
    run_job(app.state.db, app.state.ai, document["job_id"])
    saved = client.get(f"/api/topics/{topic}/documents").json()[0]
    assert saved["status"] == "ready" and saved["language"] == "pl"
    transcript = json.loads(client.get(f"/api/documents/{document['id']}/download").content)
    assert transcript["segments"] == [
        {
            "text": "Obywatel to członek państwa.",
            "start": 5.894,
            "duration": 2.02,
        }
    ]
    assert transcript["is_generated"] is True
    other_topic = make_topic(client, "Inna lekcja")
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(lambda _: oxylabs.list_tracks(app.state.settings, VIDEO), range(4)))
    other = client.post(f"/api/topics/{other_topic}/youtube", json={"url": URL}).json()
    run_job(app.state.db, app.state.ai, other["job_id"])
    assert client.get(f"/api/topics/{other_topic}/documents").json()[0]["status"] == "ready"
    duplicate = client.post(f"/api/topics/{topic}/youtube", json={"url": URL, "language": "pl"})
    assert duplicate.json()["duplicate"] is True
    assert len(calls) == 2
    for path in (app.state.settings.data_dir / "youtube-cache").iterdir():
        assert "fixture-password" not in path.read_text()
    assert "fixture-password" not in repr(app.state.settings)


def test_manual_caption_track_and_language_mismatch_are_not_translated(app, monkeypatch):
    from app import oxylabs

    enable(app.state.settings)
    monkeypatch.setattr(
        oxylabs,
        "request_content",
        lambda *_: {
            "uploader_provided": {
                "lt": {
                    "events": [
                        {
                            "tStartMs": 2000,
                            "dDurationMs": 1000,
                            "segs": [{"utf8": "Pilietis."}],
                        }
                    ]
                }
            }
        },
    )
    saved = oxylabs.fetch_transcript(app.state.settings, VIDEO, "lt")
    assert saved["language"] == "lt" and saved["is_generated"] is False
    assert saved["segments"][0]["text"] == "Pilietis."
    with pytest.raises(ValueError, match="Субтитры на выбранном языке недоступны"):
        oxylabs.fetch_transcript(app.state.settings, VIDEO, "pl")


@pytest.mark.parametrize("status", [401, 403, 402, 429, 500, 302])
def test_transport_errors_do_not_leak_secrets_or_retry(app, monkeypatch, status):
    from app import oxylabs

    enable(app.state.settings)
    calls = []

    def post(session, url, **kwargs):
        calls.append((url, kwargs))
        response = Response()
        response.status_code = status
        response.raw = BytesIO(b'{"error":"fixture-password"}')
        return response

    monkeypatch.setattr(Session, "post", post)
    with pytest.raises(ValueError) as error:
        oxylabs.request_content(app.state.settings, {"source": "youtube_metadata", "query": VIDEO})
    assert "fixture-password" not in str(error.value)
    assert len(calls) == 1
    assert calls[0][0] == "https://realtime.oxylabs.io/v1/queries"
    assert calls[0][1]["allow_redirects"] is False
    assert calls[0][1]["timeout"] == (10, 180)


def test_transport_bounds_and_validates_the_result(app, monkeypatch):
    from app import oxylabs

    enable(app.state.settings)
    bodies = [
        b"x" * (8 * 1024 * 1024 + 1),
        b"not-json",
        b'{"results":[]}',
        b'{"results":[{"status_code":500,"content":{"error":"fixture-password"}}]}',
        json.dumps({"results": [{"status_code": 200, "content": captions()}]}).encode(),
    ]

    def post(*args, **kwargs):
        response = Response()
        response.status_code = 200
        response.raw = BytesIO(bodies.pop(0))
        return response

    monkeypatch.setattr(Session, "post", post)
    for _ in range(4):
        with pytest.raises(ValueError) as error:
            oxylabs.request_content(
                app.state.settings, {"source": "youtube_subtitles", "query": VIDEO}
            )
        assert "fixture-password" not in str(error.value)
    assert (
        oxylabs.request_content(app.state.settings, {"source": "youtube_subtitles", "query": VIDEO})
        == captions()
    )


def test_empty_and_invalid_caption_events_are_not_cached(app, monkeypatch):
    from app import oxylabs

    enable(app.state.settings)
    for content in [
        {},
        {"auto_generated": {"pl": {"events": []}}},
        {
            "auto_generated": {
                "pl": {"events": [{"tStartMs": -1, "dDurationMs": 1, "segs": [{"utf8": "x"}]}]}
            }
        },
    ]:
        monkeypatch.setattr(oxylabs, "request_content", lambda *_, content=content: content)
        with pytest.raises(ValueError):
            oxylabs.fetch_transcript(app.state.settings, VIDEO, "pl")
    assert not list((app.state.settings.data_dir / "youtube-cache").glob("*.json"))


def test_redirect_body_is_bounded_before_requests_prepares_next_hop(app, monkeypatch):
    from app import oxylabs
    from requests.adapters import BaseAdapter

    enable(app.state.settings)

    class Body(BytesIO):
        consumed = 0

        def read(self, size=-1):
            value = super().read(size)
            self.consumed += len(value)
            return value

    body = Body(b"x" * (9 * 1024 * 1024))

    class RedirectAdapter(BaseAdapter):
        def send(self, request, **kwargs):
            response = Response()
            response.request, response.url = request, request.url
            response.status_code = 302
            response.headers["Location"] = "https://other.example/redirect"
            response.raw = body
            return response

        def close(self):
            pass

    def session():
        value = Session()
        value.mount("https://", RedirectAdapter())
        return value

    monkeypatch.setattr(oxylabs, "Session", session)
    with pytest.raises(ValueError, match="Ответ Oxylabs слишком большой"):
        oxylabs.request_content(app.state.settings, {"source": "youtube_metadata", "query": VIDEO})
    assert body.consumed <= 8 * 1024 * 1024 + 65536
    assert body.closed

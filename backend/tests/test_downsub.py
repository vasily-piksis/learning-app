import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from app.config import Settings
from app.jobs import run_job
from conftest import make_topic
from requests import Response, Session
from requests.adapters import BaseAdapter

VIDEO = "6crPrHg2MZc"
URL = f"https://www.youtube.com/watch?v={VIDEO}"
SRT = "1\n00:00:05,894 --> 00:00:07,914\nObywatel to członek państwa.\n\n2\n00:01:05,000 --> 00:01:09,000\nDrugi fakt.\n"


def metadata():
    return {
        "state": 2,
        "url": URL,
        "title": "Lekcja",
        "subtitles": [
            {
                "name": "Polish (auto-generated)",
                "language": "pl",
                "type": "youtube",
                "code": "pl_auto",
                "url": "opaque-original",
            },
            {
                "name": "English",
                "language": "en",
                "type": "youtube",
                "code": "en",
                "url": "opaque-manual",
            },
        ],
        "subtitlesAutoTrans": [
            {
                "name": "Russian",
                "language": "ru",
                "type": "youtube_auto",
                "code": "ru",
                "url": "must-not-download",
            },
        ],
    }


def transport(monkeypatch, responder):
    """Exercise real Requests preparation, response hooks and our wire contract."""
    calls = []

    class Adapter(BaseAdapter):
        def send(self, request, **kwargs):
            calls.append(request)
            status, body, headers = responder(request)
            response = Response()
            response.request, response.url = request, request.url
            response.status_code, response.headers = status, headers
            response.raw = BytesIO(body)
            return response

        def close(self):
            pass

    def session():
        value = Session()
        value.mount("https://", Adapter())
        return value

    from app import downsub

    monkeypatch.setattr(downsub, "Session", session)
    return calls


def successful(request):
    if request.method == "POST":
        assert request.url == "https://get.downsub.com/"
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
        payload = json.loads(request.body)
        assert payload["url"] == URL and isinstance(payload["data"], str)
        return 200, json.dumps(metadata()).encode(), {"Content-Type": "application/json"}
    assert request.url.startswith("https://subtitle.downsub.com/srt/opaque-original/")
    return 200, SRT.encode(), {"Content-Type": "text/plain; charset=utf-8"}


def test_original_language_timecodes_and_cache_survive_reopen_and_other_topics(
    client, app, monkeypatch
):
    from app import downsub

    app.state.settings.youtube_provider = "downsub"
    calls = transport(monkeypatch, successful)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(lambda _: downsub.list_tracks(app.state.settings, VIDEO), range(4)))
    topic = make_topic(client)
    resolved = client.post("/api/youtube/resolve", json={"url": URL})
    assert resolved.status_code == 200 and resolved.json()["selected_language"] == "pl"
    assert {track["language"] for track in resolved.json()["tracks"]} == {"pl", "en"}
    document = client.post(f"/api/topics/{topic}/youtube", json={"url": URL}).json()
    run_job(app.state.db, app.state.ai, document["job_id"])
    listed = client.get(f"/api/topics/{topic}/documents").json()[0]
    assert listed["status"] == "ready" and listed["language"] == "pl"
    saved = client.get(f"/api/documents/{document['id']}/download").json()
    assert saved["language"] == "pl" and saved["is_generated"] is True
    assert saved["segments"][0] == {
        "text": "Obywatel to członek państwa.",
        "start": 5.894,
        "duration": 2.02,
    }
    assert saved["segments"][1]["start"] == 65
    assert all(
        "Authorization" not in request.headers and "Cookie" not in request.headers
        for request in calls
    )
    assert len(calls) == 2
    reopened_settings = Settings(
        data_dir=app.state.settings.data_dir, youtube_provider="downsub", openai_api_key=""
    )
    assert downsub.fetch_transcript(reopened_settings, VIDEO, "pl")["segments"] == saved["segments"]
    other_topic = make_topic(client, "Druga lekcja")
    other = client.post(f"/api/topics/{other_topic}/youtube", json={"url": URL}).json()
    run_job(app.state.db, app.state.ai, other["job_id"])
    assert client.get(f"/api/topics/{other_topic}/documents").json()[0]["status"] == "ready"
    assert (
        client.post(f"/api/topics/{topic}/youtube", json={"url": URL, "language": "pl"}).json()[
            "duplicate"
        ]
        is True
    )
    assert len(calls) == 2


def test_legacy_oxylabs_cache_is_reused_without_network(app, monkeypatch):
    from app import downsub

    root = app.state.settings.data_dir / "youtube-cache"
    root.mkdir()
    values = {
        f"oxylabs:tracks:{VIDEO}": {
            "tracks": [{"language": "pl", "name": "pl", "is_generated": True}]
        },
        f"oxylabs:transcript:{VIDEO}:pl": {
            "language": "pl",
            "is_generated": True,
            "segments": [{"text": "Pilietis.", "start": 5.5, "duration": 3}],
        },
    }
    for key, value in values.items():
        (root / (hashlib.sha256(key.encode()).hexdigest() + ".json")).write_text(json.dumps(value))
    calls = transport(monkeypatch, lambda _: pytest.fail("Retained cache must avoid network"))
    assert downsub.list_tracks(app.state.settings, VIDEO)[0]["language"] == "pl"
    assert downsub.fetch_transcript(app.state.settings, VIDEO, "pl")["segments"][0]["start"] == 5.5
    assert calls == []


def test_unavailable_original_language_does_not_fetch_translation(app, monkeypatch):
    from app import downsub

    calls = transport(monkeypatch, successful)
    with pytest.raises(ValueError, match="Субтитры на выбранном языке недоступны"):
        downsub.fetch_transcript(app.state.settings, VIDEO, "ru")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "srt",
    [
        "",
        "<html>challenge</html>",
        "1\n00:00:10,000 --> 00:00:09,000\nx\n",
        "1\n24:00:00,000 --> 24:00:01,000\nx\n",
        "1\n00:00:00,000 --> 00:00:01,000\n" + "x" * 100001,
    ],
)
def test_malformed_or_excessive_srt_is_rejected(srt):
    from app.downsub import parse_srt

    with pytest.raises(ValueError):
        parse_srt(srt, "pl", True)


def test_multiline_srt_preserves_polish_and_exact_timing():
    from app.downsub import parse_srt

    result = parse_srt(
        "\ufeff1\r\n01:02:03,456 --> 01:02:05,001\r\nPierwsza linia.\r\nDruga linia.\r\n",
        "pl",
        False,
    )
    assert result["language"] == "pl" and result["is_generated"] is False
    assert result["segments"] == [
        {"text": "Pierwsza linia.\nDruga linia.", "start": 3723.456, "duration": 1.545}
    ]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 302])
def test_remote_failures_are_sanitized_not_retried_or_cached(app, monkeypatch, status):
    from app import downsub

    calls = transport(
        monkeypatch,
        lambda _: (
            status,
            b'{"error":"opaque-sensitive-url"}',
            {"Location": "http://127.0.0.1/private"},
        ),
    )
    with pytest.raises(ValueError) as error:
        downsub.list_tracks(app.state.settings, VIDEO)
    assert "opaque-sensitive-url" not in str(error.value)
    assert len(calls) == 1
    assert not list((app.state.settings.data_dir / "youtube-cache").glob("*.json"))


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_downsub_retries_transient_http(app, monkeypatch, retry_waits, status):
    from app import downsub

    count = [0]

    def responder(request):
        count[0] += 1
        return (status, b"temporary", {}) if count[0] < 3 else successful(request)

    calls = transport(monkeypatch, responder)
    assert downsub.list_tracks(app.state.settings, VIDEO)[0]["language"] == "pl"
    assert len(calls) == 3 and retry_waits == [1, 2]
    assert len({request.body for request in calls}) == 1
    assert downsub.list_tracks(app.state.settings, VIDEO)[0]["language"] == "pl"
    assert len(calls) == 3


@pytest.mark.parametrize("status", [429, 503])
def test_downsub_retry_exhaustion_is_bounded_and_not_cached(app, monkeypatch, retry_waits, status):
    from app import downsub

    calls = transport(monkeypatch, lambda _: (status, b"sensitive-provider-detail", {}))
    with pytest.raises(ValueError) as error:
        downsub.list_tracks(app.state.settings, VIDEO)
    assert len(calls) == 3 and retry_waits == [1, 2]
    assert "sensitive-provider-detail" not in str(error.value)
    assert not list((app.state.settings.data_dir / "youtube-cache").glob("*.json"))


@pytest.mark.parametrize("failure", ["connection", "timeout", "ssl"])
def test_downsub_classifies_network_failure(app, monkeypatch, retry_waits, failure):
    from app import downsub
    from requests.exceptions import ConnectionError, ReadTimeout, SSLError

    errors = {"connection": ConnectionError, "timeout": ReadTimeout, "ssl": SSLError}
    count = [0]

    def responder(request):
        count[0] += 1
        if count[0] < 3:
            raise errors[failure]("sensitive-provider-detail")
        return successful(request)

    calls = transport(monkeypatch, responder)
    if failure == "ssl":
        with pytest.raises(ValueError):
            downsub.list_tracks(app.state.settings, VIDEO)
        assert len(calls) == 1 and retry_waits == []
    else:
        assert downsub.list_tracks(app.state.settings, VIDEO)[0]["language"] == "pl"
        assert len(calls) == 3 and retry_waits == [1, 2]


@pytest.mark.parametrize(
    "header,delay,count",
    [
        ("5", [5], 2),
        ("Tue, 13 Oct 2026 00:00:05 GMT", [5], 2),
        ("120", [], 1),
        ("NaN", [1], 2),
        ("garbage", [1], 2),
    ],
)
def test_downsub_honors_retry_after(app, monkeypatch, retry_waits, header, delay, count):
    import time

    from app import downsub

    monkeypatch.setattr(time, "time", lambda: 1791849600)
    attempt = [0]

    def responder(request):
        attempt[0] += 1
        return (429, b"busy", {"Retry-After": header}) if attempt[0] == 1 else successful(request)

    calls = transport(monkeypatch, responder)
    if count == 1:
        with pytest.raises(ValueError):
            downsub.list_tracks(app.state.settings, VIDEO)
    else:
        assert downsub.list_tracks(app.state.settings, VIDEO)[0]["language"] == "pl"
    assert len(calls) == count and retry_waits == delay


def test_successful_download_after_retry_is_cached_with_original_times(
    app, monkeypatch, retry_waits
):
    from app import downsub

    downloads = [0]

    def responder(request):
        if request.method == "GET":
            downloads[0] += 1
            if downloads[0] < 3:
                return (503, b"busy", {})
        return successful(request)

    calls = transport(monkeypatch, responder)
    first = downsub.fetch_transcript(app.state.settings, VIDEO, "pl")
    assert first["language"] == "pl" and first["segments"][0]["start"] == 5.894
    assert len(calls) == 4 and retry_waits == [1, 2]
    assert downsub.fetch_transcript(app.state.settings, VIDEO, "pl") == first
    assert len(calls) == 4


def test_downsub_honors_millisecond_cooldown(app, monkeypatch, retry_waits):
    from app import downsub

    attempt = [0]

    def responder(request):
        attempt[0] += 1
        return (
            (429, b"busy", {"retry-after-ms": "5000"}) if attempt[0] == 1 else successful(request)
        )

    calls = transport(monkeypatch, responder)
    assert downsub.list_tracks(app.state.settings, VIDEO)[0]["language"] == "pl"
    assert len(calls) == 2 and retry_waits == [5]


def test_oversized_redirect_body_is_stopped_by_response_hook(app, monkeypatch):
    from app import downsub

    calls = transport(
        monkeypatch,
        lambda _: (302, b"x" * (9 * 1024 * 1024), {"Location": "http://127.0.0.1/private"}),
    )
    with pytest.raises(ValueError, match="Ответ DownSub слишком большой"):
        downsub.list_tracks(app.state.settings, VIDEO)
    assert len(calls) == 1


def test_provider_encoding_matches_independent_cryptojs_format(monkeypatch):
    from app import downsub

    monkeypatch.setattr(downsub.os, "urandom", lambda _: bytes.fromhex("0001020304050607"))
    assert (
        downsub.encode_parameter(VIDEO, "fixture")
        == "eyJjdCI6IjBQejdodk1yYUYrRnlYbm5PUG5FS1E9PSIsIml2IjoiN2MwNDYxOGI1OTg2YWIyOTYyYWU2Njk3OWJmNDQ4ZmEiLCJzIjoiMDAwMTAyMDMwNDA1MDYwNyJ9"
    )


def test_invalid_input_and_mismatched_metadata_never_import(app, monkeypatch):
    from app import downsub

    calls = transport(monkeypatch, successful)
    with pytest.raises(ValueError):
        downsub.list_tracks(app.state.settings, "../../evil")
    assert calls == []
    wrong = metadata()
    wrong["url"] = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    calls = transport(monkeypatch, lambda _: (200, json.dumps(wrong).encode(), {}))
    with pytest.raises(ValueError):
        downsub.list_tracks(app.state.settings, VIDEO)
    assert len(calls) == 1


def test_manual_caption_is_preferred_and_uses_its_own_language(app, monkeypatch):
    from app import downsub

    value = metadata()
    value["subtitles"] = [
        {
            "name": "Lithuanian",
            "language": "lt",
            "type": "youtube",
            "code": "lt",
            "url": "manual-lt",
        },
        {
            "name": "Lithuanian (auto-generated)",
            "language": "lt",
            "type": "youtube",
            "code": "lt_auto",
            "url": "automatic-lt",
        },
    ]

    def responder(request):
        if request.method == "POST":
            return 200, json.dumps(value).encode(), {}
        assert "/manual-lt/" in request.url
        return 200, b"1\n00:00:02,000 --> 00:00:04,500\nPilietis.\n", {}

    transport(monkeypatch, responder)
    saved = downsub.fetch_transcript(app.state.settings, VIDEO, "lt")
    assert saved["language"] == "lt" and saved["is_generated"] is False
    assert saved["segments"] == [{"text": "Pilietis.", "start": 2, "duration": 2.5}]


def test_failed_download_refreshes_link_only_on_manual_retry(app, monkeypatch):
    from app import downsub

    attempts = []

    def responder(request):
        attempts.append(request.method)
        if request.method == "POST":
            return 200, json.dumps(metadata()).encode(), {}
        return (404, b"expired", {}) if attempts == ["POST", "GET"] else (200, SRT.encode(), {})

    transport(monkeypatch, responder)
    with pytest.raises(ValueError):
        downsub.fetch_transcript(app.state.settings, VIDEO, "pl")
    assert attempts == ["POST", "GET"]
    saved = downsub.fetch_transcript(app.state.settings, VIDEO, "pl")
    assert saved["segments"][0]["start"] == 5.894
    assert attempts == ["POST", "GET", "POST", "GET"]
    downsub.fetch_transcript(app.state.settings, VIDEO, "pl")
    assert attempts == ["POST", "GET", "POST", "GET"]

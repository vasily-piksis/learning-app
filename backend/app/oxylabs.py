"""YouTube-only Oxylabs transport with a durable, credential-free result cache."""

import hashlib
import json
import re
import uuid
from threading import RLock
from types import SimpleNamespace

from pydantic import BaseModel, Field, ValidationError
from requests import RequestException, Session

UNAVAILABLE = "Не удалось получить субтитры через Oxylabs. Попробуйте позже"
MISSING = "Субтитры на выбранном языке недоступны. Проверьте язык и наличие субтитров у видео"
INVALID = "Oxylabs вернул некорректные данные субтитров"
LANGUAGE = r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$"
# One application worker is supported. Serializing cache fills prevents duplicate
# billable requests from simultaneous tabs and the background import worker.
_cache_lock = RLock()


class Track(BaseModel):
    language: str = Field(pattern=LANGUAGE, max_length=20)
    name: str = Field(max_length=100)
    is_generated: bool


class Tracks(BaseModel):
    tracks: list[Track] = Field(min_length=1, max_length=500)


class CaptionSegment(BaseModel):
    utf8: str = Field(max_length=100000)


class CaptionEvent(BaseModel):
    tStartMs: float = Field(ge=0, allow_inf_nan=False)
    dDurationMs: float = Field(default=0, ge=0, allow_inf_nan=False)
    segs: list[CaptionSegment] = Field(default_factory=list, max_length=10000)


class CaptionEvents(BaseModel):
    events: list[CaptionEvent] = Field(max_length=20000)


class SavedSegment(BaseModel):
    text: str = Field(min_length=1, max_length=100000)
    start: float = Field(ge=0, allow_inf_nan=False)
    duration: float = Field(ge=0, allow_inf_nan=False)


class SavedTranscript(BaseModel):
    language: str = Field(pattern=LANGUAGE, max_length=20)
    is_generated: bool
    segments: list[SavedSegment] = Field(min_length=1, max_length=10000)


def enabled(settings):
    username = settings.oxylabs_username.get_secret_value()
    password = settings.oxylabs_password.get_secret_value()
    if bool(username) != bool(password):
        raise ValueError("Укажите OXYLABS_USERNAME и OXYLABS_PASSWORD в .env")
    return bool(username and password)


def bounded_response(response, **kwargs):
    # Requests can consume a redirect body even with allow_redirects=False.
    # A response hook runs before that internal next-hop preparation.
    try:
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 8 * 1024 * 1024:
                raise ValueError("Ответ Oxylabs слишком большой")
            chunks.append(chunk)
        response._content = b"".join(chunks)
        response._content_consumed = True
    finally:
        response.close()
    return response


def request_content(settings, payload):
    """One synchronous request; no automatic retry or credential-bearing redirects."""
    try:
        with (
            Session() as session,
            session.post(
                "https://realtime.oxylabs.io/v1/queries",
                auth=(
                    settings.oxylabs_username.get_secret_value(),
                    settings.oxylabs_password.get_secret_value(),
                ),
                json=payload,
                timeout=(10, 180),
                stream=True,
                allow_redirects=False,
                hooks={"response": [bounded_response]},
            ) as response,
        ):
            if response.status_code == 401:
                raise ValueError("Проверьте логин и пароль API Oxylabs в .env")
            if response.status_code == 403:
                raise ValueError("Oxylabs не разрешил этот запрос. Проверьте доступ к YouTube API")
            if response.status_code in (402, 429):
                raise ValueError("Oxylabs: проверьте остаток бюджета и лимит запросов")
            if response.status_code != 200:
                raise ValueError(UNAVAILABLE)
            if not response._content_consumed:
                bounded_response(response)
            try:
                envelope = response.json()
                results = envelope["results"]
                if len(results) != 1 or results[0]["status_code"] != 200:
                    raise ValueError
                content = results[0]["content"]
                if not isinstance(content, dict):
                    raise ValueError
                return content
            except (ValueError, KeyError, TypeError, IndexError):
                raise ValueError(INVALID) from None
    except RequestException:
        # Upstream exception strings can contain request/auth details.
        raise ValueError(UNAVAILABLE) from None


def cached(settings, key, schema, load):
    path = (
        settings.data_dir / "youtube-cache" / (hashlib.sha256(key.encode()).hexdigest() + ".json")
    )
    with _cache_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.is_file():
                return schema.model_validate_json(path.read_text()).model_dump()
            value = schema.model_validate(load()).model_dump()
        except (ValidationError, json.JSONDecodeError):
            raise ValueError(INVALID) from None
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return value


def list_tracks(settings, video):
    def load():
        content = request_content(
            settings, {"source": "youtube_metadata", "query": video, "parse": True}
        )
        metadata = content.get("results")
        if not isinstance(metadata, dict) or metadata.get("video_id") != video:
            raise ValueError(INVALID)
        if content.get("parse_status_code") != 12000:
            raise ValueError(INVALID)
        tracks = []
        for field, generated in [
            ("user_subtitle_languages", False),
            ("generated_subtitle_languages", True),
        ]:
            languages = metadata.get(field, [])
            if not isinstance(languages, list):
                raise ValueError(INVALID)
            for language in languages:
                tracks.append({"language": language, "name": language, "is_generated": generated})
        if not tracks:
            raise ValueError("У видео нет доступных субтитров")
        return {"tracks": tracks}

    return cached(settings, f"oxylabs:tracks:{video}", Tracks, load)["tracks"]


def fetch_transcript(settings, video, language):
    if not re.fullmatch(LANGUAGE, language):
        raise ValueError(INVALID)

    def load():
        from .youtube import normalize_transcript

        content = request_content(
            settings,
            {
                "source": "youtube_subtitles",
                "query": video,
                "context": [{"key": "language_code", "value": language}],
            },
        )
        for origin, generated in [("uploader_provided", False), ("auto_generated", True)]:
            tracks = content.get(origin, {})
            if not isinstance(tracks, dict):
                raise ValueError(INVALID)
            if language not in tracks:
                continue
            events = CaptionEvents.model_validate(tracks[language]).events
            snippets = [
                SimpleNamespace(
                    text="".join(segment.utf8 for segment in event.segs),
                    start=event.tStartMs / 1000,
                    duration=event.dDurationMs / 1000,
                )
                for event in events
                if event.segs
            ]
            return normalize_transcript(
                SimpleNamespace(
                    language_code=language,
                    is_generated=generated,
                    snippets=snippets,
                )
            )
        raise ValueError(MISSING)

    return cached(settings, f"oxylabs:transcript:{video}:{language}", SavedTranscript, load)

import hashlib
import json
import math
import re
import uuid
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from requests import RequestException, Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from youtube_transcript_api import (
    AgeRestricted,
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
)

from . import downsub
from .auth import require_user
from .library import document_data, get_or_404
from .models import Document, Job, SourcePage, Topic

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


class VideoBody(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class YouTubeBody(VideoBody):
    language: str | None = Field(
        default=None, pattern=r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$", max_length=20
    )


def video_url(value):
    try:
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port is not None
        ):
            raise ValueError
        if parsed.hostname == "youtu.be":
            video = parsed.path.removeprefix("/")
        elif parsed.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            if parsed.path == "/watch":
                ids = parse_qs(parsed.query, max_num_fields=32).get("v", [])
                if len(ids) != 1:
                    raise ValueError
                video = ids[0]
            else:
                match = re.fullmatch(r"/(?:shorts|embed|live)/([A-Za-z0-9_-]{11})", parsed.path)
                if not match:
                    raise ValueError
                video = match[1]
        else:
            raise ValueError
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
            raise ValueError
        return video, f"https://www.youtube.com/watch?v={video}"
    except ValueError:
        raise ValueError(
            "Введите ссылку на одно видео YouTube (youtube.com или youtu.be)"
        ) from None


class TranscriptSession(Session):
    """Timeouts and bounded responses for the third-party transcript transport."""

    def __init__(self):
        super().__init__()
        self.max_redirects = 3

    def request(self, method, url, **kwargs):
        kwargs["timeout"] = (10, 30)
        kwargs["stream"] = True
        # Requests runs response hooks before consuming redirect bodies. Apply the
        # bound to every hop, including redirect responses, not just the final one.
        kwargs["hooks"] = {"response": [self.read_response]}
        return super().request(method, url, **kwargs)

    def read_response(self, response, **kwargs):
        try:
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 8 * 1024 * 1024:
                    raise ValueError("Ответ YouTube слишком большой")
                chunks.append(chunk)
            response._content = b"".join(chunks)
            response._content_consumed = True
        finally:
            response.close()
        return response


def fetch_transcript(video, language):
    try:
        with TranscriptSession() as session:
            return YouTubeTranscriptApi(http_client=session).fetch(video, languages=[language])
    except (IpBlocked, RequestBlocked):
        raise ValueError(
            "YouTube заблокировал получение субтитров с этого сервера. Попробуйте позже"
        ) from None
    except (TranscriptsDisabled, NoTranscriptFound):
        raise ValueError(
            "Субтитры на выбранном языке недоступны. Проверьте язык и наличие субтитров у видео"
        ) from None
    except (AgeRestricted, VideoUnavailable):
        raise ValueError("Видео недоступно или имеет ограничение по возрасту") from None
    except (YouTubeTranscriptApiException, RequestException):
        raise ValueError("Не удалось получить субтитры YouTube. Попробуйте позже") from None


def list_tracks(video):
    try:
        with TranscriptSession() as session:
            tracks = YouTubeTranscriptApi(http_client=session).list(video)
            return [
                {
                    "language": track.language_code,
                    "name": track.language,
                    "is_generated": track.is_generated,
                }
                for track in tracks
            ]
    except (IpBlocked, RequestBlocked):
        raise ValueError(
            "YouTube заблокировал получение субтитров с этого сервера. Попробуйте позже"
        ) from None
    except (TranscriptsDisabled, NoTranscriptFound):
        raise ValueError("У видео нет доступных субтитров") from None
    except (AgeRestricted, VideoUnavailable):
        raise ValueError("Видео недоступно или имеет ограничение по возрасту") from None
    except (YouTubeTranscriptApiException, RequestException):
        raise ValueError("Не удалось получить субтитры YouTube. Попробуйте позже") from None


def resolve_tracks(video, settings=None):
    tracks = (
        downsub.list_tracks(settings, video)
        if settings is not None and settings.youtube_provider == "downsub"
        else list_tracks(video)
    )
    if not tracks:
        raise ValueError("У видео нет доступных субтитров")
    generated = {track["language"] for track in tracks if track["is_generated"]}
    languages = {track["language"] for track in tracks}
    selected = (
        next(iter(generated))
        if len(generated) == 1
        else (next(iter(languages)) if len(languages) == 1 else None)
    )
    return {"tracks": tracks, "selected_language": selected}


@router.post("/youtube/resolve")
def resolve_video(body: VideoBody, request: Request):
    try:
        video, url = video_url(body.url)
        return {"url": url, **resolve_tracks(video, request.app.state.settings)}
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


def normalize_transcript(transcript):
    segments, length = [], 0
    for snippet in transcript.snippets:
        start, duration = float(snippet.start), float(snippet.duration)
        if not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration < 0:
            raise ValueError("Субтитры содержат неверные временные метки")
        if start + duration > 24 * 60 * 60:
            raise ValueError("Видео превышает ограничение в 24 часа")
        text = snippet.text.strip()
        if not text:
            continue
        length += len(text)
        if length > 100000 or len(segments) >= 10000:
            raise ValueError(
                "Субтитры превышают ограничение: 100 000 символов или 10 000 фрагментов"
            )
        segments.append({"text": text, "start": start, "duration": duration})
    if not segments:
        raise ValueError("Субтитры не содержат текста")
    return {
        "language": transcript.language_code,
        "is_generated": transcript.is_generated,
        "segments": segments,
    }


@router.post("/topics/{identifier}/youtube")
def add_youtube(identifier: int, body: YouTubeBody, request: Request):
    try:
        video, url = video_url(body.url)
        language = (
            body.language or resolve_tracks(video, request.app.state.settings)["selected_language"]
        )
        if not language:
            raise ValueError("Выберите исходный язык из доступных дорожек субтитров")
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    user = require_user(request)
    database = request.app.state.db
    digest = hashlib.sha256(f"youtube:{video}:{language}".encode()).hexdigest()
    try:
        with database.session() as db:
            topic = get_or_404(db, Topic, identifier)
            duplicate = db.scalar(
                select(Document).where(Document.topic_id == identifier, Document.sha256 == digest)
            )
            if duplicate:
                return {**document_data(db, duplicate), "duplicate": True}
            document = Document(
                topic_id=identifier,
                name=f"YouTube · {video}",
                filename=uuid.uuid4().hex,
                mime="application/json",
                size=0,
                sha256=digest,
                page_count=0,
                source_url=url,
                source_meta={"video_id": video, "language": language},
            )
            db.add(document)
            db.flush()
            topic.version += 1
            db.add(Job(user_id=user.id, kind="youtube", payload={"document_id": document.id}))
            db.flush()
            return {**document_data(db, document), "duplicate": False}
    except IntegrityError:
        with database.session() as db:
            duplicate = db.scalar(
                select(Document).where(Document.topic_id == identifier, Document.sha256 == digest)
            )
            if not duplicate:
                raise
            return {**document_data(db, duplicate), "duplicate": True}


def ingest_youtube(database, payload):
    with database.session() as db:
        document = db.get(Document, payload["document_id"])
        document.status = "processing"
        metadata, filename, url = document.source_meta, document.filename, document.source_url
    path = database.settings.data_dir / "files" / filename
    # An atomic file is the retained transcript cache if the process stops before DB commit.
    if path.is_file():
        saved = json.loads(path.read_text())
    else:
        saved = (
            downsub.fetch_transcript(database.settings, metadata["video_id"], metadata["language"])
            if database.settings.youtube_provider == "downsub"
            else normalize_transcript(fetch_transcript(metadata["video_id"], metadata["language"]))
        )
        saved.update(video_id=metadata["video_id"], url=url)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    with database.session() as db:
        document = db.get(Document, payload["document_id"])
        existing = set(
            db.scalars(select(SourcePage.number).where(SourcePage.document_id == document.id))
        )
        warnings = (
            ["Автоматические субтитры могут содержать ошибки"] if saved["is_generated"] else []
        )
        for number, segment in enumerate(saved["segments"], 1):
            if number not in existing:
                db.add(
                    SourcePage(
                        document_id=document.id,
                        number=number,
                        text=segment["text"],
                        language=saved["language"],
                        start_seconds=segment["start"],
                        end_seconds=segment["start"] + segment["duration"],
                        warnings=warnings if number == 1 else [],
                    )
                )
        document.source_meta = {k: v for k, v in saved.items() if k != "segments"}
        document.size, document.page_count, document.status = (
            path.stat().st_size,
            len(saved["segments"]),
            "ready",
        )
    return {"document_id": payload["document_id"], "segments": len(saved["segments"])}

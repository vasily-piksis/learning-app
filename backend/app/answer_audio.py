"""Private media validation, transcription lifecycle, and recoverable cleanup."""

import hashlib
import json
import math
import os
import re
import stat
import subprocess  # nosec B404
import uuid
import wave
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy import delete, func, select, text

from .auth import require_user
from .evaluations import RetryEvaluationBody, outcome_unknown, utc_now
from .free_responses import count_words, response_exercise
from .models import (
    AudioAnswer,
    Evaluation,
    Job,
    SessionCard,
    StudySession,
    TranscriptionRequest,
    now,
)
from .transcription import Transcriber, language_hint

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])
MAX_BYTES = 15 * 1024 * 1024
FORMATS = "mov,matroska,webm,ogg,wav"
ERRORS = {
    "unknown": "Результат неизвестен; запрос мог быть оплачен. Повтор возможен только явно",
    "failed": "Не удалось распознать запись",
    "runtime_unavailable": "Распознавание сейчас недоступно. Можно написать ответ",
    "quota_exceeded": "Дневной лимит распознавания исчерпан",
    "record_again": "Запись больше недоступна. Запишите ответ снова",
}


@dataclass(frozen=True)
class ValidatedAudio:
    mime: str
    duration: float
    sha256: str
    normalized_path: Path


def private_directory(settings):
    path = settings.data_dir / "answer-audio"
    path.mkdir(mode=0o700, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Invalid private directory")
    path.chmod(0o700)
    return path


def owned_file(path):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("Invalid audio file")
        if not re.fullmatch(r"[0-9a-f]{32}(?:\.normalized)?\.[a-z0-9]+", path.name):
            raise ValueError("Invalid audio file")
    except OSError:
        raise ValueError("Invalid audio file") from None


def reject_external_mp4(data):
    """Walk ISO boxes without resolving data references, including QuickTime aliases."""

    def boxes(start, end, depth=0):
        if depth > 12:
            raise ValueError("Invalid container")
        while start + 8 <= end:
            size, kind = int.from_bytes(data[start : start + 4], "big"), data[start + 4 : start + 8]
            header = 8
            if size == 1:
                size, header = int.from_bytes(data[start + 8 : start + 16], "big"), 16
            if size == 0:
                size = end - start
            if size < header or start + size > end:
                raise ValueError("Invalid container")
            body, stop = start + header, start + size
            if kind in {b"moov", b"trak", b"mdia", b"minf", b"dinf"}:
                boxes(body, stop, depth + 1)
            if kind == b"dref":
                if body + 8 > stop:
                    raise ValueError("Invalid data references")
                count = int.from_bytes(data[body + 4 : body + 8], "big")
                cursor = body + 8
                for _ in range(count):
                    length = int.from_bytes(data[cursor : cursor + 4], "big")
                    entry = data[cursor + 4 : cursor + 8]
                    flags = int.from_bytes(data[cursor + 8 : cursor + 12], "big")
                    if length != 12 or cursor + length > stop or entry != b"url " or flags != 1:
                        raise ValueError("External audio references forbidden")
                    cursor += length
            start = stop

    boxes(0, len(data))


def validate_audio(path: Path) -> ValidatedAudio:
    owned_file(path)
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("Invalid audio size")
    data = path.read_bytes()
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        mime = "audio/wav"
    elif data[:4] == b"OggS":
        mime = "audio/ogg"
    elif data[:4] == b"\x1aE\xdf\xa3":
        mime = "audio/webm"
    elif data[4:8] == b"ftyp":
        mime = "audio/mp4"
        reject_external_mp4(data)
    else:
        raise ValueError("Unsupported audio container")
    normalized = path.parent / f"{uuid.uuid4().hex}.normalized.wav"
    flags = ["-protocol_whitelist", "file,pipe", "-format_whitelist", FORMATS]
    try:
        probe = subprocess.run(  # nosec B603,B607
            [
                "ffprobe",
                "-v",
                "error",
                *flags,
                "-show_entries",
                "format=format_name,duration:stream=codec_type",
                "-of",
                "json",
                str(path),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=10,
            check=True,
            shell=False,  # nosec B603
        )
        metadata = json.loads(probe.stdout)
        streams = metadata.get("streams", [])
        if not streams or any(s.get("codec_type") != "audio" for s in streams):
            raise ValueError("Only audio streams allowed")
        duration = metadata.get("format", {}).get("duration")
        if duration not in (None, "N/A") and (
            not math.isfinite(float(duration)) or float(duration) > 180
        ):
            raise ValueError("Invalid audio duration")
        with normalized.open("xb") as output:
            os.chmod(normalized, 0o600)
            subprocess.run(  # nosec B603,B607
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-xerror",
                    *flags,
                    "-i",
                    str(path),
                    "-map",
                    "0:a:0",
                    "-t",
                    "181",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    "-f",
                    "wav",
                    "pipe:1",
                ],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.PIPE,
                timeout=30,
                check=True,
                shell=False,  # nosec B603
            )
        # Pipe WAV headers can use unknown length: count actual complete decoded sample bytes.
        with wave.open(str(normalized), "rb") as decoded:
            samples = decoded.readframes(181 * 16000 + 1)
            if (
                decoded.getnchannels() != 1
                or decoded.getsampwidth() != 2
                or decoded.getframerate() != 16000
            ):
                raise ValueError("Invalid decoded audio")
        duration = len(samples) / 32000
        if not math.isfinite(duration) or not 0 < duration <= 180 or len(samples) % 2:
            raise ValueError("Invalid decoded duration")
        # Write an exact finite WAV header for SDK and browser playback.
        with wave.open(str(normalized), "wb") as output:
            output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            output.writeframes(samples)
        return ValidatedAudio(mime, duration, hashlib.sha256(data).hexdigest(), normalized)
    except (OSError, ValueError, subprocess.SubprocessError, wave.Error, EOFError):
        normalized.unlink(missing_ok=True)
        raise ValueError("Неверный формат или длительность записи") from None


def runtime_available(settings):
    try:
        ZoneInfo(settings.budget_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    model = settings.openai_transcription_model
    return bool(
        settings.transcription_enabled
        and settings.openai_api_key
        and model
        and len(model) <= 200
        and not any(c.isspace() for c in model)
        and settings.transcription_daily_seconds_limit > 0
    )


def require_available(settings):
    if not runtime_available(settings):
        raise HTTPException(
            409, {"code": "runtime_unavailable", "message": ERRORS["runtime_unavailable"]}
        )


def current_audio(db, card_id):
    return db.scalar(
        select(AudioAnswer).where(
            AudioAnswer.session_card_id == card_id,
            AudioAnswer.status.not_in(["discarded", "deleted"]),
        )
    )


def audio_data(audio):
    return {
        "audio_answer_id": audio.id,
        "job_id": audio.job_id,
        "status": audio.status,
        "duration": audio.duration,
        "expires_at": audio.expires_at.isoformat() + "Z",
        "original_transcript": audio.original_transcript,
        "expected_language": audio.expected_language,
        "detected_languages": audio.detected_languages,
        "language_mismatch": bool(
            audio.detected_languages
            and any(
                language_hint(code) != language_hint(audio.expected_language)
                for code in audio.detected_languages
            )
        ),
        "recording_available": bool(
            audio.raw_path
            and audio.expires_at > now()
            and audio.status not in {"ready", "discarded", "deleted"}
        ),
        "error_code": audio.error_code,
        "error": ERRORS.get(audio.error_code),
    }


def get_owned(db, identifier, user_id):
    audio = db.get(AudioAnswer, identifier)
    if not audio or audio.user_id != user_id or audio.status == "deleted":
        raise HTTPException(404, "Не найдено")
    return audio


def ensure_active(db, session, card):
    if card.snapshot.get("question_type") not in {"free_response", "picture_description"}:
        raise HTTPException(422, "Голос недоступен для этого задания")
    if (
        session.status != "active"
        or session.position != card.position
        or db.scalar(select(Evaluation.id).where(Evaluation.session_card_id == card.id))
    ):
        raise HTTPException(409, "Ответ уже отправлен или занятие неактивно")


def key_used(db, user_id, key):
    return bool(
        db.scalar(
            select(TranscriptionRequest.id).where(
                TranscriptionRequest.user_id == user_id, TranscriptionRequest.request_key == key
            )
        )
        or any(
            key in row.request_keys
            for row in db.scalars(select(AudioAnswer).where(AudioAnswer.user_id == user_id))
        )
    )


@router.get("/study/{identifier}/audio")
def lookup(identifier: int, position: int, request: Request):
    from .study import at_position, owned

    with request.app.state.db.session() as db:
        owned(db, identifier, require_user(request).id)
        card = at_position(db, identifier, position)
        audio = current_audio(db, card.id)
        available = runtime_available(request.app.state.settings)
        return {
            "available": available,
            "reason": None if available else "runtime_unavailable",
            "audio_answer": audio_data(audio) if audio else None,
        }


@router.post("/study/{identifier}/audio", status_code=202)
def upload(
    identifier: int,
    request: Request,
    position: Annotated[int, Form(ge=0)],
    idempotency_key: Annotated[str, Form(min_length=1, max_length=80)],
    file: Annotated[UploadFile, File()],
):
    from .study import at_position, owned

    database, user = request.app.state.db, require_user(request)
    with database.session() as db:
        session = owned(db, identifier, user.id)
        card = at_position(db, identifier, position)
        ensure_active(db, session, card)
    directory = private_directory(database.settings)
    incoming = directory / f"{uuid.uuid4().hex}.part"
    normalized = None
    retained = False
    try:
        size = 0
        with incoming.open("xb") as stream:
            incoming.chmod(0o600)
            while chunk := file.file.read(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(422, "Запись превышает 15 MiB")
                stream.write(chunk)
        digest = hashlib.sha256(incoming.read_bytes()).hexdigest()
        # Bind idempotency to original bytes, including container metadata.
        with database.session() as db:
            previous = db.scalar(
                select(AudioAnswer).where(
                    AudioAnswer.user_id == user.id, AudioAnswer.request_key == idempotency_key
                )
            )
            if previous:
                if (
                    previous.session_card_id != card.id
                    or previous.sha256 != digest
                    or previous.status in {"discarded", "deleted"}
                ):
                    raise HTTPException(409, "Идентификатор уже использован")
                return JSONResponse(audio_data(previous), status_code=202)
        require_available(database.settings)
        validated = validate_audio(incoming)
        normalized = validated.normalized_path
        with normalized.open("rb") as stream:
            os.fsync(stream.fileno())
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        with database.session() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            session = owned(db, identifier, user.id)
            card = at_position(db, identifier, position)
            ensure_active(db, session, card)
            require_available(database.settings)
            previous = current_audio(db, card.id)
            if previous:
                if previous.request_key == idempotency_key and previous.sha256 == digest:
                    return JSONResponse(audio_data(previous), status_code=202)
                raise HTTPException(409, "Сначала удалите предыдущую запись")
            if key_used(db, user.id, idempotency_key):
                raise HTTPException(409, "Идентификатор уже использован")
            identifier_audio = uuid.uuid4().hex
            job = Job(
                user_id=user.id,
                kind="transcribe_answer",
                payload={
                    "session_card_id": card.id,
                    "audio_answer_id": identifier_audio,
                    "revision": 1,
                    "request_key": idempotency_key,
                },
            )
            db.add(job)
            db.flush()
            audio = AudioAnswer(
                id=identifier_audio,
                session_card_id=card.id,
                user_id=user.id,
                job_id=job.id,
                request_key=idempotency_key,
                request_keys=[idempotency_key],
                sha256=digest,
                duration=validated.duration,
                raw_path=normalized.name,
                expected_language=response_exercise(card.snapshot).language,
                expires_at=now() + timedelta(hours=24),
            )
            db.add(audio)
            db.flush()
            result = audio_data(audio)
        retained = True
        return JSONResponse(result, status_code=202)
    except ValueError:
        raise HTTPException(422, "Неверный формат или длительность записи") from None
    finally:
        incoming.unlink(missing_ok=True)
        if normalized and not retained:
            normalized.unlink(missing_ok=True)
        file.file.close()


@router.get("/audio-answers/{identifier}")
def status(identifier: str, request: Request):
    with request.app.state.db.session() as db:
        return audio_data(get_owned(db, identifier, require_user(request).id))


@router.get("/audio-answers/{identifier}/recording")
def recording(identifier: str, request: Request):
    with request.app.state.db.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        audio = get_owned(db, identifier, require_user(request).id)
        if not audio_data(audio)["recording_available"]:
            raise HTTPException(404, "Запись недоступна")
        try:
            path = private_directory(request.app.state.settings) / audio.raw_path
            owned_file(path)
            data = path.read_bytes()
        except (OSError, ValueError):
            raise HTTPException(404, "Запись недоступна") from None
        return Response(
            data,
            media_type="audio/wav",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )


def cancel_audio(db, audio, deleted=False):
    audio.revision += 1
    audio.status = "deleted" if deleted else "discarded"
    audio.original_transcript, audio.detected_languages, audio.was_edited = None, [], False
    audio.error_code = None
    job = db.get(Job, audio.job_id)
    job.status, job.result, job.error = ("deleted" if deleted else "cancelled"), None, None
    job.payload = {}
    if deleted:
        audio.session_card_id = None
        audio.expected_language, audio.sha256, audio.request_keys = "", "", []


@router.delete("/audio-answers/{identifier}")
def discard(identifier: str, request: Request):
    database = request.app.state.db
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        audio = get_owned(db, identifier, require_user(request).id)
        if db.scalar(
            select(Evaluation.id).where(Evaluation.session_card_id == audio.session_card_id)
        ):
            raise HTTPException(409, "Ответ уже отправлен")
        if audio.status != "discarded":
            cancel_audio(db, audio)
    cleanup_answer_audio(database)
    return {"discarded": True}


@router.post("/audio-answers/{identifier}/retry", status_code=202)
def retry(identifier: str, body: RetryEvaluationBody, request: Request):
    from .study import owned

    database = request.app.state.db
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        audio = get_owned(db, identifier, require_user(request).id)
        job = db.get(Job, audio.job_id)
        if body.idempotency_key in audio.request_keys:
            if (
                body.idempotency_key == job.payload.get("request_key")
                and body.idempotency_key != audio.request_key
            ):
                return JSONResponse(audio_data(audio), status_code=202)
            raise HTTPException(409, "Для повтора нужен новый идентификатор")
        if (
            audio.status not in {"failed", "unknown"}
            or len(audio.request_keys) >= 100
            or key_used(db, audio.user_id, body.idempotency_key)
        ):
            raise HTTPException(409, "Повтор недоступен")
        card = db.get(SessionCard, audio.session_card_id)
        session = owned(db, card.session_id, audio.user_id)
        ensure_active(db, session, card)
        require_available(database.settings)
        if not audio.raw_path or audio.expires_at <= now():
            raise HTTPException(409, {"code": "record_again", "message": ERRORS["record_again"]})
        try:
            owned_file(private_directory(database.settings) / audio.raw_path)
        except ValueError:
            raise HTTPException(
                409, {"code": "record_again", "message": ERRORS["record_again"]}
            ) from None
        audio.request_keys = [*audio.request_keys, body.idempotency_key]
        audio.revision += 1
        audio.status, audio.error_code = "queued", None
        job.status, job.error = "queued", None
        job.payload = {
            **job.payload,
            "revision": audio.revision,
            "request_key": body.idempotency_key,
        }
        return JSONResponse(audio_data(audio), status_code=202)


class AudioCancelled(Exception):
    pass


class AudioFailure(Exception):
    def __init__(self, code):
        self.code = code


def live_context(db, audio, revision, statuses):
    if audio is None or audio.revision != revision or audio.status not in statuses:
        raise AudioCancelled()
    card = db.get(SessionCard, audio.session_card_id)
    session = db.get(StudySession, card.session_id) if card else None
    job = db.get(Job, audio.job_id)
    if (
        not session
        or session.status != "active"
        or session.position != card.position
        or session.user_id != audio.user_id
        or job.status != "running"
        or job.payload.get("audio_answer_id") != audio.id
        or job.payload.get("revision") != revision
    ):
        raise AudioCancelled()
    return job


def reserve_request(database, identifier, revision):
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        audio = db.get(AudioAnswer, identifier)
        job = live_context(db, audio, revision, {"running"})
        if not runtime_available(database.settings):
            raise AudioFailure("runtime_unavailable")
        if audio.expires_at <= now() or not audio.raw_path:
            raise AudioFailure("record_again")
        key = job.payload["request_key"]
        if db.scalar(
            select(TranscriptionRequest.id).where(
                TranscriptionRequest.user_id == audio.user_id,
                TranscriptionRequest.request_key == key,
            )
        ):
            raise AudioCancelled()
        current = utc_now()
        zone = ZoneInfo(database.settings.budget_timezone)
        day = current.astimezone(zone).date()
        start = datetime.combine(day, time.min, zone).astimezone(UTC).replace(tzinfo=None)
        end = (
            datetime.combine(day + timedelta(days=1), time.min, zone)
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        seconds = math.ceil(audio.duration)
        used = db.scalar(
            select(func.coalesce(func.sum(TranscriptionRequest.seconds), 0)).where(
                TranscriptionRequest.reserved_at >= start, TranscriptionRequest.reserved_at < end
            )
        )
        if used + seconds > database.settings.transcription_daily_seconds_limit:
            raise AudioFailure("quota_exceeded")
        record = TranscriptionRequest(
            id=uuid.uuid4().hex,
            job_id=job.id,
            user_id=audio.user_id,
            request_key=key,
            seconds=seconds,
            reserved_at=current.replace(tzinfo=None),
            model=database.settings.openai_transcription_model,
        )
        db.add(record)
        db.flush()
        return record.id


def persist_transcript(database, identifier, revision, transcript):
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        audio = db.get(AudioAnswer, identifier)
        job = live_context(db, audio, revision, {"running"})
        audio.original_transcript, audio.detected_languages = transcript.text, transcript.languages
        audio.status, audio.error_code = "ready", None
        job.status, job.result, job.error = "succeeded", {"audio_answer_id": identifier}, None


def run_transcription_job(database, job_id, revision):
    record_id, usage, outcome, code = None, None, "unknown", None
    try:
        with database.session() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            audio = db.scalar(select(AudioAnswer).where(AudioAnswer.job_id == job_id))
            live_context(db, audio, revision, {"queued"})
            audio.status = "running"
            identifier, language = audio.id, audio.expected_language
            if not audio.raw_path or audio.expires_at <= now():
                raise AudioFailure("record_again")
            path = private_directory(database.settings) / audio.raw_path
            validated = ValidatedAudio("audio/wav", audio.duration, audio.sha256, path)
        try:
            owned_file(path)
        except ValueError:
            raise AudioFailure("record_again") from None
        transcriber = (
            Transcriber(database.settings) if runtime_available(database.settings) else None
        )
        record_id = reserve_request(database, identifier, revision)
        transcript = transcriber.transcribe(validated, language)
        outcome, usage = "succeeded", transcript.usage
        persist_transcript(database, identifier, revision, transcript)
    except AudioCancelled:
        # A completed text answer may invalidate a queued recording without a discard.
        # Do not leave its claimed job running forever, or touch a newer revision.
        with database.session() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            audio = db.scalar(select(AudioAnswer).where(AudioAnswer.job_id == job_id))
            if audio and audio.revision == revision and audio.status in {"queued", "running"}:
                cancel_audio(db, audio)
    except Exception as error:
        code = (
            error.code
            if isinstance(error, AudioFailure)
            else "unknown"
            if outcome_unknown(error) or outcome == "succeeded"
            else "failed"
        )
        if outcome != "succeeded":
            outcome = "unknown" if code == "unknown" else "failed"
        with database.session() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            audio = db.scalar(select(AudioAnswer).where(AudioAnswer.job_id == job_id))
            if audio and audio.revision == revision and audio.status in {"queued", "running"}:
                audio.status, audio.error_code = (
                    ("unknown" if code == "unknown" else "failed"),
                    code,
                )
                job = db.get(Job, job_id)
                job.status, job.error = audio.status, ERRORS[code]
    finally:
        if record_id:
            with database.session() as db:
                record = db.get(TranscriptionRequest, record_id)
                if record and record.job_id == job_id:
                    record.status, record.usage, record.error_code = outcome, usage, code
        cleanup_answer_audio(database)


def cleanup_answer_audio(database, recover_parts=False):
    directory = private_directory(database.settings)
    # Shared SQLite exclusive claim holds through unlink; retries/serving/cancel cannot race it.
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        for audio in db.scalars(select(AudioAnswer)):
            job = db.get(Job, audio.job_id)
            if audio.raw_path and (
                audio.status in {"ready", "discarded", "deleted"}
                or (audio.expires_at <= now() and job.status not in {"queued", "running"})
            ):
                path = directory / audio.raw_path
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    continue
                audio.raw_path = None
            if audio.status == "deleted" and audio.raw_path is None:
                db.delete(audio)
        referenced = set(
            db.scalars(select(AudioAnswer.raw_path).where(AudioAnswer.raw_path.is_not(None)))
        )
        for path in directory.iterdir():
            if path.name not in referenced and re.fullmatch(
                r"[0-9a-f]{32}(?:\.normalized)?\.(?:part|wav)", path.name
            ):
                try:
                    if (
                        recover_parts
                        or path.lstat().st_mtime
                        < (now() - timedelta(hours=24)).replace(tzinfo=UTC).timestamp()
                    ):
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
        db.execute(
            delete(TranscriptionRequest).where(
                TranscriptionRequest.reserved_at < now() - timedelta(days=30)
            )
        )


def recover_answer_audio(database):
    with database.session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        for audio in db.scalars(
            select(AudioAnswer).where(AudioAnswer.status.in_(["queued", "running"]))
        ):
            job = db.get(Job, audio.job_id)
            if audio.status == "running" or job.status == "running":
                audio.revision += 1
                audio.status, audio.error_code = "unknown", "unknown"
                job.status, job.error = "unknown", ERRORS["unknown"]
        for record in db.scalars(
            select(TranscriptionRequest).where(TranscriptionRequest.status == "reserved")
        ):
            record.status = "unknown"
    cleanup_answer_audio(database, recover_parts=True)


def voice_metadata(db, card, user_id, submission):
    identifier = submission.get("audio_answer_id")
    if not identifier:
        return None
    audio = get_owned(db, identifier, user_id)
    if (
        audio.session_card_id != card.id
        or audio.expected_language != response_exercise(card.snapshot).language
        or audio.status != "ready"
        or not audio.original_transcript
    ):
        raise HTTPException(409, "Транскрипция ещё не готова или относится к другому заданию")
    audio.was_edited = audio.original_transcript != submission["free_text"]
    return {
        "original_transcript": audio.original_transcript,
        "original_word_count": count_words(audio.original_transcript),
        "was_edited": audio.was_edited,
    }

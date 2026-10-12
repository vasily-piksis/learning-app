"""Anonymous DownSub website protocol; original tracks only, never translations."""

import base64
import hashlib
import json
import os
import re
import time
from collections import OrderedDict
from urllib.parse import quote

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from pydantic import Field, ValidationError
from requests import RequestException, Session

from .caption_cache import LANGUAGE, Track, Tracks, Transcript, cached, lock

UNAVAILABLE = "Не удалось получить субтитры через DownSub. Попробуйте позже"
INVALID = "DownSub вернул некорректные данные субтитров"
MISSING = "Субтитры на выбранном языке недоступны. Проверьте язык и наличие субтитров у видео"
# Public obfuscation parameter from DownSub's website, not a private API key.
PUBLIC_PARAMETER_KEY = "zthxw34cdp6wfyxmpad38v52t3hsz6c5"
_metadata = OrderedDict()


def encode_parameter(value, passphrase=PUBLIC_PARAMETER_KEY):
    salt = os.urandom(8)
    material, block = b"", b""
    while len(material) < 48:
        # CryptoJS's website format uses OpenSSL's historical derivation. This
        # only encodes public video identifiers; it does not protect app secrets.
        block = hashlib.md5(block + passphrase.encode() + salt, usedforsecurity=False).digest()
        material += block
    iv = material[32:48]
    # Website wire-format compatibility for public IDs/URLs, transported over TLS.
    # This cipher never protects credentials, sessions or private stored data.
    # nosemgrep: python.cryptography.security.mode-without-authentication.crypto-mode-without-authentication
    encryptor = Cipher(algorithms.AES(material[:32]), modes.CBC(iv)).encryptor()
    padder = padding.PKCS7(128).padder()
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    ciphertext = encryptor.update(padder.update(data) + padder.finalize()) + encryptor.finalize()
    formatted = json.dumps(
        {"ct": base64.b64encode(ciphertext).decode(), "iv": iv.hex(), "s": salt.hex()},
        separators=(",", ":"),
    )
    return (
        base64.b64encode(formatted.encode())
        .decode()
        .replace("+", "-", 1)
        .replace("/", "_", 1)
        .replace("=", "", 1)
    )


def bounded_response(response, **kwargs):
    # Bound redirects before Requests prepares _next, even when not following.
    try:
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 8 * 1024 * 1024:
                raise ValueError("Ответ DownSub слишком большой")
            chunks.append(chunk)
        response._content = b"".join(chunks)
        response._content_consumed = True
    finally:
        response.close()
    return response


def request(method, url, **kwargs):
    try:
        with Session() as session:
            session.trust_env = False
            session.headers.update(
                {"Origin": "https://downsub.com", "Referer": "https://downsub.com/"}
            )
            with session.request(
                method,
                url,
                timeout=(10, 45),
                stream=True,
                allow_redirects=False,
                hooks={"response": [bounded_response]},
                **kwargs,
            ) as response:
                if response.status_code in (401, 403, 429):
                    raise ValueError(
                        "DownSub ограничил доступ или частоту запросов. Попробуйте позже"
                    )
                if response.status_code != 200:
                    raise ValueError(UNAVAILABLE)
                return response.content
    except RequestException:
        raise ValueError(UNAVAILABLE) from None


class DownloadTrack(Track):
    download: str = Field(min_length=1, max_length=12000, pattern=r"^[A-Za-z0-9_+/=-]+$")


def original_tracks(settings, video):
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
        raise ValueError(INVALID)
    key = (str(settings.data_dir.resolve()), video)
    with lock:
        saved = _metadata.get(key)
        if saved and time.monotonic() - saved[0] < 600:
            _metadata.move_to_end(key)
            return saved[1]
        url = f"https://www.youtube.com/watch?v={video}"
        payload = {"url": url, "data": encode_parameter(encode_parameter(url), url)}
        raw = request(
            "POST",
            "https://get.downsub.com/",
            data=json.dumps(payload, separators=(",", ":")),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            metadata = json.loads(raw)
            if metadata.get("state") not in (1, 2) or metadata.get("url") != url:
                raise ValueError
            originals = metadata["subtitles"]
            if not isinstance(originals, list) or len(originals) > 500:
                raise ValueError
            tracks = []
            for value in originals:
                if value.get("type") != "youtube":
                    continue
                tracks.append(
                    DownloadTrack(
                        language=value["language"],
                        name=value["name"],
                        download=value["url"],
                        is_generated=value.get("code", "").endswith("_auto")
                        or "(auto-generated)" in value["name"],
                    )
                )
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ValueError(INVALID) from None
        if not tracks:
            raise ValueError("У видео нет доступных субтитров")
        _metadata[key] = (time.monotonic(), tracks)
        _metadata.move_to_end(key)
        while len(_metadata) > 128:
            _metadata.popitem(last=False)
        return tracks


def list_tracks(settings, video):
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
        raise ValueError(INVALID)
    return cached(
        settings,
        f"youtube:tracks:{video}",
        Tracks,
        lambda: {
            "tracks": [
                track.model_dump(exclude={"download"}) for track in original_tracks(settings, video)
            ]
        },
        legacy_keys=(f"oxylabs:tracks:{video}",),
    )["tracks"]


def parse_srt(text, language, is_generated):
    segments = []
    pattern = r"^(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})$"

    def seconds(value):
        hours, minutes, tail = value.split(":")
        second, millis = tail.split(",")
        if int(minutes) > 59 or int(second) > 59:
            raise ValueError(INVALID)
        return int(hours) * 3600 + int(minutes) * 60 + int(second) + int(millis) / 1000

    for block in re.split(r"\n\s*\n", text.lstrip("\ufeff").replace("\r\n", "\n").strip()):
        lines = block.splitlines()
        if len(lines) < 3 or not lines[0].isdigit():
            raise ValueError(INVALID)
        match = re.fullmatch(pattern, lines[1])
        if not match:
            raise ValueError(INVALID)
        start, end = seconds(match[1]), seconds(match[2])
        segments.append(
            {
                "text": "\n".join(lines[2:]).strip(),
                "start": start,
                "duration": round(end - start, 3),
            }
        )
    try:
        return Transcript(
            language=language, is_generated=is_generated, segments=segments
        ).model_dump()
    except ValidationError:
        raise ValueError(INVALID) from None


def fetch_transcript(settings, video, language):
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video) or not re.fullmatch(LANGUAGE, language):
        raise ValueError(INVALID)

    def load():
        tracks = [track for track in original_tracks(settings, video) if track.language == language]
        if not tracks:
            raise ValueError(MISSING)
        track = min(tracks, key=lambda item: item.is_generated)
        url = "https://subtitle.downsub.com/srt/" + quote(track.download, safe="") + "/?title=study"
        try:
            return parse_srt(request("GET", url).decode("utf-8-sig"), language, track.is_generated)
        except (ValueError, UnicodeError):
            # Refresh expiring download references on the next manual retry.
            _metadata.pop((str(settings.data_dir.resolve()), video), None)
            raise ValueError(UNAVAILABLE) from None

    saved = cached(
        settings,
        f"youtube:transcript:{video}:{language}",
        Transcript,
        load,
        legacy_keys=(f"oxylabs:transcript:{video}:{language}",),
    )
    if saved["language"] != language:
        raise ValueError(INVALID)
    return saved

"""One original-language Audio API send; no automatic retries or translation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from openai import OpenAI

from .free_responses import count_words

if TYPE_CHECKING:
    from .answer_audio import ValidatedAudio


@dataclass(frozen=True)
class Transcript:
    text: str
    languages: list[str]
    usage: dict | None = None


def language_hint(language):
    # Assignments retain BCP-47; Audio accepts ISO primary codes (plus selected zh locales).
    return language.split("-", 1)[0].lower()


class Transcriber:
    def __init__(self, settings, client=None):
        self.model = settings.openai_transcription_model
        self.client = (client or OpenAI(api_key=settings.openai_api_key)).with_options(
            max_retries=0, timeout=60
        )

    def transcribe(self, audio: ValidatedAudio, language: str) -> Transcript:
        hint = language_hint(language)
        options = {"languages": [hint]} if self.model == "gpt-transcribe" else {"language": hint}
        with audio.normalized_path.open("rb") as stream:
            result = self.client.audio.transcriptions.create(
                model=self.model,
                file=("answer.wav", stream, "audio/wav"),
                response_format="json",
                **options,
            )
        data = result.model_dump()
        value = data.get("text")
        if not isinstance(value, str) or len(value) > 10000 or not 1 <= count_words(value) <= 2000:
            raise ValueError("Invalid transcript")
        languages = data.get("languages") or []
        codes = [
            item["code"]
            for item in languages
            if isinstance(item, dict) and isinstance(item.get("code"), str)
        ]
        return Transcript(value, codes, data.get("usage"))

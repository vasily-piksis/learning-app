"""Provider-independent, validated and atomic cache of original YouTube captions."""

import hashlib
import json
import uuid
from threading import RLock

from pydantic import BaseModel, Field, ValidationError, model_validator

LANGUAGE = r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$"
lock = RLock()


class Track(BaseModel):
    language: str = Field(pattern=LANGUAGE, max_length=20)
    name: str = Field(max_length=100)
    is_generated: bool


class Tracks(BaseModel):
    tracks: list[Track] = Field(min_length=1, max_length=500)


class Segment(BaseModel):
    text: str = Field(min_length=1, max_length=100000)
    start: float = Field(ge=0, allow_inf_nan=False)
    duration: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def timing(self):
        if self.start + self.duration > 24 * 60 * 60:
            raise ValueError("Видео превышает ограничение в 24 часа")
        return self


class Transcript(BaseModel):
    language: str = Field(pattern=LANGUAGE, max_length=20)
    is_generated: bool
    segments: list[Segment] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def text_limit(self):
        if sum(len(value.text) for value in self.segments) > 100000:
            raise ValueError(
                "Субтитры превышают ограничение: 100 000 символов или 10 000 фрагментов"
            )
        return self


def cached(settings, key, schema, load, legacy_keys=()):
    root = settings.data_dir / "youtube-cache"

    def filename(value):
        return root / (hashlib.sha256(value.encode()).hexdigest() + ".json")

    path = filename(key)
    with lock:
        root.mkdir(parents=True, exist_ok=True)
        try:
            if path.is_file():
                return schema.model_validate_json(path.read_text()).model_dump()
            retained = next(
                (filename(value) for value in legacy_keys if filename(value).is_file()), None
            )
            value = (
                schema.model_validate_json(retained.read_text())
                if retained
                else schema.model_validate(load())
            ).model_dump()
        except ValidationError:
            raise ValueError("Сохранённые субтитры повреждены или имеют неверный формат") from None
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return value

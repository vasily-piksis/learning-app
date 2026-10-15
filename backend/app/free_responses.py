"""Bounded free-response contracts and pure grading helpers."""

import json
import unicodedata
from bisect import bisect_right
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

WORD_COUNT_VERSION = 1
_PROFILE = json.loads(Path(__file__).with_name("word-count-profile.json").read_text())
WORD_COUNT_UNICODE_VERSION = _PROFILE["unicode_category_version"]
_RANGES = _PROFILE["ranges"]
_STARTS = [row[0] for row in _RANGES]


def _category(char: str) -> str:
    point = ord(char)
    index = bisect_right(_STARTS, point) - 1
    return _RANGES[index][2] if index >= 0 and point <= _RANGES[index][1] else ""


def count_words(text: str) -> int:
    """Count NFC Unicode words without modifying the submitted answer."""
    text = unicodedata.normalize("NFC", text)
    count, active, letter = 0, False, False
    for i, char in enumerate(text):
        category = _category(char)
        if category in {"L", "N"}:
            count += not active
            active, letter = True, category == "L"
        elif category == "M" and active and letter:
            continue
        elif (
            char in "'’\u002d‐‑"
            and active
            and i + 1 < len(text)
            and _category(text[i + 1]) in {"L", "N"}
        ):
            letter = False
        else:
            active, letter = False, False
    return count


Goal = Literal["content", "language"]
Level = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
Identifier = Annotated[str, Field(min_length=1, max_length=80)]
WordBound = Annotated[int, Field(ge=1, le=2000)]
Suggestion = Annotated[str, Field(min_length=1, max_length=500)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FreeResponseSourceRef(Strict):
    """Local leaf contract; schemas.SourceRef retains its existing interface."""

    document_id: int
    page: int


def source_key(source: FreeResponseSourceRef) -> tuple[int, int]:
    return source.document_id, source.page


class SourceFragment(Strict):
    source: FreeResponseSourceRef
    text: str = Field(min_length=1, max_length=4000)


class RubricCriterion(Strict):
    id: Identifier
    label: str = Field(min_length=1, max_length=200)
    weight: int = Field(ge=1, le=100)


class ExpectedPoint(Strict):
    id: Identifier
    text: str = Field(min_length=1, max_length=2000)
    essential: bool
    sources: list[FreeResponseSourceRef] = Field(min_length=1, max_length=20)


class FreeResponseExercise(Strict):
    goal: Goal
    language: str = Field(pattern=r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$", max_length=35)
    level: Level | None
    min_words: WordBound | None = None
    max_words: WordBound | None = None
    model_answer: str = Field(min_length=1, max_length=4000)
    rubric: list[RubricCriterion] = Field(min_length=1, max_length=8)
    expected_points: list[ExpectedPoint] = Field(min_length=1, max_length=12)
    source_fragments: list[SourceFragment] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def coherent_criteria(self):
        if (self.goal == "language") != (self.level is not None):
            raise ValueError("Уровень CEFR обязателен только для языкового задания")
        if (
            self.min_words is not None
            and self.max_words is not None
            and self.min_words > self.max_words
        ):
            raise ValueError("Минимум слов не должен превышать максимум")
        if sum(criterion.weight for criterion in self.rubric) != 100:
            raise ValueError("Сумма весов критериев должна быть 100")
        for ids in (
            [criterion.id for criterion in self.rubric],
            [point.id for point in self.expected_points],
        ):
            if len(ids) != len(set(ids)):
                raise ValueError("Идентификаторы критериев и пунктов не должны повторяться")
        refs = {source_key(fragment.source) for fragment in self.source_fragments}
        if any(
            source_key(source) not in refs
            for point in self.expected_points
            for source in point.sources
        ):
            raise ValueError("Каждому источнику пункта нужен сохранённый фрагмент")
        if sum(len(fragment.text) for fragment in self.source_fragments) > 80000:
            raise ValueError("Сохранённые фрагменты превышают 80000 символов")
        return self


class RubricScore(Strict):
    criterion_id: Identifier
    score: int = Field(ge=0, le=4)
    explanation: str = Field(min_length=1, max_length=2000)


class TextEvidence(Strict):
    kind: Literal["text"]
    source: FreeResponseSourceRef
    quote: str = Field(min_length=1, max_length=4000)


class PointCheck(Strict):
    point_id: Identifier
    met: bool
    evidence: list[TextEvidence] = Field(max_length=20)


class Correction(Strict):
    original: str = Field(min_length=1, max_length=500)
    suggested: str = Field(max_length=500)
    explanation: str = Field(min_length=1, max_length=500)


class EvaluationFeedback(Strict):
    rubric_scores: list[RubricScore] = Field(max_length=8)
    point_checks: list[PointCheck] = Field(max_length=12)
    language_match: bool
    corrections: list[Correction] = Field(max_length=20)
    summary: str = Field(min_length=1, max_length=2000)
    suggestions: list[Suggestion] = Field(max_length=8)


class FreeResponseEvaluation(EvaluationFeedback):
    assessability: Literal["assessable", "insufficient_context"]
    reason: str | None = Field(max_length=2000)

    @model_validator(mode="after")
    def assessability_reason(self):
        if self.assessability == "insufficient_context" and (
            not self.reason or not self.reason.strip()
        ):
            raise ValueError("Недостаточному контексту нужна причина")
        if self.assessability == "assessable" and self.reason is not None:
            raise ValueError("Для проверяемого ответа reason должен быть null")
        return self


class WordLimit(Strict):
    min: WordBound | None
    max: WordBound | None
    met: bool


class EvaluationGrade(EvaluationFeedback):
    score: int = Field(ge=0, le=100)
    correct: bool
    word_count: int = Field(ge=1, le=2000)
    word_count_version: Literal[1] = WORD_COUNT_VERSION
    word_limit: WordLimit


class VoiceMetadata(Strict):
    original_transcript: str = Field(min_length=1, max_length=10000)
    original_word_count: int = Field(ge=1, le=2000)
    was_edited: bool


class StoredEvaluationGrade(EvaluationGrade):
    """Versioned persisted feedback; reading it never regrades an old answer."""

    version: Literal[2]
    evaluation_id: int
    input_method: Literal["text", "voice"]
    voice: VoiceMetadata | None = None

    @model_validator(mode="after")
    def input_metadata(self):
        if (self.input_method == "voice") != (self.voice is not None):
            raise ValueError("Голосовые метаданные нужны только для голосового ответа")
        return self


class InsufficientContext(ValueError):
    """An unassessable response must fail evaluation without creating a grade."""


def validate_evaluation(
    exercise: FreeResponseExercise, answer: str, result: FreeResponseEvaluation
) -> EvaluationGrade:
    """Validate frozen IDs, literal evidence and corrections, then compute the grade."""
    if result.assessability == "insufficient_context":
        raise InsufficientContext(result.reason)
    word_count = count_words(answer)
    if len(answer) > 10000 or not 1 <= word_count <= 2000:
        raise ValueError("Ответ должен содержать до 10000 символов и 2000 слов")
    for given, expected in (
        (
            [score.criterion_id for score in result.rubric_scores],
            [criterion.id for criterion in exercise.rubric],
        ),
        (
            [check.point_id for check in result.point_checks],
            [point.id for point in exercise.expected_points],
        ),
    ):
        if len(given) != len(set(given)) or set(given) != set(expected):
            raise ValueError(
                "Оценка должна содержать каждый сохранённый критерий и пункт ровно один раз"
            )
    points = {point.id: point for point in exercise.expected_points}
    for check in result.point_checks:
        refs = {source_key(source) for source in points[check.point_id].sources}
        for evidence in check.evidence:
            ref = source_key(evidence.source)
            if ref not in refs or not any(
                source_key(fragment.source) == ref and evidence.quote in fragment.text
                for fragment in exercise.source_fragments
            ):
                raise ValueError("Цитата должна точно входить в сохранённый источник этого пункта")
    if any(correction.original not in answer for correction in result.corrections):
        raise ValueError("Исправляемый текст должен точно входить в исходный ответ")
    scores = {score.criterion_id: score.score for score in result.rubric_scores}
    weighted = sum(
        Decimal(criterion.weight * scores[criterion.id]) / 4 for criterion in exercise.rubric
    )
    score = int(weighted.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    word_limit = WordLimit(
        min=exercise.min_words,
        max=exercise.max_words,
        met=(exercise.min_words is None or word_count >= exercise.min_words)
        and (exercise.max_words is None or word_count <= exercise.max_words),
    )
    essential_met = all(
        check.met for check in result.point_checks if points[check.point_id].essential
    )
    return EvaluationGrade(
        **result.model_dump(exclude={"assessability", "reason"}),
        score=score,
        correct=score >= 70 and essential_met and result.language_match and word_limit.met,
        word_count=word_count,
        word_count_version=WORD_COUNT_VERSION,
        word_limit=word_limit,
    )

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from .exercises import (
    EndingExercise,
    GapExercise,
    MatchingExercise,
    OrderingExercise,
    QuestionType,
    WrittenExercise,
    solution_text,
    validate_exercise,
)

Exercise = WrittenExercise | GapExercise | EndingExercise | MatchingExercise | OrderingExercise


class NameBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Укажите название")
        return value


class TopicBody(NameBody):
    subject_id: int


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImageUpdate(Strict):
    asset_id: str | None
    alt: str = Field(default="", max_length=500)


class SourceRef(Strict):
    document_id: int
    page: int


class Extraction(Strict):
    page: int
    text: str
    warnings: list[str]
    is_blank: bool = False
    language: str | None = None


def normalize_correct(value):
    indices = value.correct_indices or (
        [] if value.correct_index is None else [value.correct_index]
    )
    if (
        not indices
        or len(set(indices)) != len(indices)
        or any(not 0 <= index < len(value.options) for index in indices)
        or (value.correct_index is not None and value.correct_index not in indices)
    ):
        raise ValueError("Укажите правильные варианты ответа")
    value.correct_indices = sorted(indices)
    value.correct_index = indices[0] if len(indices) == 1 else None


class GeneratedCard(Strict):
    topic_id: int
    question: str
    answer: str
    mode: Literal["flashcard", "quiz"]
    options: list[str]
    correct_index: StrictInt | None = None
    correct_indices: list[StrictInt] = Field(default_factory=list)
    sources: list[SourceRef]
    language: str | None = None
    question_type: QuestionType = "choice"
    exercise: Exercise | None = None

    @model_validator(mode="after")
    def semantic_fields(self):
        if self.question_type != "choice":
            value = self.exercise.model_dump() if self.exercise is not None else None
            normalized = validate_exercise(self.question_type, value)
            self.exercise = type(self.exercise).model_validate(normalized)
            self.answer = solution_text(self.question_type, normalized)
            if (
                self.mode != "quiz"
                or self.options
                or self.correct_indices
                or self.correct_index is not None
            ):
                raise ValueError("Для этого задания нужен quiz без вариантов ответа")
            if not self.question.strip() or not self.sources:
                raise ValueError("Карточке нужны вопрос и источники")
            return self
        validate_exercise("choice", self.exercise)
        if not self.question.strip() or not self.answer.strip() or not self.sources:
            raise ValueError("Карточке нужны вопрос, ответ и источники")
        if self.mode == "quiz":
            if not 2 <= len(self.options) <= 6 or len(set(self.options)) != len(self.options):
                raise ValueError("Тесту нужны от 2 до 6 различных вариантов")
            normalize_correct(self)
        elif self.options or self.correct_index is not None or self.correct_indices:
            raise ValueError("У флеш-карты нет вариантов ответа")
        return self


class UnsupportedType(Strict):
    question_type: QuestionType
    reason: str = Field(min_length=1, max_length=1000)


class Generated(Strict):
    cards: list[GeneratedCard]
    insufficient_reason: str | None
    unsupported_types: list[UnsupportedType] = Field(default_factory=list)


class QuizOptions(Strict):
    card_id: int
    options: list[str] = Field(min_length=2, max_length=6)
    correct_index: StrictInt | None = None
    correct_indices: list[StrictInt] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_options(self):
        if len(set(self.options)) != len(self.options) or any(
            not option.strip() for option in self.options
        ):
            raise ValueError("Тесту нужны различные варианты и один правильный ответ")
        normalize_correct(self)
        return self


class ExplanationResult(Strict):
    text: str
    example: str | None
    sources: list[SourceRef]


class GenerateBody(Strict):
    topic_ids: list[int] = Field(min_length=1, max_length=30)
    document_ids: list[int] | None = None
    mode: Literal["flashcard", "quiz"] = "quiz"
    target_language: str | None = Field(
        default=None, pattern=r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$", max_length=20
    )
    count: int = Field(ge=1, le=30)
    allow_partial: bool = False
    question_types: list[QuestionType] = Field(
        default_factory=lambda: ["choice"], min_length=1, max_length=6
    )
    practice_goal: Literal["content", "language"] = "content"
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def distinct_topics(self):
        if self.target_language is not None:
            raise ValueError(
                "Учебное содержимое сохраняет исходный язык; перевод не поддерживается"
            )
        if len(set(self.question_types)) != len(self.question_types) or self.count < len(
            self.topic_ids
        ) * len(self.question_types):
            raise ValueError("Выберите разные типы и хотя бы один вопрос на тему и тип")
        if self.practice_goal == "content" and any(
            t in {"ending", "ordering"} for t in self.question_types
        ):
            raise ValueError("Для окончаний и сборки предложения выберите языковую практику")
        if self.mode == "flashcard" and self.question_types != ["choice"]:
            raise ValueError("Специализированные задания создаются в режиме quiz")
        if len(set(self.topic_ids)) != len(self.topic_ids) or self.count < len(self.topic_ids):
            raise ValueError("Выберите разные темы и хотя бы одну карточку на тему")
        if self.document_ids is not None and (
            not self.document_ids or len(set(self.document_ids)) != len(self.document_ids)
        ):
            raise ValueError("Выберите непустой список разных документов")
        return self


class CardEdit(Strict):
    image_updates: dict[Literal["question", "answer"], ImageUpdate] | None = None
    question: str = Field(min_length=1, max_length=10000)
    answer: str | None = Field(default=None, min_length=1, max_length=10000)
    options: list[str] = Field(default_factory=list)
    exercise: Exercise | None = None
    correct_index: StrictInt | None = None
    correct_indices: list[StrictInt] | None = None
    version: int


class SaveCards(BaseModel):
    card_ids: list[int] = Field(min_length=1, max_length=100)


class PrepareOptionsBody(Strict):
    topic_ids: list[StrictInt] = Field(min_length=1, max_length=30)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def unique_topics(self):
        if len(set(self.topic_ids)) != len(self.topic_ids) or any(i < 1 for i in self.topic_ids):
            raise ValueError("Выберите разные темы")
        return self


class SavePreparationBody(Strict):
    card_ids: list[StrictInt] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_cards(self):
        if len(set(self.card_ids)) != len(self.card_ids):
            raise ValueError("Выберите разные вопросы")
        return self

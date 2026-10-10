from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class SourceRef(Strict):
    document_id: int
    page: int


class Extraction(Strict):
    page: int
    text: str
    warnings: list[str]
    is_blank: bool = False


class GeneratedCard(Strict):
    topic_id: int
    question: str
    answer: str
    mode: Literal["flashcard", "quiz"]
    options: list[str]
    correct_index: int | None
    sources: list[SourceRef]

    @model_validator(mode="after")
    def semantic_fields(self):
        if not self.question.strip() or not self.answer.strip() or not self.sources:
            raise ValueError("Карточке нужны вопрос, ответ и источники")
        if self.mode == "quiz":
            if not 2 <= len(self.options) <= 6 or len(set(self.options)) != len(self.options):
                raise ValueError("Тесту нужны от 2 до 6 различных вариантов")
            if self.correct_index is None or not 0 <= self.correct_index < len(self.options):
                raise ValueError("Тесту нужен ровно один правильный вариант")
        elif self.options or self.correct_index is not None:
            raise ValueError("У флеш-карты нет вариантов ответа")
        return self


class Generated(Strict):
    cards: list[GeneratedCard]
    insufficient_reason: str | None


class ExplanationResult(Strict):
    text: str
    example: str | None
    sources: list[SourceRef]


class GenerateBody(BaseModel):
    topic_ids: list[int] = Field(min_length=1, max_length=30)
    document_ids: list[int] | None = None
    mode: Literal["flashcard", "quiz"]
    count: int = Field(ge=1, le=30)
    allow_partial: bool = False

    @model_validator(mode="after")
    def distinct_topics(self):
        if len(set(self.topic_ids)) != len(self.topic_ids) or self.count < len(self.topic_ids):
            raise ValueError("Выберите разные темы и хотя бы одну карточку на тему")
        if self.document_ids is not None and (
            not self.document_ids or len(set(self.document_ids)) != len(self.document_ids)
        ):
            raise ValueError("Выберите непустой список разных документов")
        return self


class CardEdit(BaseModel):
    question: str = Field(min_length=1, max_length=10000)
    answer: str = Field(min_length=1, max_length=10000)
    options: list[str]
    correct_index: int | None
    version: int


class SaveCards(BaseModel):
    card_ids: list[int] = Field(min_length=1, max_length=100)

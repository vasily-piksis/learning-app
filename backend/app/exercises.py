"""Typed learning exercises, stable private snapshots and deterministic grading."""

import copy
import random
import secrets
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

QuestionType = Literal["choice", "written", "gap", "ending", "matching", "ordering"]
QUESTION_TYPES = ("choice", "written", "gap", "ending", "matching", "ordering")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def normalize_text(value: str, case_sensitive: bool = False) -> str:
    value = unicodedata.normalize("NFC", " ".join(value.split()))
    return value if case_sensitive else unicodedata.normalize("NFC", value.casefold())


def unique_answers(values, case_sensitive=False, limit=1000):
    normalized = [normalize_text(value, case_sensitive) for value in values]
    if any(not value or len(raw) > limit for value, raw in zip(normalized, values, strict=True)):
        raise ValueError("Ответы должны быть непустыми и укладываться в ограничение длины")
    if len(set(normalized)) != len(normalized):
        raise ValueError("Допустимые ответы не должны повторяться")
    return normalized


class WrittenExercise(Strict):
    accepted_answers: list[str] = Field(min_length=1, max_length=10)
    case_sensitive: bool = False

    @model_validator(mode="after")
    def valid(self):
        unique_answers(self.accepted_answers, self.case_sensitive)
        return self


class TextSegment(Strict):
    text: str = Field(max_length=10000)


class GapSegment(Strict):
    gap_id: str = Field(min_length=1, max_length=80)


class Gap(Strict):
    id: str = Field(min_length=1, max_length=80)
    accepted_answers: list[str] = Field(min_length=1, max_length=10)


class GapExercise(Strict):
    segments: list[TextSegment | GapSegment] = Field(min_length=1, max_length=30)
    gaps: list[Gap] = Field(min_length=1, max_length=6)
    case_sensitive: bool = False
    accepted_combinations: list[list[str]] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def valid(self):
        ids = [gap.id for gap in self.gaps]
        occurrences = [s.gap_id for s in self.segments if isinstance(s, GapSegment)]
        if len(set(ids)) != len(ids) or Counter(ids) != Counter(occurrences):
            raise ValueError("Каждый пропуск должен встречаться ровно один раз")
        answers = [
            set(unique_answers(g.accepted_answers, self.case_sensitive, 200)) for g in self.gaps
        ]
        combinations = []
        for combination in self.accepted_combinations:
            if len(combination) != len(ids):
                raise ValueError("Сочетание должно содержать ответ для каждого пропуска")
            normalized = tuple(normalize_text(v, self.case_sensitive) for v in combination)
            if any(
                value not in allowed for value, allowed in zip(normalized, answers, strict=True)
            ):
                raise ValueError("Сочетание содержит недопустимый ответ")
            combinations.append(normalized)
        if len(set(combinations)) != len(combinations):
            raise ValueError("Сочетания не должны повторяться")
        if any({c[i] for c in combinations} != allowed for i, allowed in enumerate(answers)):
            raise ValueError("Все допустимые ответы должны входить в сочетания")
        return self


class EndingExercise(GapExercise):
    @model_validator(mode="after")
    def one_ending(self):
        if len(self.gaps) != 1:
            raise ValueError("У окончания должен быть ровно один пропуск")
        return self


class Pair(Strict):
    left: str = Field(min_length=1, max_length=200)
    right: str = Field(min_length=1, max_length=200)


class MatchingExercise(Strict):
    pairs: list[Pair] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def unambiguous(self):
        unique_answers([p.left for p in self.pairs], limit=200)
        unique_answers([p.right for p in self.pairs], limit=200)
        return self


class OrderingExercise(Strict):
    tokens: list[str] = Field(min_length=2, max_length=20)
    accepted_orders: list[list[str]] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def same_words(self):
        if any(not v.strip() or len(v) > 100 for v in self.tokens):
            raise ValueError("Слова должны быть непустыми, до 100 символов")
        if any(Counter(order) != Counter(self.tokens) for order in self.accepted_orders):
            raise ValueError("Допустимый порядок должен содержать те же слова")
        if len({tuple(order) for order in self.accepted_orders}) != len(self.accepted_orders):
            raise ValueError("Допустимые порядки не должны повторяться")
        return self


SCHEMAS = {
    "written": WrittenExercise,
    "gap": GapExercise,
    "ending": EndingExercise,
    "matching": MatchingExercise,
    "ordering": OrderingExercise,
}


def validate_exercise(question_type: QuestionType, value: dict | None) -> dict | None:
    if question_type == "choice":
        if value is not None:
            raise ValueError("У выбора ответа нет отдельного упражнения")
        return None
    if question_type not in SCHEMAS:
        raise ValueError("Неизвестный тип задания")
    return SCHEMAS[question_type].model_validate(value).model_dump()


def solution_text(question_type: QuestionType, exercise: dict) -> str:
    if question_type == "written":
        return " / ".join(exercise["accepted_answers"])
    if question_type in {"gap", "ending"}:
        values = dict(
            zip(
                (g["id"] for g in exercise["gaps"]),
                exercise["accepted_combinations"][0],
                strict=True,
            )
        )
        return "".join(
            s["text"] if "text" in s else values[s["gap_id"]] for s in exercise["segments"]
        )
    if question_type == "matching":
        return "\n".join(f"{p['left']} → {p['right']}" for p in exercise["pairs"])
    if question_type == "ordering":
        return " / ".join(" ".join(order) for order in exercise["accepted_orders"])
    raise ValueError("Для этого типа решение хранится в answer")


def original_exercise(snapshot: dict) -> dict | None:
    value = copy.deepcopy(snapshot.get("exercise"))
    kind = snapshot.get("question_type", "choice")
    if kind == "matching" and value and "solution" in value:
        left = {v["id"]: v["text"] for v in value["left"]}
        right = {v["id"]: v["text"] for v in value["right"]}
        return {
            "pairs": [
                {"left": left[p["left_id"]], "right": right[p["right_id"]]}
                for p in value["solution"]
            ]
        }
    if kind == "ordering" and value and isinstance(value["tokens"][0], dict):
        value["tokens"] = [v["text"] for v in value["tokens"]]
    return value


def build_snapshot(card: dict) -> dict:
    snapshot = copy.deepcopy(card)
    kind = snapshot.get("question_type", "choice")
    value = validate_exercise(kind, original_exercise(snapshot))
    snapshot.update(question_type=kind, snapshot_version=2, exercise=value)
    if kind == "matching":
        left, right, solution = [], [], []
        for pair in value["pairs"]:
            l_id, r_id = secrets.token_hex(12), secrets.token_hex(12)
            left.append({"id": l_id, "text": pair["left"]})
            right.append({"id": r_id, "text": pair["right"]})
            solution.append({"left_id": l_id, "right_id": r_id})
        random.SystemRandom().shuffle(left)
        random.SystemRandom().shuffle(right)
        snapshot["exercise"] = {"left": left, "right": right, "solution": solution}
    elif kind == "ordering":
        tokens = [{"id": secrets.token_hex(12), "text": text} for text in value["tokens"]]
        random.SystemRandom().shuffle(tokens)
        snapshot["exercise"] = {"tokens": tokens, "accepted_orders": value["accepted_orders"]}
    return snapshot


def public_exercise(snapshot: dict, revealed: bool) -> dict:
    permitted = {
        "id",
        "job_id",
        "topic_id",
        "question",
        "answer",
        "language",
        "target_language",
        "mode",
        "options",
        "correct_indices",
        "correct_index",
        "multiple_answers",
        "version",
        "status",
        "sources",
        "question_type",
        "snapshot_version",
        "exercise",
    }
    result = copy.deepcopy({key: value for key, value in snapshot.items() if key in permitted})
    result["sources"] = [
        {k: v for k, v in s.items() if k != "text"} for s in result.get("sources", [])
    ]
    if revealed:
        return result
    for key in ("answer", "correct_index", "correct_indices"):
        result.pop(key, None)
    kind, value = snapshot.get("question_type", "choice"), snapshot.get("exercise")
    if kind == "written":
        result["exercise"] = {"case_sensitive": value["case_sensitive"]}
    elif kind in {"gap", "ending"}:
        result["exercise"] = {
            "segments": value["segments"],
            "gaps": [{"id": g["id"]} for g in value["gaps"]],
            "case_sensitive": value["case_sensitive"],
        }
    elif kind == "matching":
        result["exercise"] = {"left": value["left"], "right": value["right"]}
    elif kind == "ordering":
        result["exercise"] = {"tokens": value["tokens"]}
    return result


class InvalidSubmission(ValueError):
    pass


@dataclass
class GradeResult:
    correct: bool
    parts: list[dict] = field(default_factory=list)
    message_code: str | None = None


def canonical_submission(snapshot: dict, submission: dict) -> dict:
    kind, value = snapshot.get("question_type", "choice"), snapshot.get("exercise")
    data = {k: v for k, v in submission.items() if v is not None}
    if snapshot.get("mode") == "flashcard":
        if set(data) != {"remembered"} or type(data["remembered"]) is not bool:
            raise InvalidSubmission("Отметьте, помните ли ответ")
        return data
    if kind == "choice":
        from .quiz import correct_indices

        if set(data) not in ({"choice"}, {"choices"}):
            raise InvalidSubmission("Выберите варианты ответа")
        choices = data.get("choices", [data.get("choice")])
        if not isinstance(choices, list) or not choices or any(type(i) is not int for i in choices):
            raise InvalidSubmission("Недопустимые варианты ответа")
        if len(set(choices)) != len(choices) or any(
            not 0 <= i < len(snapshot["options"]) for i in choices
        ):
            raise InvalidSubmission("Недопустимые варианты ответа")
        if len(correct_indices(snapshot)) == 1 and len(choices) != 1:
            raise InvalidSubmission("Выберите один вариант")
        return {"choices": sorted(choices)}
    expected = {
        "written": "text",
        "gap": "gap_answers",
        "ending": "gap_answers",
        "matching": "pairs",
        "ordering": "order",
    }.get(kind)
    if expected is None or set(data) != {expected}:
        raise InvalidSubmission("Ответ не соответствует типу задания")
    answer = data[expected]
    if kind == "written":
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 1000:
            raise InvalidSubmission("Напишите ответ до 1000 символов")
    elif kind in {"gap", "ending"}:
        ids = {g["id"] for g in value["gaps"]}
        if (
            not isinstance(answer, dict)
            or set(answer) != ids
            or any(not isinstance(v, str) or not v.strip() or len(v) > 200 for v in answer.values())
        ):
            raise InvalidSubmission("Заполните все пропуски допустимым текстом")
        answer = dict(sorted(answer.items()))
    elif kind == "matching":
        left, right = {v["id"] for v in value["left"]}, {v["id"] for v in value["right"]}
        if (
            not isinstance(answer, list)
            or len(answer) != len(left)
            or any(
                not isinstance(p, dict)
                or set(p) != {"left_id", "right_id"}
                or not isinstance(p["left_id"], str)
                or not isinstance(p["right_id"], str)
                for p in answer
            )
        ):
            raise InvalidSubmission("Сопоставьте все пары")
        if {p["left_id"] for p in answer} != left or {p["right_id"] for p in answer} != right:
            raise InvalidSubmission("Каждый элемент можно использовать ровно один раз")
        answer = sorted(answer, key=lambda p: p["left_id"])
    elif kind == "ordering":
        ids = {v["id"] for v in value["tokens"]}
        if (
            not isinstance(answer, list)
            or any(not isinstance(v, str) for v in answer)
            or len(answer) != len(ids)
            or set(answer) != ids
        ):
            raise InvalidSubmission("Используйте все слова ровно один раз")
    return {expected: answer}


def grade_answer(snapshot: dict, submission: dict) -> GradeResult:
    data = canonical_submission(snapshot, submission)
    if snapshot.get("mode") == "flashcard":
        return GradeResult(data["remembered"])
    kind, value = snapshot.get("question_type", "choice"), snapshot.get("exercise")
    if kind == "choice":
        from .quiz import correct_indices

        return GradeResult(set(data["choices"]) == set(correct_indices(snapshot)))
    if kind == "written":

        def normalize(v):
            return normalize_text(v, value["case_sensitive"])

        return GradeResult(
            normalize(data["text"]) in [normalize(v) for v in value["accepted_answers"]]
        )
    if kind in {"gap", "ending"}:
        given = [
            normalize_text(data["gap_answers"][g["id"]], value["case_sensitive"])
            for g in value["gaps"]
        ]
        combinations = [
            [normalize_text(v, value["case_sensitive"]) for v in c]
            for c in value["accepted_combinations"]
        ]
        closest = min(
            combinations, key=lambda c: sum(a != b for a, b in zip(given, c, strict=True))
        )
        parts = [
            {"id": gap["id"], "correct": a == b}
            for gap, a, b in zip(value["gaps"], given, closest, strict=True)
        ]
        incompatible = given not in combinations and all(
            given[i] in {c[i] for c in combinations} for i in range(len(given))
        )
        return GradeResult(
            given in combinations, parts, "incompatible_combination" if incompatible else None
        )
    if kind == "matching":
        solution = {p["left_id"]: p["right_id"] for p in value["solution"]}
        parts = [
            {"id": p["left_id"], "correct": p["right_id"] == solution[p["left_id"]]}
            for p in data["pairs"]
        ]
        return GradeResult(all(p["correct"] for p in parts), parts)
    texts = {v["id"]: v["text"] for v in value["tokens"]}
    return GradeResult([texts[v] for v in data["order"]] in value["accepted_orders"])

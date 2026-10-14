import json
import unicodedata

import pytest
from exercise_cases import CASES, exercise_module


def snapshot(kind, value=None):
    return exercise_module().build_snapshot(
        {
            "id": 1,
            "question_type": kind,
            "exercise": value or CASES[kind],
            "question": "Exercise",
            "answer": "SECRET ANSWER",
            "sources": [],
            "mode": "quiz",
        }
    )


def test_written_preserves_diacritics_and_unicode_equivalence():
    e = exercise_module()
    assert e.normalize_text("  ŻÓŁĆ  ") == "żółć"
    s = snapshot("written", {"accepted_answers": ["żółć"], "case_sensitive": False})
    assert e.grade_answer(s, {"text": unicodedata.normalize("NFD", "ŻÓŁĆ")}).correct
    assert not e.grade_answer(s, {"text": "zolc"}).correct
    assert e.grade_answer(snapshot("written"), {"text": "LENTELĖ"}).correct


def test_dependent_gaps_report_incompatible_combination_and_nearest_parts():
    e = exercise_module()
    s = snapshot("gap")
    assert e.grade_answer(s, {"gap_answers": {"subject": "We", "verb": "are"}}).correct
    result = e.grade_answer(s, {"gap_answers": {"subject": "I", "verb": "are"}})
    assert not result.correct and result.message_code == "incompatible_combination"
    assert result.parts == [{"id": "subject", "correct": True}, {"id": "verb", "correct": False}]
    with pytest.raises(e.InvalidSubmission):
        e.grade_answer(s, {"gap_answers": {"subject": "I"}})


def test_matching_uses_hidden_mapping_and_requires_complete_bijection():
    e = exercise_module()
    s = snapshot("matching")
    pairs = s["exercise"]["solution"]
    assert e.grade_answer(s, {"pairs": pairs}).correct
    wrong = [
        {"left_id": pairs[0]["left_id"], "right_id": pairs[1]["right_id"]},
        {"left_id": pairs[1]["left_id"], "right_id": pairs[0]["right_id"]},
    ]
    assert not e.grade_answer(s, {"pairs": wrong}).correct
    with pytest.raises(e.InvalidSubmission):
        e.grade_answer(s, {"pairs": [pairs[0], pairs[0]]})
    public = e.public_exercise(s, False)
    assert len(public["exercise"]["left"]) == 2
    assert "solution" not in public["exercise"] and "pairs" not in public["exercise"]
    assert "SECRET ANSWER" not in json.dumps(public)


def test_ordering_repeated_words_allow_distinct_ids_but_not_duplicate_id():
    e = exercise_module()
    s = snapshot("ordering")
    tokens = s["exercise"]["tokens"]
    ids = {}
    for token in tokens:
        ids.setdefault(token["text"], []).append(token["id"])
    order = [ids["I"][0], ids["think"][0], ids["I"][1], ids["can"][0]]
    assert e.grade_answer(s, {"order": order}).correct
    assert e.grade_answer(s, {"order": [order[2], order[1], order[0], order[3]]}).correct
    with pytest.raises(e.InvalidSubmission):
        e.grade_answer(s, {"order": [order[0], order[1], order[0], order[3]]})
    public = e.public_exercise(s, False)
    assert "accepted_orders" not in public["exercise"]
    repeat = e.build_snapshot(s)
    assert {t["id"] for t in repeat["exercise"]["tokens"]}.isdisjoint({t["id"] for t in tokens})


@pytest.mark.parametrize("kind", ["written", "gap", "ending"])
def test_solution_criteria_are_not_returned_before_reveal(kind):
    e = exercise_module()
    s = snapshot(kind)
    public = e.public_exercise(s, False)
    serialized = json.dumps(public)
    assert "accepted_answers" not in serialized and "accepted_combinations" not in serialized
    assert "answer" not in public
    assert "answer" in e.public_exercise(s, True)


def test_choice_shuffle_remaps_all_correct_answers_without_changing_original(monkeypatch):
    import random

    e = exercise_module()
    monkeypatch.setattr(random.SystemRandom, "shuffle", lambda self, values: values.reverse())
    original = {
        "question_type": "choice",
        "mode": "quiz",
        "exercise": None,
        "options": ["stalas", "lentelė", "namas"],
        "correct_indices": [0, 1],
        "correct_index": None,
        "answer": "stalas / lentelė",
        "sources": [],
    }
    shuffled = e.build_snapshot(original)
    assert shuffled["options"] == ["namas", "lentelė", "stalas"]
    assert shuffled["correct_indices"] == [1, 2] and shuffled["correct_index"] is None
    assert e.grade_answer(shuffled, {"choices": [1, 2]}).correct
    assert not e.grade_answer(shuffled, {"choices": [0, 1]}).correct
    assert original["options"] == ["stalas", "lentelė", "namas"]


def test_legacy_single_correct_choice_is_remapped_in_new_snapshot(monkeypatch):
    import random

    e = exercise_module()
    monkeypatch.setattr(random.SystemRandom, "shuffle", lambda self, values: values.reverse())
    shuffled = e.build_snapshot(
        {
            "mode": "quiz",
            "options": ["correct", "wrong"],
            "correct_index": 0,
            "answer": "correct",
            "sources": [],
        }
    )
    assert shuffled["options"] == ["wrong", "correct"]
    assert shuffled["correct_index"] == 1 and shuffled["correct_indices"] == [1]

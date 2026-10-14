import copy

import pytest
from exercise_cases import CASES, GAP, exercise_module


@pytest.mark.parametrize("kind", CASES)
def test_supported_exercise_keeps_its_solution(kind):
    e = exercise_module()
    value = e.validate_exercise(kind, CASES[kind])
    assert value == CASES[kind]
    assert e.solution_text(kind, value)


@pytest.mark.parametrize("mutation", ["dead", "duplicate", "missing", "extra_segment"])
def test_dependent_gap_rejects_incoherent_criteria(mutation):
    e = exercise_module()
    value = copy.deepcopy(GAP)
    if mutation == "dead":
        value["gaps"][0]["accepted_answers"].append("You")
    elif mutation == "duplicate":
        value["accepted_combinations"].append(["i", "AM"])
    elif mutation == "missing":
        value["accepted_combinations"][0].pop()
    else:
        value["segments"].append({"gap_id": "subject"})
    with pytest.raises(ValueError):
        e.validate_exercise("gap", value)


def test_ending_rejects_multiple_slots_and_zero_ending():
    e = exercise_module()
    with pytest.raises(ValueError):
        e.validate_exercise("ending", GAP)
    value = copy.deepcopy(CASES["ending"])
    value["gaps"][0]["accepted_answers"] = [""]
    value["accepted_combinations"] = [[""]]
    with pytest.raises(ValueError):
        e.validate_exercise("ending", value)


def test_matching_rejects_normalized_ambiguity_and_unknown_fields():
    e = exercise_module()
    value = {"pairs": [{"left": "a", "right": "x"}, {"left": " A ", "right": "y"}]}
    with pytest.raises(ValueError):
        e.validate_exercise("matching", value)
    with pytest.raises(ValueError):
        e.validate_exercise("written", {**CASES["written"], "ignored": True})


def test_ordering_requires_same_multiset_and_choice_has_no_exercise():
    e = exercise_module()
    with pytest.raises(ValueError):
        e.validate_exercise("ordering", {"tokens": ["a", "a"], "accepted_orders": [["a", "b"]]})
    assert e.validate_exercise("choice", None) is None
    with pytest.raises(ValueError):
        e.validate_exercise("choice", CASES["written"])


@pytest.mark.parametrize(
    "kind,field,values",
    [
        ("written", "accepted_answers", ["x"] * 11),
        ("matching", "pairs", [{"left": "a", "right": "b"}]),
        ("ordering", "tokens", ["x"]),
        ("gap", "gaps", []),
    ],
)
def test_exercise_size_limits_reject_invalid_question(kind, field, values):
    e = exercise_module()
    value = copy.deepcopy(CASES[kind])
    value[field] = values
    with pytest.raises(ValueError):
        e.validate_exercise(kind, value)

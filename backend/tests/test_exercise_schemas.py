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


def test_gap_complete_solution_includes_every_approved_combination():
    from app.exercises import solution_text

    assert (
        solution_text(
            "gap",
            {
                "segments": [{"gap_id": "subject"}, {"text": " "}, {"gap_id": "verb"}],
                "gaps": [
                    {"id": "subject", "accepted_answers": ["I", "we"]},
                    {"id": "verb", "accepted_answers": ["am", "are"]},
                ],
                "case_sensitive": False,
                "accepted_combinations": [["I", "am"], ["we", "are"]],
            },
        )
        == "I am / we are"
    )


@pytest.mark.parametrize(
    "segments",
    [
        [{"gap_id": "ending"}],
        [{"text": "Choose an ending: "}, {"gap_id": "ending"}],
        [{"text": ""}, {"gap_id": "ending"}],
    ],
)
def test_ending_requires_a_visible_word_stem_directly_before_the_slot(segments):
    from app.exercises import validate_exercise

    with pytest.raises(ValueError):
        validate_exercise(
            "ending",
            {
                "segments": segments,
                "gaps": [{"id": "ending", "accepted_answers": ["u"]}],
                "accepted_combinations": [["u"]],
                "case_sensitive": False,
            },
        )


@pytest.mark.parametrize(
    "tokens,orders",
    [
        (["a", "a"], [["a", "a"]]),
        (["a", "b"], [["a", "b"], ["b", "a"]]),
        (["a", "a", "b"], [["a", "a", "b"], ["a", "b", "a"], ["b", "a", "a"]]),
    ],
)
def test_ordering_rejects_every_distinguishable_order_accepted(tokens, orders):
    with pytest.raises(ValueError):
        exercise_module().validate_exercise(
            "ordering", {"tokens": tokens, "accepted_orders": orders}
        )


def test_ordering_identity_shuffle_uses_bounded_distinct_fallback(monkeypatch):
    from itertools import permutations

    from app import exercises

    monkeypatch.setattr(exercises.random.SystemRandom, "shuffle", lambda self, values: None)
    for tokens in (["a", "a", "b"], ["a", "b", "c"]):
        orders = sorted(set(permutations(tokens)))
        accepted = [list(order) for order in orders[:-1]]
        value = {"tokens": tokens, "accepted_orders": accepted}
        card = {"question_type": "ordering", "exercise": value}
        frozen = exercises.build_snapshot(card)
        assert [token["text"] for token in frozen["exercise"]["tokens"]] == list(orders[-1])
        assert exercises.original_exercise(frozen)["accepted_orders"] == accepted


def test_ordering_large_duplicate_bank_has_bounded_fallback(monkeypatch):
    from app import exercises

    monkeypatch.setattr(exercises.random.SystemRandom, "shuffle", lambda self, values: None)
    orders = [["a"] * position + ["b"] + ["a"] * (19 - position) for position in range(19, 14, -1)]
    frozen = exercises.build_snapshot(
        {"question_type": "ordering", "exercise": {"tokens": orders[0], "accepted_orders": orders}}
    )
    assert [token["text"] for token in frozen["exercise"]["tokens"]] == ["a"] * 14 + ["b"] + [
        "a"
    ] * 5

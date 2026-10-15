"""Pure contracts: no model, database, or network is needed to grade a result."""

import pytest
from app import exercises


def free_snapshot():
    return {
        "question_type": "free_response",
        "mode": "quiz",
        "exercise": {"model_answer": "An example, never an exact-match answer."},
    }


def test_free_submission_preserves_raw_text_and_audio_reference():
    answer = "  Ąžuolas 😀\n"
    assert exercises.canonical_submission(free_snapshot(), {"free_text": answer}) == {
        "free_text": answer,
        "audio_answer_id": None,
    }
    assert exercises.canonical_submission(
        free_snapshot(), {"free_text": answer, "audio_answer_id": "audio-1"}
    ) == {"free_text": answer, "audio_answer_id": "audio-1"}


@pytest.mark.parametrize("answer", ["", "... 😀", "x" * 10001, "a " * 2001, 123])
def test_free_submission_rejects_technical_limits_before_evaluation(answer):
    with pytest.raises(exercises.InvalidSubmission):
        exercises.canonical_submission(free_snapshot(), {"free_text": answer})


@pytest.mark.parametrize(
    "payload",
    [
        {"free_text": "word", "_grading": None},
        {"free_text": "word", "_grading": {"correct": True}},
        {"free_text": "word", "text": "word"},
        {"free_text": "word", "audio_answer_id": 1},
        {"free_text": "word", "audio_answer_id": ""},
    ],
)
def test_free_submission_rejects_client_grading_and_extra_fields(payload):
    with pytest.raises(exercises.InvalidSubmission):
        exercises.canonical_submission(free_snapshot(), payload)


def test_free_response_requires_evaluation_even_for_model_answer():
    with pytest.raises(exercises.RequiresEvaluation):
        exercises.grade_answer(
            free_snapshot(), {"free_text": "An example, never an exact-match answer."}
        )
    assert exercises.solution_text("free_response", free_snapshot()["exercise"]) == (
        "An example, never an exact-match answer."
    )


def test_old_written_answer_limit_and_payload_are_not_expanded():
    snapshot = {"question_type": "written", "mode": "quiz", "exercise": {}}
    with pytest.raises(exercises.InvalidSubmission):
        exercises.canonical_submission(snapshot, {"free_text": "word"})
    with pytest.raises(exercises.InvalidSubmission):
        exercises.canonical_submission(snapshot, {"text": "x" * 1001})


def exercise_data():
    return {
        "goal": "content",
        "language": "lt",
        "level": None,
        "min_words": None,
        "max_words": None,
        "model_answer": "Ąžuolas yra medis.",
        "rubric": [
            {"id": "facts", "label": "Facts", "weight": 50},
            {"id": "explanation", "label": "Explanation", "weight": 50},
        ],
        "expected_points": [
            {
                "id": "tree",
                "text": "Oak is a tree",
                "essential": True,
                "sources": [{"document_id": 1, "page": 2}],
            },
        ],
        "source_fragments": [
            {"source": {"document_id": 1, "page": 2}, "text": "Ąžuolas yra medis."},
        ],
    }


def evaluation_data():
    return {
        "assessability": "assessable",
        "reason": None,
        "rubric_scores": [
            {"criterion_id": "facts", "score": 3, "explanation": "Facts covered"},
            {"criterion_id": "explanation", "score": 4, "explanation": "Clear explanation"},
        ],
        "point_checks": [
            {
                "point_id": "tree",
                "met": True,
                "evidence": [
                    {"kind": "text", "source": {"document_id": 1, "page": 2}, "quote": "yra medis"},
                ],
            }
        ],
        "language_match": True,
        "corrections": [{"original": "medis", "suggested": "medis", "explanation": "Correct"}],
        "summary": "Good answer",
        "suggestions": ["Add detail"],
    }


def models(exercise=None, result=None):
    from app import free_responses as fr

    return (
        fr.FreeResponseExercise.model_validate(exercise or exercise_data()),
        fr.FreeResponseEvaluation.model_validate(result or evaluation_data()),
    )


def test_free_exercise_routes_through_closed_schema_and_generated_card():
    from app.schemas import GeneratedCard

    value = exercises.validate_exercise("free_response", exercise_data())
    assert value["min_words"] is None and value["max_words"] is None
    card = GeneratedCard.model_validate(
        {
            "topic_id": 1,
            "question": "What is an oak?",
            "answer": "ignored",
            "mode": "quiz",
            "options": [],
            "sources": [{"document_id": 1, "page": 2}],
            "question_type": "free_response",
            "exercise": exercise_data(),
        }
    )
    assert card.answer == "Ąžuolas yra medis."


@pytest.mark.parametrize(
    "field,value",
    [
        ("goal", "other"),
        ("level", "B1"),
        ("language", "Lithuanian"),
        ("min_words", 0),
        ("max_words", 2001),
        ("min_words", True),
        ("rubric", []),
        ("expected_points", []),
        ("source_fragments", []),
        ("model_answer", "x" * 4001),
        ("unexpected", True),
    ],
)
def test_exercise_rejects_invalid_contract_fields(field, value):
    from app import free_responses as fr

    data = exercise_data()
    data[field] = value
    with pytest.raises(ValueError):
        fr.FreeResponseExercise.model_validate(data)


def test_language_goal_requires_explicit_cefr_and_content_has_no_level():
    from app import free_responses as fr

    data = exercise_data()
    data["goal"] = "language"
    with pytest.raises(ValueError):
        fr.FreeResponseExercise.model_validate(data)
    for level in ["A1", "A2", "B1", "B2", "C1", "C2"]:
        data["level"] = level
        assert fr.FreeResponseExercise.model_validate(data).level == level
    data["level"] = "A0"
    with pytest.raises(ValueError):
        fr.FreeResponseExercise.model_validate(data)


@pytest.mark.parametrize(
    "mutation",
    [
        "range",
        "weight",
        "rubric_id",
        "point_id",
        "fragment_length",
        "fragment_count",
        "rubric_count",
        "point_count",
        "missing_fragment_ref",
        "extra_fragment_field",
    ],
)
def test_exercise_rejects_incoherent_or_unbounded_private_criteria(mutation):
    import copy

    from app import free_responses as fr

    data = exercise_data()
    if mutation == "range":
        data.update(min_words=5, max_words=4)
    elif mutation == "weight":
        data["rubric"][0]["weight"] = 49
    elif mutation == "rubric_id":
        data["rubric"][1]["id"] = "facts"
    elif mutation == "point_id":
        data["expected_points"] *= 2
    elif mutation == "fragment_length":
        data["source_fragments"][0]["text"] = "x" * 4001
    elif mutation == "fragment_count":
        data["source_fragments"] *= 21
    elif mutation == "rubric_count":
        data["rubric"] *= 5
    elif mutation == "point_count":
        data["expected_points"] *= 13
    elif mutation == "missing_fragment_ref":
        data["expected_points"][0]["sources"][0]["page"] = 3
    else:
        data["source_fragments"][0]["source"]["text"] = "not a source ref"
    with pytest.raises(ValueError):
        fr.FreeResponseExercise.model_validate(copy.deepcopy(data))


def test_maximum_frozen_fragments_are_accepted_without_truncation():
    from app import free_responses as fr

    data = exercise_data()
    data["source_fragments"] = [
        {"source": {"document_id": 1, "page": 2}, "text": "𐐀" * 4000} for _ in range(20)
    ]
    result = fr.FreeResponseExercise.model_validate(data)
    assert sum(len(fragment.text) for fragment in result.source_fragments) == 80000


def test_public_free_exercise_whitelists_metadata_until_feedback():
    value = {
        "question_type": "free_response",
        "mode": "quiz",
        "exercise": {**exercise_data(), "prompt": "secret prompt"},
        "answer": "secret answer",
        "sources": [{"document_id": 1, "page": 2, "text": "secret"}],
    }
    public = exercises.public_exercise(value, False)
    assert public["exercise"] == {
        "goal": "content",
        "language": "lt",
        "level": None,
        "min_words": None,
        "max_words": None,
    }
    assert "answer" not in public and "text" not in public["sources"][0]
    revealed = exercises.public_exercise(value, True)
    assert revealed["exercise"]["model_answer"] == "Ąžuolas yra medis."
    assert "source_fragments" not in revealed["exercise"]
    assert "prompt" not in revealed["exercise"]


def test_server_computes_half_up_score_and_keeps_rubric_and_raw_answer():
    from app import free_responses as fr

    exercise, result = models()
    original = exercise.model_dump()
    grade = fr.validate_evaluation(exercise, "  Ąžuolas yra medis.\n", result)
    assert grade.score == 88 and grade.correct is True
    assert grade.word_count == 3 and grade.word_count_version == 1
    assert grade.word_limit.model_dump() == {"min": None, "max": None, "met": True}
    assert exercise.model_dump() == original


@pytest.mark.parametrize("mutation", ["score", "essential", "language", "min_words", "max_words"])
def test_correctness_requires_score_essential_language_and_word_range(mutation):
    from app import free_responses as fr

    data, result = exercise_data(), evaluation_data()
    if mutation == "score":
        result["rubric_scores"][0]["score"] = 0
    elif mutation == "essential":
        result["point_checks"][0]["met"] = False
    elif mutation == "language":
        result["language_match"] = False
    elif mutation == "min_words":
        data["min_words"] = 4
    else:
        data["max_words"] = 2
    exercise, evaluation = models(data, result)
    grade = fr.validate_evaluation(exercise, "Ąžuolas yra medis.", evaluation)
    assert not grade.correct
    if mutation in {"min_words", "max_words"}:
        assert grade.score == 88 and not grade.word_limit.met
        assert (
            exercises.canonical_submission(
                {"question_type": "free_response", "mode": "quiz", "exercise": data},
                {"free_text": "Ąžuolas yra medis."},
            )["free_text"]
            == "Ąžuolas yra medis."
        )


def test_threshold_seventy_and_nonessential_unmet_point():
    from app import free_responses as fr

    data, result = exercise_data(), evaluation_data()
    data["rubric"][0]["weight"], data["rubric"][1]["weight"] = 20, 80
    result["rubric_scores"][0]["score"], result["rubric_scores"][1]["score"] = 2, 3
    data["expected_points"][0]["essential"] = False
    result["point_checks"][0].update(met=False, evidence=[])
    exercise, evaluation = models(data, result)
    grade = fr.validate_evaluation(exercise, "Ąžuolas yra medis.", evaluation)
    assert grade.score == 70 and grade.correct


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_criterion",
        "missing_criterion",
        "duplicate_criterion",
        "unknown_point",
        "missing_point",
        "duplicate_point",
        "correction",
        "foreign_ref",
        "false_quote",
        "another_point_source",
    ],
)
def test_evaluation_rejects_changed_ids_forged_quotes_and_foreign_sources(mutation):
    from app import free_responses as fr

    data, result = exercise_data(), evaluation_data()
    if mutation == "unknown_criterion":
        result["rubric_scores"][0]["criterion_id"] = "made-up"
    elif mutation == "missing_criterion":
        result["rubric_scores"].pop()
    elif mutation == "duplicate_criterion":
        result["rubric_scores"].append(result["rubric_scores"][0])
    elif mutation == "unknown_point":
        result["point_checks"][0]["point_id"] = "made-up"
    elif mutation == "missing_point":
        result["point_checks"] = []
    elif mutation == "duplicate_point":
        result["point_checks"] *= 2
    elif mutation == "correction":
        result["corrections"][0]["original"] = "not in answer"
    elif mutation == "foreign_ref":
        result["point_checks"][0]["evidence"][0]["source"]["document_id"] = 2
    elif mutation == "false_quote":
        result["point_checks"][0]["evidence"][0]["quote"] = "not in frozen fragment"
    else:
        data["expected_points"].append(
            {
                "id": "another",
                "text": "Other point",
                "essential": False,
                "sources": [{"document_id": 2, "page": 1}],
            }
        )
        data["source_fragments"].append(
            {"source": {"document_id": 2, "page": 1}, "text": "yra medis"}
        )
        result["point_checks"].append({"point_id": "another", "met": False, "evidence": []})
        result["point_checks"][0]["evidence"][0]["source"] = {"document_id": 2, "page": 1}
    exercise, evaluation = models(data, result)
    with pytest.raises(ValueError):
        fr.validate_evaluation(exercise, "Ąžuolas yra medis.", evaluation)


@pytest.mark.parametrize(
    "field,value",
    [
        ("summary", "x" * 2001),
        ("suggestions", ["x"] * 9),
        ("corrections", [{"original": "x", "suggested": "y", "explanation": "z"}] * 21),
        ("rubric_scores", [{"criterion_id": "facts", "score": 5, "explanation": "bad"}]),
        ("rubric_scores", [{"criterion_id": "facts", "score": 1.5, "explanation": "bad"}]),
        ("language_match", "true"),
        ("unknown", "field"),
    ],
)
def test_model_result_is_closed_and_bounded(field, value):
    from app import free_responses as fr

    data = evaluation_data()
    data[field] = value
    with pytest.raises(ValueError):
        fr.FreeResponseEvaluation.model_validate(data)


def test_insufficient_context_has_no_grade_and_requires_reason():
    from app import free_responses as fr

    data = evaluation_data()
    data.update(
        assessability="insufficient_context",
        reason="Sources conflict",
        rubric_scores=[],
        point_checks=[],
        corrections=[],
    )
    exercise, result = models(result=data)
    with pytest.raises(fr.InsufficientContext, match="Sources conflict"):
        fr.validate_evaluation(exercise, "Ąžuolas yra medis.", result)
    data["reason"] = None
    with pytest.raises(ValueError):
        fr.FreeResponseEvaluation.model_validate(data)


def test_unicode_character_limit_uses_scalars_and_answer_is_not_normalized():
    text = "𐐀" * 10000
    assert exercises.canonical_submission(free_snapshot(), {"free_text": text})["free_text"] == text


def test_stored_v2_keeps_the_computed_grade_and_voice_metadata():
    from app import free_responses as fr

    exercise, result = models()
    grade = fr.validate_evaluation(exercise, "Ąžuolas yra medis.", result)
    stored = fr.StoredEvaluationGrade.model_validate(
        {
            **grade.model_dump(),
            "version": 2,
            "evaluation_id": 42,
            "input_method": "voice",
            "voice": {
                "original_transcript": "Ąžuolas medis.",
                "original_word_count": 2,
                "was_edited": True,
            },
        }
    )
    assert stored.score == 88 and stored.voice.original_word_count == 2
    assert stored.model_dump()["word_limit"] == {"min": None, "max": None, "met": True}
    for update in [{"version": 1}, {"score": 101}, {"input_method": "voice", "voice": None}]:
        with pytest.raises(ValueError):
            fr.StoredEvaluationGrade.model_validate({**stored.model_dump(), **update})


@pytest.mark.parametrize(
    "mutation",
    ["quote_empty", "quote_length", "evidence_count", "correction_length", "suggestion_length"],
)
def test_nested_model_feedback_bounds(mutation):
    from app import free_responses as fr

    data = evaluation_data()
    if mutation == "quote_empty":
        data["point_checks"][0]["evidence"][0]["quote"] = ""
    elif mutation == "quote_length":
        data["point_checks"][0]["evidence"][0]["quote"] = "x" * 4001
    elif mutation == "evidence_count":
        data["point_checks"][0]["evidence"] *= 21
    elif mutation == "correction_length":
        data["corrections"][0]["original"] = "x" * 501
    else:
        data["suggestions"] = ["x" * 501]
    with pytest.raises(ValueError):
        fr.FreeResponseEvaluation.model_validate(data)


def test_empty_evidence_is_allowed_for_positive_check_and_ranges_default_null():
    from app import free_responses as fr

    data, result = exercise_data(), evaluation_data()
    data.pop("min_words")
    data.pop("max_words")
    result["point_checks"][0]["evidence"] = []
    exercise, evaluation = models(data, result)
    grade = fr.validate_evaluation(exercise, "Ąžuolas yra medis.", evaluation)
    assert grade.correct and grade.word_limit.min is None and grade.word_limit.max is None


def test_persisted_v2_read_does_not_recompute_correctness():
    from app import free_responses as fr

    exercise, result = models()
    grade = fr.validate_evaluation(exercise, "Ąžuolas yra medis.", result)
    stored = {
        **grade.model_dump(),
        "version": 2,
        "evaluation_id": 42,
        "input_method": "text",
        "voice": None,
    }
    # A later rubric or policy cannot alter this already stored grade.
    stored.update(score=69, correct=True)
    assert fr.StoredEvaluationGrade.model_validate(stored).correct is True

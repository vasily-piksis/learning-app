WRITTEN = {"accepted_answers": ["stalas", "lentelė"], "case_sensitive": False}
GAP = {
    "segments": [{"gap_id": "subject"}, {"text": " "}, {"gap_id": "verb"}],
    "gaps": [
        {"id": "subject", "accepted_answers": ["I", "We"]},
        {"id": "verb", "accepted_answers": ["am", "are"]},
    ],
    "case_sensitive": False,
    "accepted_combinations": [["I", "am"], ["We", "are"]],
}
ENDING = {
    "segments": [{"text": "Su draug"}, {"gap_id": "ending"}],
    "gaps": [{"id": "ending", "accepted_answers": ["u"]}],
    "case_sensitive": False,
    "accepted_combinations": [["u"]],
}
MATCHING = {"pairs": [{"left": "stalas", "right": "table"}, {"left": "namas", "right": "house"}]}
ORDERING = {"tokens": ["I", "think", "I", "can"], "accepted_orders": [["I", "think", "I", "can"]]}
CASES = {
    "written": WRITTEN,
    "gap": GAP,
    "ending": ENDING,
    "matching": MATCHING,
    "ordering": ORDERING,
}


def exercise_module():
    import importlib
    import importlib.util

    assert importlib.util.find_spec("app.exercises") is not None, "Exercise grading feature missing"
    return importlib.import_module("app.exercises")

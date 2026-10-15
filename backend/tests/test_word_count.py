import json
from pathlib import Path

import pytest
from app import free_responses

FIXTURE = json.loads((Path(__file__).parents[2] / "tests/fixtures/word-count-v1.json").read_text())


@pytest.mark.parametrize("case", FIXTURE["cases"])
def test_shared_unicode_word_counts(case):
    assert free_responses.count_words(case["text"]) == case["count"]


def test_counter_version_matches_shared_fixture():
    assert free_responses.WORD_COUNT_VERSION == FIXTURE["version"]
    assert free_responses.WORD_COUNT_UNICODE_VERSION == FIXTURE["unicode_category_version"]

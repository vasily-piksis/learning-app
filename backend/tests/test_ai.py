from types import SimpleNamespace
import pytest
from app.schemas import Extraction


def test_typed_ai_refusal_and_incomplete_are_errors(tmp_path):
    from app.ai import AI, AIError
    from app.config import Settings
    class Transport:
        def __init__(self, response):
            self.responses = self
            self.response = response
        def parse(self, **kwargs):
            assert kwargs["text_format"] is Extraction
            assert kwargs["store"] is False
            return self.response
    valid = Extraction(page=1, text="Источник", warnings=[])
    for response in [SimpleNamespace(status="incomplete", output=[], output_parsed=valid), SimpleNamespace(status="completed", output=[SimpleNamespace(content=[SimpleNamespace(type="refusal")])], output_parsed=None)]:
        ai = AI(Settings(data_dir=tmp_path, openai_api_key="test-only"), client=Transport(response))
        with pytest.raises(AIError):
            ai.parse(Extraction, [], 2000)
    ai = AI(Settings(data_dir=tmp_path), client=Transport(SimpleNamespace(status="completed", output=[], output_parsed=valid)))
    assert ai.parse(Extraction, [], 2000).text == "Источник"


def test_missing_api_key_does_not_fake_success(tmp_path):
    from app.ai import AI, AIError
    from app.config import Settings
    ai = AI(Settings(data_dir=tmp_path, openai_api_key=""))
    with pytest.raises(AIError, match="OPENAI_API_KEY"):
        ai.parse(Extraction, [], 1000)

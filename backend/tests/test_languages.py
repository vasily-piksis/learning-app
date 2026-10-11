import json
from types import SimpleNamespace

import pytest
from app.ai import AI
from app.config import Settings
from app.jobs import run_job
from app.models import Card, SourcePage
from app.schemas import Extraction, Generated, GeneratedCard, SourceRef
from conftest import make_topic
from fakes import FixtureAI, ready_document
from sqlalchemy import select


@pytest.mark.parametrize(
    "language,text", [("pl", "Obywatel"), ("lt", "Pilietis"), ("en", "Citizen")]
)
def test_ai_preserves_source_language_and_only_translates_explicitly(tmp_path, language, text):
    class Transport:
        def __init__(self):
            self.responses = self
            self.inputs = []

        def parse(self, **kwargs):
            self.inputs.append(kwargs)
            assert kwargs["store"] is False
            return SimpleNamespace(
                status="completed",
                output=[],
                output_parsed=Generated(cards=[], insufficient_reason=None),
            )

    transport = Transport()
    ai = AI(Settings(data_dir=tmp_path), client=transport)
    sources = [{"document_id": 1, "page": 1, "language": language, "text": text}]
    ai.generate(1, sources, "quiz", 1)
    request = transport.inputs[-1]
    assert "Пиши по-русски" not in request["input"][0]["content"]
    assert "язык" in request["input"][0]["content"]
    ai.generate(1, sources, "quiz", 1, target_language="ru", existing=[{"question": text}])
    data = json.loads(transport.inputs[-1]["input"][1]["content"])
    assert data["target_language"] == "ru" and data["existing"][0]["question"] == text
    assert sources[0]["text"] == text
    ai.explain({"question": text, "language": language, "sources": sources}, "Explain simply", [])
    assert "Пиши по-русски" not in transport.inputs[-1]["input"][0]["content"]


def test_language_metadata_and_duplicate_generation(client, app):
    class PolishAI(FixtureAI):
        def generate(self, topic_id, sources, mode, count, target_language=None, existing=None):
            self.inputs.append(
                {"target_language": target_language, "existing": existing, "sources": sources}
            )
            return Generated(
                cards=[
                    GeneratedCard(
                        topic_id=topic_id,
                        question="Kim jest obywatel?",
                        answer="Członek państwa",
                        mode="quiz",
                        options=["Członek państwa", "Miasto"],
                        correct_index=0,
                        language=target_language or "pl",
                        sources=[SourceRef(document_id=sources[0]["document_id"], page=1)],
                    )
                ],
                insufficient_reason=None,
            )

    app.state.ai = FixtureAI()
    topic = make_topic(client)
    document = ready_document(client, app, topic)
    with app.state.db.session() as db:
        page = db.scalar(select(SourcePage).where(SourcePage.document_id == document["id"]))
        page.language = "pl"
    app.state.ai = PolishAI()
    first = client.post("/api/generate", json={"topic_ids": [topic], "count": 1}).json()
    assert "id" in first, first
    run_job(app.state.db, app.state.ai, first["id"])
    card = client.get(f"/api/cards?job_id={first['id']}").json()[0]
    assert card["language"] == "pl" and card["sources"][0]["language"] == "pl"
    assert card["target_language"] is None
    second = client.post("/api/generate", json={"topic_ids": [topic], "count": 1}).json()
    run_job(app.state.db, app.state.ai, second["id"])
    assert client.get(f"/api/cards?job_id={second['id']}").json() == []
    assert client.get(f"/api/jobs/{second['id']}").json()["result"]["warnings"]
    assert app.state.ai.inputs[-1]["existing"][0]["question"] == card["question"]
    assert client.get(f"/api/topics/{topic}/documents").json()[0]["used_for_questions"] is True
    translated = client.post(
        "/api/generate", json={"topic_ids": [topic], "count": 1, "target_language": "ru"}
    ).json()
    run_job(app.state.db, app.state.ai, translated["id"])
    translation = client.get(f"/api/cards?job_id={translated['id']}").json()[0]
    assert translation["language"] == translation["target_language"] == "ru"
    with app.state.db.session() as db:
        assert db.get(Card, card["id"]).language == "pl"


def test_extraction_schema_keeps_optional_language_for_legacy_results():
    assert Extraction(page=1, text="Pilietis", warnings=[], language="lt").language == "lt"

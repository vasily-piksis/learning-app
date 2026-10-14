import pytest
from app.jobs import run_job
from app.schemas import Generated, GeneratedCard, QuizOptions, SourceRef
from conftest import make_topic
from fakes import FixtureAI, ready_document
from test_study import saved_cards


def multi_card(client, app):
    topic, cards = saved_cards(client, app, count=1)
    card = cards[0]
    response = client.patch(
        f"/api/cards/{card['id']}",
        json={
            "question": "Выбери все переводы table",
            "answer": "стол; таблица",
            "options": ["стол", "таблица", "стул"],
            "correct_indices": [0, 1],
            "version": card["version"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["correct_indices"] == [0, 1]
    return topic, response.json()


@pytest.mark.parametrize(
    ("choices", "correct"),
    [([0, 1], True), ([1, 0], True), ([0], False), ([1], False), ([0, 1, 2], False), ([2], False)],
)
def test_multiple_answers_require_exact_set_and_keep_history(client, app, choices, correct):
    topic, card = multi_card(client, app)
    session = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    assert session["card"]["multiple_answers"] is True
    assert "correct_indices" not in session["card"] and "correct_index" not in session["card"]
    route = f"/api/study/{session['id']}/answer"
    choices = [session["card"]["options"].index(card["options"][i]) for i in choices]
    expected_indices = sorted(
        session["card"]["options"].index(text) for text in ["стол", "таблица"]
    )
    payload = {"position": 0, "choices": choices, "idempotency_key": "multiple"}
    result = client.post(route, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["correct"] is correct
    assert result.json()["card"]["correct_indices"] == expected_indices
    assert (
        client.post(route, json={**payload, "choices": list(reversed(choices))}).json()
        == result.json()
    )
    history = client.get(f"/api/study/{session['id']}").json()
    assert history["review"][0]["choices"] == sorted(choices)
    assert history["correct"] == int(correct)


@pytest.mark.parametrize("choices", [[], [0, 0], [-1], [3], [False]])
def test_invalid_multiple_selections_do_not_advance(client, app, choices):
    topic, _ = multi_card(client, app)
    session = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    result = client.post(
        f"/api/study/{session['id']}/answer",
        json={"position": 0, "choices": choices, "idempotency_key": "invalid"},
    )
    assert result.status_code == 422
    assert client.get(f"/api/study/{session['id']}").json()["position"] == 0


@pytest.mark.parametrize("indices", [[], [0, 0], [-1], [3], [True]])
def test_edit_rejects_invalid_correct_sets(client, app, indices):
    topic, card = multi_card(client, app)
    result = client.patch(
        f"/api/cards/{card['id']}",
        json={
            "question": card["question"],
            "answer": card["answer"],
            "options": card["options"],
            "correct_indices": indices,
            "version": card["version"],
        },
    )
    assert result.status_code == 422
    assert client.get(f"/api/cards?topic_id={topic}").json()[0]["correct_indices"] == [0, 1]


def test_model_multiple_answers_are_saved_and_ready_for_both_modes(client, app):
    app.state.ai = FixtureAI()
    topic = make_topic(client)
    document = ready_document(client, app, topic)
    app.state.ai.generate = lambda *args, **kwargs: Generated(
        cards=[
            GeneratedCard(
                topic_id=topic,
                question="Все переводы table?",
                answer="стол; таблица",
                mode="quiz",
                options=["стол", "таблица", "стул"],
                correct_indices=[0, 1],
                sources=[SourceRef(document_id=document["id"], page=1)],
            )
        ],
        insufficient_reason=None,
    )
    job = client.post(
        "/api/generate", json={"topic_ids": [topic], "count": 1, "mode": "quiz"}
    ).json()
    run_job(app.state.db, app.state.ai, job["id"])
    cards = client.get(f"/api/cards?topic_id={topic}").json()
    assert cards[0]["correct_indices"] == [0, 1]
    client.post("/api/cards/save", json={"card_ids": [cards[0]["id"]]})
    assert client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).status_code == 200
    flash = client.post("/api/study", json={"topic_ids": [topic], "mode": "flashcard"}).json()
    revealed = client.post(f"/api/study/{flash['id']}/reveal", json={"position": 0}).json()["card"]
    assert revealed["answer"] == "стол; таблица" and revealed["correct_indices"] == []


def test_flashcard_preparation_can_make_multiple_correct_options(client, app):
    topic, cards = saved_cards(client, app, "flashcard", 1)
    app.state.ai.prepare_quiz = lambda snapshot: QuizOptions(
        card_id=snapshot["id"], options=["Нил", "река Нил", "Дон"], correct_indices=[0, 1]
    )
    job = client.post("/api/study/prepare-options", json={"topic_ids": [topic]}).json()
    run_job(app.state.db, app.state.ai, job["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "succeeded"
    assert (
        client.post(
            f"/api/jobs/{job['id']}/save-preparation", json={"card_ids": [c["id"] for c in cards]}
        ).status_code
        == 200
    )
    session = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    assert session["card"]["multiple_answers"] is True


def test_real_sdk_parses_multiple_correct_options_without_paid_request(tmp_path):
    import httpx
    from test_retry import ai_client, completed

    payload = {
        "cards": [
            {
                "topic_id": 1,
                "question": "Все переводы table?",
                "answer": "стол; таблица",
                "mode": "quiz",
                "options": ["стол", "таблица", "стул"],
                "correct_index": None,
                "correct_indices": [0, 1],
                "sources": [{"document_id": 1, "page": 1}],
                "language": "ru",
            }
        ],
        "insufficient_reason": None,
    }
    ai, sdk = ai_client(tmp_path, lambda request: httpx.Response(200, json=completed(payload)))
    with sdk:
        result = ai.generate(
            1,
            [{"document_id": 1, "page": 1, "text": "table: стол, таблица", "language": "ru"}],
            "quiz",
            1,
        )
    assert result.cards[0].correct_indices == [0, 1]
    assert result.cards[0].correct_index is None


def test_existing_0003_database_and_legacy_snapshot_upgrade_without_rewriting(tmp_path):
    import json
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from app.config import Settings
    from app.db import Database
    from app.models import Card, SessionCard, Topic
    from sqlalchemy import create_engine, text

    backend = Path(__file__).parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    engine = create_engine(f"sqlite:///{tmp_path / 'learning.sqlite3'}")
    snapshot = {
        "id": 1,
        "topic_id": 1,
        "question": "Река?",
        "answer": "Нил",
        "mode": "quiz",
        "options": ["Нил", "Дон"],
        "correct_index": 0,
        "sources": [],
    }
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0003")
        statements = [
            "INSERT INTO users VALUES(1, 'child', 'Child', 'test-only-hash', 1)",
            "INSERT INTO subjects VALUES(1, 'History', '2026-01-01')",
            "INSERT INTO topics VALUES(1, 1, 'Egypt', 1, '2026-01-01')",
            "INSERT INTO cards(id, topic_id, question, answer, mode, options, correct_index, version, status) VALUES(1, 1, 'Река?', 'Нил', 'quiz', '[\"Нил\", \"Дон\"]', 0, 1, 'saved')",
            "INSERT INTO study_sessions VALUES(1, 1, '[1]', 'quiz', 0, 'active', '2026-01-01', '2026-01-01')",
        ]
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(
            text("INSERT INTO session_cards VALUES(1, 1, 0, :snapshot, 0)"),
            {"snapshot": json.dumps(snapshot)},
        )
    engine.dispose()
    database = Database(Settings(_env_file=None, data_dir=tmp_path))
    with database.session() as db:
        assert db.get(Topic, 1).deleted is False
        card = db.get(Card, 1)
        assert card.correct_index == 0 and card.correct_indices == []
        assert db.get(SessionCard, 1).snapshot == snapshot
        assert list(db.execute(text("PRAGMA foreign_key_check"))) == []
        from app.study import public_card

        assert public_card(snapshot, True, db)["correct_indices"] == [0]
        assert "correct_indices" not in public_card(snapshot, False, db)

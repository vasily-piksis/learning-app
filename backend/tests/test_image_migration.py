from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_image_migration_adds_only_reference_tables_and_preserves_original_data(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    original = tmp_path / "original.pdf"
    original.write_bytes(b"private original bytes")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0006")
        connection.execute(text("INSERT INTO users VALUES(1,'test','Learner','fixture-hash',1)"))
        connection.execute(
            text("INSERT INTO subjects(id,name,created) VALUES(1,'Subject','2026-01-01')")
        )
        connection.execute(
            text(
                "INSERT INTO topics(id,subject_id,name,version,created) VALUES(1,1,'Topic',1,'2026-01-01')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO cards(id,topic_id,question,answer,mode,options,correct_index,version,status) VALUES(1,1,'Original question','Original answer','quiz','[\"Original answer\",\"Other\"]',0,3,'saved')"
            )
        )
        for sid, mode, status, position in (
            (1, "flashcard", "active", 0),
            (2, "quiz", "completed", 1),
        ):
            connection.execute(
                text(
                    "INSERT INTO study_sessions(id,user_id,topic_ids,mode,position,status,created,updated) VALUES(:id,1,'[1]',:mode,:position,:status,'2026-01-01','2026-01-01')"
                ),
                {"id": sid, "mode": mode, "position": position, "status": status},
            )
            connection.execute(
                text(
                    "INSERT INTO session_cards(id,session_id,position,snapshot,revealed) VALUES(:id,:id,0,:snapshot,0)"
                ),
                {
                    "id": sid,
                    "snapshot": '{"question":"Original snapshot","answer":"Fixed solution","mode":"'
                    + mode
                    + '"}',
                },
            )
        connection.execute(
            text(
                "INSERT INTO attempts(id,user_id,session_card_id,idempotency_key,value,correct,created) VALUES(1,1,2,'legacy',:value,1,'2026-01-01')"
            ),
            {"value": '{"choice":0}'},
        )
        tables = ("cards", "study_sessions", "session_cards", "attempts")
        before = {
            table: [
                dict(row) for row in connection.execute(text(f"SELECT * FROM {table}")).mappings()
            ]
            for table in tables
        }
        command.upgrade(config, "0007")
        after = {
            table: [
                dict(row) for row in connection.execute(text(f"SELECT * FROM {table}")).mappings()
            ]
            for table in tables
        }
        for table in tables:
            assert [{key: row[key] for key in before[table][0]} for row in after[table]] == before[
                table
            ]
        assert {"image_assets", "card_images", "session_images", "job_images"} <= set(
            inspect(connection).get_table_names()
        )
        assert after["cards"][0]["question_type"] == "choice"
        assert after["cards"][0]["exercise"] is None
        assert connection.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    assert original.read_bytes() == b"private original bytes"

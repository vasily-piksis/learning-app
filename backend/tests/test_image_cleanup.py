from pathlib import Path

import pytest
from test_question_images import candidate, question, save


def files(app):
    return list((app.state.settings.data_dir / "question-images").glob("*.webp"))


def test_delete_question_keeps_two_histories_until_last_reference_is_removed(client, app):
    topic, card = question(client, app)
    asset = candidate(client, card)
    assert (
        save(client, card, {"question": {"asset_id": asset["id"], "alt": "old"}}).status_code == 200
    )
    first = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    second = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    assert len(files(app)) == 1
    assert client.delete(f"/api/cards/{card['id']}").status_code == 200
    assert len(files(app)) == 1
    assert client.post("/api/study/delete", json={"session_ids": [first["id"]]}).status_code == 200
    assert len(files(app)) == 1
    assert client.get(second["card"]["images"]["question"]["url"]).status_code == 200
    assert client.post("/api/study/delete", json={"session_ids": [second["id"]]}).status_code == 200
    assert files(app) == []


@pytest.mark.parametrize("remove", ["topic", "subject"])
def test_delete_topic_and_subject_clean_attached_and_unattached_candidates(client, app, remove):
    topic, card = question(client, app)
    first = candidate(client, card)
    current = save(client, card, {"question": {"asset_id": first["id"], "alt": "one"}}).json()
    candidate(client, current, "answer")
    assert len(files(app)) == 2
    path = (
        f"/api/topics/{topic}"
        if remove == "topic"
        else f"/api/subjects/{client.get(f'/api/topics/{topic}').json()['subject_id']}"
    )
    assert client.delete(path).status_code == 200
    assert files(app) == []


def test_repeat_copies_old_image_after_question_delete_and_original_history_cleanup(client, app):
    topic, card = question(client, app)
    asset = candidate(client, card)
    assert (
        save(client, card, {"question": {"asset_id": asset["id"], "alt": "immutable"}}).status_code
        == 200
    )
    original = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    wrong = original["card"]["options"].index("Дон")
    assert (
        client.post(
            f"/api/study/{original['id']}/answer",
            json={"position": 0, "choice": wrong, "idempotency_key": "image-repeat"},
        ).status_code
        == 200
    )
    assert client.delete(f"/api/cards/{card['id']}").status_code == 200
    repeated = client.post(f"/api/study/{original['id']}/repeat").json()
    assert repeated["card"]["images"]["question"]["asset_id"] == asset["id"]
    assert (
        repeated["card"]["images"]["question"]["url"]
        != original["card"]["images"]["question"]["url"]
    )
    client.post("/api/study/delete", json={"session_ids": [original["id"]]})
    assert client.get(repeated["card"]["images"]["question"]["url"]).status_code == 200
    client.post("/api/study/delete", json={"session_ids": [repeated["id"]]})
    assert files(app) == []


def test_failed_unlink_is_retained_for_safe_retry_without_deleting_other_files(
    client, app, monkeypatch
):
    from app.question_images import cleanup_image_assets

    _, card = question(client, app)
    asset = candidate(client, card)
    original_unlink = Path.unlink

    def fail(path, *args, **kwargs):
        if path.parent.name == "question-images" and path.suffix == ".webp":
            raise OSError("temporary failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail)
    assert client.delete(f"/api/image-candidates/{asset['id']}").status_code == 200
    assert len(files(app)) == 1
    monkeypatch.setattr(Path, "unlink", original_unlink)
    cleanup_image_assets(app.state.db)
    assert files(app) == [] and len(list((app.state.settings.data_dir / "files").iterdir())) == 1


def test_recovery_finishes_renamed_writing_asset_or_discards_missing_part(client, app):
    from app.models import ImageAsset
    from app.question_images import cleanup_image_assets

    _, card = question(client, app)
    asset = candidate(client, card)
    with app.state.db.session() as db:
        row = db.get(ImageAsset, asset["id"])
        row.stage = "writing"
        row.sha256 = ""
    cleanup_image_assets(app.state.db, recover_writing=True)
    assert client.get(asset["url"]).status_code == 200
    with app.state.db.session() as db:
        row = db.get(ImageAsset, asset["id"])
        assert row.stage == "draft" and row.sha256
        row.stage = "writing"
        filename = row.filename
    (app.state.settings.data_dir / "question-images" / filename).unlink()
    (app.state.settings.data_dir / "question-images" / (filename + ".part")).write_bytes(
        b"incomplete"
    )
    cleanup_image_assets(app.state.db, recover_writing=True)
    assert list((app.state.settings.data_dir / "question-images").iterdir()) == []
    assert client.get(asset["url"]).status_code == 404


def test_concurrent_history_repeat_and_cleanup_cannot_delete_the_new_reference(client, app):
    from concurrent.futures import ThreadPoolExecutor

    from app.question_images import cleanup_image_assets

    topic, card = question(client, app)
    asset = candidate(client, card)
    save(client, card, {"question": {"asset_id": asset["id"], "alt": "stable"}})
    session = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    client.post(
        f"/api/study/{session['id']}/answer",
        json={
            "position": 0,
            "choice": session["card"]["options"].index("Дон"),
            "idempotency_key": "concurrent-image",
        },
    )
    client.delete(f"/api/cards/{card['id']}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        repeated = pool.submit(client.post, f"/api/study/{session['id']}/repeat")
        cleaning = pool.submit(cleanup_image_assets, app.state.db)
        result = repeated.result()
        cleaning.result()
    assert result.status_code == 200, result.text
    assert client.get(result.json()["card"]["images"]["question"]["url"]).status_code == 200


def test_commit_failure_after_rename_recovers_candidate_without_another_upload(
    client, app, monkeypatch
):
    from app.models import ImageAsset
    from sqlalchemy.orm import Session
    from test_question_images import upload

    _, card = question(client, app)
    original_commit = Session.commit
    raised = []

    def fail_once(session):
        if not raised and any(
            isinstance(row, ImageAsset) and row.stage == "draft" for row in session.dirty
        ):
            raised.append(True)
            raise RuntimeError("simulated metadata commit failure")
        return original_commit(session)

    monkeypatch.setattr(Session, "commit", fail_once)
    with pytest.raises(RuntimeError):
        upload(client, card)
    gallery = client.get(f"/api/cards/{card['id']}/image-candidates").json()["items"]
    assert len(gallery) == 1 and gallery[0]["stage"] == "draft"
    assert client.get(gallery[0]["url"]).status_code == 200
    assert len(files(app)) == 1

import io
import json

import pytest
from PIL import Image
from test_study import saved_cards


def image_bytes(fmt="PNG", size=(8, 4), color=(20, 80, 140, 128), exif=None):
    image = Image.new("RGBA", size, color)
    if fmt == "JPEG":
        image = image.convert("RGB")
    data = io.BytesIO()
    image.save(data, format=fmt, **({"exif": exif} if exif else {}))
    return data.getvalue()


def question(client, app):
    topic, _ = saved_cards(client, app, count=1)
    return topic, client.get(f"/api/cards?topic_id={topic}").json()[0]


def upload(client, card, slot="question", data=None, mime="image/png"):
    return client.post(
        f"/api/cards/{card['id']}/image-candidates",
        data={"slot": slot, "version": card["version"]},
        files={"file": ("photo.png", data if data is not None else image_bytes(), mime)},
    )


def save(client, card, updates, **changes):
    return client.patch(
        f"/api/cards/{card['id']}",
        json={
            "question": card["question"],
            "answer": card["answer"],
            "options": card["options"],
            "correct_indices": card["correct_indices"],
            "version": card["version"],
            "image_updates": updates,
            **changes,
        },
    )


def candidate(client, card, slot="question", **kwargs):
    response = upload(client, card, slot, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def test_upload_normalizes_bytes_and_preserves_alpha_without_modifying_question(client, app):
    topic, card = question(client, app)
    result = candidate(client, card)
    assert result["slot"] == "question" and result["stage"] == "draft"
    assert "filename" not in result and "path" not in result
    preview = client.get(result["url"])
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/webp"
    assert (
        preview.headers["cache-control"] == "no-store"
        and preview.headers["x-content-type-options"] == "nosniff"
    )
    with Image.open(io.BytesIO(preview.content)) as image:
        assert image.size == (8, 4) and image.convert("RGBA").getpixel((0, 0))[3] == 128
        assert not image.getexif()
    assert client.get(f"/api/cards?topic_id={topic}").json()[0] == card
    gallery = client.get(f"/api/cards/{card['id']}/image-candidates").json()
    assert gallery["items"][0]["id"] == result["id"] and gallery["items"][0]["can_apply"] is True


def test_orientation_metadata_and_dimension_limits(client, app):
    _, card = question(client, app)
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private metadata"
    result = candidate(client, card, data=image_bytes("JPEG", (4, 2), exif=exif), mime="image/jpeg")
    with Image.open(io.BytesIO(client.get(result["url"]).content)) as normalized:
        assert normalized.size == (2, 4) and not normalized.getexif()
    resized = candidate(client, card, data=image_bytes(size=(3000, 1000)))
    assert resized["width"] == 2048 and resized["height"] <= 683
    response = upload(client, card, data=image_bytes(size=(5000, 4001)))
    assert response.status_code == 413


@pytest.mark.parametrize(
    "data,mime",
    [
        (b"not an image", "image/png"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "image/png"),
        (image_bytes("GIF"), "image/png"),
    ],
)
def test_spoofed_mime_corrupt_and_unsupported_formats_are_rejected(client, app, data, mime):
    _, card = question(client, app)
    response = upload(client, card, data=data, mime=mime)
    assert response.status_code == 422, response.text
    assert client.get(f"/api/cards/{card['id']}/image-candidates").json()["items"] == []


def test_animated_webp_and_oversized_upload_are_rejected(client, app):
    _, card = question(client, app)
    frames = [Image.new("RGB", (4, 4), color) for color in ["red", "blue"]]
    data = io.BytesIO()
    frames[0].save(
        data, format="WEBP", save_all=True, append_images=frames[1:], duration=100, loop=0
    )
    assert upload(client, card, data=data.getvalue(), mime="image/webp").status_code == 422
    assert upload(client, card, data=b"x" * (10 * 1024 * 1024 + 1)).status_code == 413


def test_atomic_text_image_save_and_legacy_edit_keep_existing_link(client, app):
    topic, card = question(client, app)
    asset = candidate(client, card)
    update = {"question": {"asset_id": asset["id"], "alt": "Iliustracija"}}
    invalid = save(client, card, update, question="")
    assert invalid.status_code == 422
    assert client.get(f"/api/cards?topic_id={topic}").json()[0].get("images", {}) == {}
    response = save(client, card, update)
    assert response.status_code == 200, response.text
    current = response.json()
    assert current["version"] == card["version"] + 1
    assert current["images"]["question"]["alt"] == "Iliustracija"
    library = client.get(current["images"]["question"]["url"])
    assert library.status_code == 200
    edit = client.patch(
        f"/api/cards/{card['id']}",
        json={
            "question": "New wording",
            "answer": card["answer"],
            "options": card["options"],
            "correct_indices": card["correct_indices"],
            "version": current["version"],
        },
    )
    assert edit.status_code == 200 and edit.json()["images"]["question"]["asset_id"] == asset["id"]


def test_stale_preview_free_rebase_target_slot_and_owner_guards(client, app):
    topic, card = question(client, app)
    asset = candidate(client, card)
    updated = client.patch(
        f"/api/cards/{card['id']}", json={"question": "Changed", "version": card["version"]}
    ).json()
    assert client.get(asset["url"]).status_code == 200
    assert (
        save(client, updated, {"question": {"asset_id": asset["id"], "alt": "old"}}).status_code
        == 409
    )
    stale = client.get(f"/api/cards/{card['id']}/image-candidates").json()["items"][0]
    assert stale["can_apply"] is False and stale["stage"] == "obsolete"
    assert (
        client.post(
            f"/api/image-candidates/{asset['id']}/rebase", json={"version": updated["version"]}
        ).status_code
        == 200
    )
    assert (
        save(
            client, updated, {"answer": {"asset_id": asset["id"], "alt": "wrong slot"}}
        ).status_code
        == 422
    )
    assert (
        save(
            client, updated, {"question": {"asset_id": asset["id"], "alt": "reviewed"}}
        ).status_code
        == 200
    )


def test_candidate_preview_is_private_and_library_requires_login(client, app):
    _, card = question(client, app)
    asset = candidate(client, card)
    login = client.post(
        "/api/auth/login", json={"username": "parent", "password": "parent-password"}
    ).json()
    client.headers.update({"X-CSRF-Token": login["csrf_token"]})
    assert client.get(asset["url"]).status_code == 404
    assert client.get(f"/api/cards/{card['id']}/image-candidates").json()["items"] == []
    assert (
        save(client, card, {"question": {"asset_id": asset["id"], "alt": "foreign"}}).status_code
        == 404
    )
    client.cookies.clear()
    assert client.get(asset["url"]).status_code == 401
    assert client.get(f"/api/cards/{card['id']}/images/question").status_code == 401


def test_answer_image_hidden_without_id_alt_or_preload_until_reveal(client, app):
    topic, card = question(client, app)
    asset = candidate(client, card, "answer")
    assert (
        save(
            client, card, {"answer": {"asset_id": asset["id"], "alt": "Hidden answer illustration"}}
        ).status_code
        == 200
    )
    session = client.post("/api/study", json={"topic_ids": [topic], "mode": "flashcard"}).json()
    assert asset["id"] not in json.dumps(
        session
    ) and "Hidden answer illustration" not in json.dumps(session)
    path = f"/api/study/{session['id']}/cards/0/images/answer"
    assert client.get(path).status_code in [403, 404]
    shown = client.post(f"/api/study/{session['id']}/reveal", json={"position": 0}).json()
    assert shown["card"]["images"]["answer"]["asset_id"] == asset["id"]
    assert client.get(path).status_code == 200
    other = client.post(
        "/api/auth/login", json={"username": "parent", "password": "parent-password"}
    ).json()
    client.headers.update({"X-CSRF-Token": other["csrf_token"]})
    assert client.get(path).status_code == 404


def test_discard_and_replace_never_remove_original_or_old_history_asset(client, app):
    topic, card = question(client, app)
    old = candidate(client, card)
    current = save(client, card, {"question": {"asset_id": old["id"], "alt": "old alt"}}).json()
    session = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    rejected = candidate(client, current)
    assert client.delete(f"/api/image-candidates/{rejected['id']}").status_code == 200
    assert client.delete(f"/api/image-candidates/{rejected['id']}").status_code == 200
    assert client.get(current["images"]["question"]["url"]).status_code == 200
    newer = candidate(client, current, data=image_bytes(color=(200, 10, 5, 255)))
    updated = save(client, current, {"question": {"asset_id": newer["id"], "alt": "new alt"}})
    assert updated.status_code == 200, updated.text
    history = client.get(f"/api/study/{session['id']}").json()
    assert history["card"]["images"]["question"]["asset_id"] == old["id"]
    assert history["card"]["images"]["question"]["alt"] == "old alt"
    assert (
        client.get(history["card"]["images"]["question"]["url"]).content
        != client.get(updated.json()["images"]["question"]["url"]).content
    )


def test_regeneration_applies_text_and_picture_atomically_with_one_version(client, app):
    from app.jobs import run_job
    from test_regeneration import fixture, request

    topic, card, _, _ = fixture(client, app)
    asset = candidate(client, card)
    job = request(client, card).json()
    run_job(app.state.db, app.state.ai, job["id"])
    proposal = client.get(f"/api/jobs/{job['id']}").json()["result"]["candidate"]
    body = {
        "candidate": proposal,
        "image_updates": {"question": {"asset_id": asset["id"], "alt": "new illustration"}},
    }
    route = f"/api/jobs/{job['id']}/apply-regeneration"
    response = client.post(route, json=body)
    assert response.status_code == 200, response.text
    assert (
        response.json()["version"] == card["version"] + 1
        and response.json()["question"] == "Новая река?"
    )
    assert response.json()["images"]["question"]["asset_id"] == asset["id"]
    assert client.post(route, json=body).json() == response.json()
    changed = {**body, "image_updates": {"question": {"asset_id": None, "alt": ""}}}
    assert client.post(route, json=changed).status_code == 409


def test_bad_image_update_rolls_back_all_text_and_links(client, app):
    topic, card = question(client, app)
    first = candidate(client, card)
    wrong = candidate(client, card, "answer")
    response = save(
        client,
        card,
        {
            "question": {"asset_id": first["id"], "alt": "valid"},
            "answer": {"asset_id": first["id"], "alt": "wrong slot"},
        },
        question="must not persist",
    )
    assert response.status_code == 422
    current = client.get(f"/api/cards?topic_id={topic}").json()[0]
    assert current == card
    assert (
        client.get(first["url"]).status_code == 200 and client.get(wrong["url"]).status_code == 200
    )


def test_upload_failure_cannot_discard_another_inflight_writing_asset(client, app, monkeypatch):
    from app import question_images
    from app.models import ImageAsset

    _, card = question(client, app)
    other = "f" * 32
    with app.state.db.session() as db:
        db.add(
            ImageAsset(
                id=other,
                filename=f"{other}.webp",
                owner_user_id=1,
                target_card_id=card["id"],
                target_version=card["version"],
                slot="answer",
                stage="writing",
            )
        )

    def fail(*args):
        raise OSError("local write failed")

    monkeypatch.setattr(question_images, "write_candidate", fail)
    with pytest.raises(OSError):
        upload(client, card)
    with app.state.db.session() as db:
        assert db.get(ImageAsset, other).stage == "writing"


def test_regeneration_and_explanation_adapter_inputs_exclude_illustrations(client, app):
    from app.jobs import run_job
    from test_regeneration import fixture, request

    topic, card, _, calls = fixture(client, app)
    asset = candidate(client, card)
    updated = save(client, card, {"question": {"asset_id": asset["id"], "alt": "private alt"}})
    assert updated.status_code == 200
    card = updated.json()
    job = request(client, card).json()
    run_job(app.state.db, app.state.ai, job["id"])
    assert len(calls) == 1
    snapshot, sources = calls[0]
    assert "images" not in snapshot
    assert all("asset_id" not in source for source in sources)
    session = client.post("/api/study", json={"topic_ids": [topic], "mode": "flashcard"}).json()
    client.post(f"/api/study/{session['id']}/reveal", json={"position": 0})
    explanation = client.post(
        f"/api/study/{session['id']}/explain", json={"position": 0, "question": "Why?"}
    ).json()
    run_job(app.state.db, app.state.ai, explanation["id"])
    assert "images" not in app.state.ai.inputs[-1][0]
    assert all("asset_id" not in source for source in app.state.ai.inputs[-1][0]["sources"])

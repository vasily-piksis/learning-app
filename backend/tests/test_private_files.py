from io import BytesIO

import pytest
from app.jobs import run_job
from app.models import Document
from conftest import make_topic, pdf_bytes
from fastapi.testclient import TestClient
from PIL import Image


@pytest.mark.parametrize("kind", ["pdf", "image", "youtube"])
def test_original_files_require_login_even_with_known_id_or_filename(
    client, app, monkeypatch, kind
):
    topic = make_topic(client)
    if kind == "youtube":
        from test_downsub import URL, successful, transport

        app.state.settings.youtube_provider = "downsub"
        transport(monkeypatch, successful)
        document = client.post(
            f"/api/topics/{topic}/youtube", json={"url": URL, "language": "pl"}
        ).json()
        run_job(app.state.db, app.state.ai, document["job_id"])
    else:
        if kind == "pdf":
            content, name = pdf_bytes(), "private.pdf"
        else:
            buffer = BytesIO()
            Image.new("RGB", (50, 50), "red").save(buffer, "PNG")
            content, name = buffer.getvalue(), "private.png"
        document = client.post(
            f"/api/topics/{topic}/documents", files={"file": (name, content)}
        ).json()
    route = f"/api/documents/{document['id']}/download"
    allowed = client.get(route)
    assert allowed.status_code == 200
    assert allowed.headers["cache-control"] == "no-store"
    with app.state.db.session() as db:
        filename = db.get(Document, document["id"]).filename
    with TestClient(app) as anonymous:
        for endpoint in (
            route,
            f"/api/topics/{topic}/documents",
            "/api/cards",
            f"/api/jobs/{document['job_id']}",
        ):
            response = anonymous.get(endpoint)
            assert response.status_code == 401
            assert response.content != allowed.content
        for path in (
            f"/files/{filename}",
            f"/data/files/{filename}",
            f"/assets/{filename}",
            f"/{filename}",
            f"/%2e%2e/data/files/{filename}",
        ):
            response = anonymous.get(path)
            assert response.content != allowed.content
        for cache in (app.state.settings.data_dir / "youtube-cache").glob("*.json"):
            private_cache = cache.read_bytes()
            for path in (
                f"/youtube-cache/{cache.name}",
                f"/data/youtube-cache/{cache.name}",
                f"/assets/{cache.name}",
            ):
                assert anonymous.get(path).content != private_cache
    client.post("/api/auth/logout")
    assert client.get(route).status_code == 401


def test_public_frontend_cannot_overlap_private_storage(tmp_path):
    from app.config import Settings
    from app.main import create_app

    root = tmp_path / "public"
    root.mkdir()
    (root / "index.html").write_text("<html>Login</html>")
    with pytest.raises(ValueError, match="FRONTEND_DIR"):
        create_app(
            Settings(_env_file=None, data_dir=root / "data", frontend_dir=root), worker=False
        )


def test_assets_directory_cannot_point_to_upload_storage(tmp_path):
    from app.config import Settings
    from app.main import create_app

    public = tmp_path / "public"
    files = tmp_path / "data" / "files"
    public.mkdir()
    files.mkdir(parents=True)
    (public / "index.html").write_text("<html>Login</html>")
    (public / "assets").symlink_to(files, target_is_directory=True)
    with pytest.raises(ValueError, match="assets"):
        create_app(
            Settings(_env_file=None, data_dir=tmp_path / "data", frontend_dir=public), worker=False
        )

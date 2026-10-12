from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_serves_frontend_without_turning_missing_api_into_html(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><h1>Учиться</h1></html>")
    app = create_app(
        Settings(data_dir=tmp_path / "db", frontend_dir=static, cookie_secure=False), worker=False
    )
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200 and "Учиться" in page.text
        assert page.headers["x-content-type-options"] == "nosniff"
        assert page.headers["x-robots-tag"] == "noindex, nofollow"
        assert client.get("/login").headers["x-robots-tag"] == "noindex, nofollow"
        assert client.get("/api/not-a-route").status_code == 404
        assert client.get("/api/auth/me").headers["cache-control"] == "no-store"

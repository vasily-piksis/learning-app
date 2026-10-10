from fastapi.testclient import TestClient


def test_private_login_csrf_and_logout(tmp_path):
    from app.cli import create_user
    from app.config import Settings
    from app.main import create_app

    settings = Settings(data_dir=tmp_path, app_origin="http://testserver", cookie_secure=False)
    app = create_app(settings, worker=False)
    create_user(app.state.db, "daughter", "Дочка", "a-long-secret")
    with TestClient(app) as client:
        assert client.get("/api/auth/me").status_code == 401
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "daughter", "password": "wrong"},
                headers={"Origin": "http://testserver"},
            ).status_code
            == 401
        )
        response = client.post(
            "/api/auth/login",
            json={"username": "daughter", "password": "a-long-secret"},
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 200
        assert "httponly" in response.headers["set-cookie"].lower()
        assert client.get("/api/auth/me").json()["display_name"] == "Дочка"
        csrf = response.json()["csrf_token"]
        assert client.post("/api/auth/logout").status_code == 403
        assert (
            client.post(
                "/api/auth/logout", headers={"Origin": "http://evil", "X-CSRF-Token": csrf}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/auth/logout", headers={"Origin": "http://testserver", "X-CSRF-Token": csrf}
            ).status_code
            == 200
        )
        assert client.get("/api/auth/me").status_code == 401
    reopened = create_app(settings, worker=False)
    with TestClient(reopened) as client:
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "daughter", "password": "a-long-secret"},
                headers={"Origin": "http://testserver"},
            ).status_code
            == 200
        )

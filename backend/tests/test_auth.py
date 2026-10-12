from fastapi.testclient import TestClient


def test_three_failed_logins_lock_for_fifteen_minutes_without_verifying_more_passwords(
    client, app, monkeypatch
):
    from app import auth

    timestamp = [1000.0]
    app.state.login_limiter.clock = lambda: timestamp[0]
    original = auth.hasher.verify
    verifications = []

    def verify(self, encoded, password):
        verifications.append(password)
        return original(encoded, password)

    monkeypatch.setattr(auth.PasswordHasher, "verify", verify)
    for index in range(3):
        timestamp[0] += 100 if index else 0
        assert (
            client.post(
                "/api/auth/login", json={"username": "child", "password": "wrong"}
            ).status_code
            == 401
        )
    locked = client.post(
        "/api/auth/login", json={"username": "child", "password": "strong-password"}
    )
    assert locked.status_code == 429
    assert locked.headers["retry-after"] == "900"
    assert len(verifications) == 3
    timestamp[0] += 899
    assert (
        client.post(
            "/api/auth/login", json={"username": "child", "password": "strong-password"}
        ).status_code
        == 429
    )
    timestamp[0] += 1
    assert (
        client.post(
            "/api/auth/login", json={"username": "child", "password": "strong-password"}
        ).status_code
        == 200
    )


def test_successful_login_resets_failed_attempts(client):
    for _ in range(2):
        for _ in range(2):
            assert (
                client.post(
                    "/api/auth/login", json={"username": "child", "password": "wrong"}
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/api/auth/login", json={"username": "child", "password": "strong-password"}
            ).status_code
            == 200
        )


def test_lock_cannot_be_bypassed_by_changing_username_or_forwarded_header(client, app):
    for index in range(3):
        assert (
            client.post(
                "/api/auth/login",
                json={"username": f"missing-{index}", "password": "wrong"},
                headers={"X-Forwarded-For": f"198.51.100.{index}"},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/auth/login",
            json={"username": "child", "password": "strong-password"},
            headers={"X-Forwarded-For": "198.51.100.99"},
        ).status_code
        == 429
    )
    with TestClient(app, client=("198.51.100.20", 12345)) as other:
        assert (
            other.post(
                "/api/auth/login",
                json={"username": "child", "password": "strong-password"},
                headers={"Origin": "http://testserver"},
            ).status_code
            == 200
        )


def test_parallel_failed_logins_cannot_bypass_three_attempt_limit(client, monkeypatch):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock

    from app import auth
    from argon2.exceptions import VerificationError

    calls = []
    guard = Lock()

    def wrong_password(self, encoded, password):
        with guard:
            calls.append(password)
        time.sleep(0.05)
        raise VerificationError("invalid")

    monkeypatch.setattr(auth.PasswordHasher, "verify", wrong_password)
    with ThreadPoolExecutor(max_workers=8) as executor:
        statuses = list(
            executor.map(
                lambda _: (
                    client.post(
                        "/api/auth/login", json={"username": "child", "password": "wrong"}
                    ).status_code
                ),
                range(8),
            )
        )
    assert statuses.count(401) == 3
    assert statuses.count(429) == 5
    assert len(calls) == 3


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

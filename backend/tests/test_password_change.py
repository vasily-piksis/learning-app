import pytest
from app.auth import hasher
from app.models import AuthSession, User
from fastapi.testclient import TestClient
from sqlalchemy import select

OLD = "strong-password"
NEW = "a-new-family-password"


def change(client, current=OLD, new=NEW):
    return client.post(
        "/api/auth/password", json={"current_password": current, "new_password": new}
    )


def login(client, password=OLD, username="child"):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": "http://testserver"},
    )
    if response.status_code == 200:
        client.headers.update(
            {"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf_token"]}
        )
    return response


def test_change_rotates_current_session_and_revokes_other_devices_only_for_this_user(client, app):
    old_token = client.cookies.get("study_session")
    old_csrf = client.headers["X-CSRF-Token"]
    with TestClient(app) as other, TestClient(app) as parent:
        assert login(other).status_code == 200
        assert login(parent, "parent-password", "parent").status_code == 200
        response = change(client)
        assert response.status_code == 200, response.text
        assert "httponly" in response.headers["set-cookie"].lower()
        assert client.cookies.get("study_session") != old_token
        assert response.json()["csrf_token"] != old_csrf
        assert OLD not in response.text and NEW not in response.text
        assert client.get("/api/auth/me").status_code == 200
        assert other.get("/api/auth/me").status_code == 401
        assert parent.get("/api/auth/me").status_code == 200
        assert client.post("/api/auth/logout").status_code == 403
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        with app.state.db.session() as db:
            user = db.scalar(select(User).where(User.username == "child"))
            assert hasher.verify(user.password_hash, NEW)
            assert (
                len(list(db.scalars(select(AuthSession).where(AuthSession.user_id == user.id))))
                == 1
            )
        assert login(other, OLD).status_code == 401
        assert login(other, NEW).status_code == 200
        assert client.post("/api/auth/logout").status_code == 200


def test_wrong_current_password_keeps_hash_and_session(client, app):
    token = client.cookies.get("study_session")
    with app.state.db.session() as db:
        before = db.scalar(select(User).where(User.username == "child")).password_hash
    assert change(client, current="incorrect-current").status_code == 401
    assert client.cookies.get("study_session") == token
    assert client.get("/api/auth/me").status_code == 200
    with app.state.db.session() as db:
        assert db.scalar(select(User).where(User.username == "child")).password_hash == before


@pytest.mark.parametrize("new", ["s3cr!", "", "a" * 1025])
def test_invalid_new_password_is_rejected_without_echoing_secrets(client, new):
    response = change(client, new=new)
    assert response.status_code == 422
    assert OLD not in response.text
    if new:
        assert new not in response.text
    assert client.get("/api/auth/me").status_code == 200


def test_password_change_requires_login_csrf_and_same_origin(client, app):
    with TestClient(app) as anonymous:
        anonymous.headers["Origin"] = "http://testserver"
        assert change(anonymous).status_code == 401
    assert (
        client.post(
            "/api/auth/password",
            json={"current_password": OLD, "new_password": NEW},
            headers={"Origin": "https://wrong.example"},
        ).status_code
        == 403
    )
    client.headers.pop("X-CSRF-Token")
    assert change(client).status_code == 403


def test_three_wrong_current_passwords_lock_changes_but_do_not_lock_login(client, app, monkeypatch):
    from app import auth

    timestamp = [1000.0]
    # The real limiter is exercised; only the clock and expensive verification are observed.
    app.state.password_limiter.clock = lambda: timestamp[0]
    original = auth.PasswordHasher.verify
    calls = []

    def verify(self, encoded, password):
        calls.append(password)
        return original(self, encoded, password)

    monkeypatch.setattr(auth.PasswordHasher, "verify", verify)
    for _ in range(3):
        assert change(client, current="wrong").status_code == 401
    locked = change(client)
    assert locked.status_code == 429 and locked.headers["retry-after"] == "900"
    assert calls == ["wrong"] * 3
    with TestClient(app) as same_user:
        assert login(same_user).status_code == 200
        assert change(same_user).status_code == 429
    timestamp[0] += 900
    assert change(client).status_code == 200


def test_old_password_login_cannot_survive_a_concurrent_password_change(client, app, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event

    from app import auth

    captured, release = Event(), Event()
    original = auth.new_auth_session

    def pause(db, user, request, response):
        if request.url.path == "/api/auth/login":
            captured.set()
            assert release.wait(5)
        return original(db, user, request, response)

    monkeypatch.setattr(auth, "new_auth_session", pause)
    with TestClient(app) as other, ThreadPoolExecutor(max_workers=2) as pool:
        signing_in = pool.submit(login, other)
        assert captured.wait(5)
        changing = pool.submit(change, client)
        try:
            with pytest.raises(TimeoutError):
                changing.result(timeout=0.2)
        finally:
            release.set()
        assert signing_in.result().status_code == 200
        assert changing.result().status_code == 200
        assert other.get("/api/auth/me").status_code == 401
        assert client.get("/api/auth/me").status_code == 200


def test_revoked_concurrent_changes_do_not_count_as_incorrect_passwords(client, app, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock

    from app import auth

    captured, release, all_authorized = Event(), Event(), Event()
    guard, authorized = Lock(), []
    original_hash, original_user = auth.PasswordHasher.hash, auth.require_user

    def hash_password(self, password, *args, **kwargs):
        if password == NEW:
            captured.set()
            assert release.wait(5)
        return original_hash(self, password, *args, **kwargs)

    def observe(request):
        user = original_user(request)
        with guard:
            authorized.append(user.id)
            if len(authorized) == 3:
                all_authorized.set()
        return user

    with TestClient(app) as other, TestClient(app) as third:
        assert login(other).status_code == login(third).status_code == 200
        monkeypatch.setattr(auth.PasswordHasher, "hash", hash_password)
        monkeypatch.setattr(auth, "require_user", observe)
        with ThreadPoolExecutor(max_workers=3) as pool:
            first = pool.submit(change, client)
            assert captured.wait(5)
            remaining = [pool.submit(change, account) for account in (other, third)]
            try:
                assert all_authorized.wait(5)
            finally:
                release.set()
            changed = first.result()
            assert changed.status_code == 200
            assert [future.result().status_code for future in remaining] == [401, 401]
        client.headers["X-CSRF-Token"] = changed.json()["csrf_token"]
        assert (
            change(client, current="one-wrong-password", new="another-new-password").status_code
            == 401
        )
        assert change(client, current=NEW, new="another-new-password").status_code == 200

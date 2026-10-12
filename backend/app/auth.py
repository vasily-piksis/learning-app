import hashlib
import math
import secrets
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from threading import Lock

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from .models import AuthSession, User, now

router = APIRouter(prefix="/api/auth")
hasher = PasswordHasher()
dummy_hash = hasher.hash(secrets.token_urlsafe(32))


def token_hash(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def identity(request: Request):
    token = request.cookies.get("study_session", "")
    if not token:
        return None
    with request.app.state.db.session() as db:
        auth = db.get(AuthSession, token_hash(token))
        if not auth or auth.expires <= now():
            return None
        user = db.get(User, auth.user_id)
        return (user, auth) if user and user.active else None


def require_user(request: Request) -> User:
    value = identity(request)
    if not value:
        raise HTTPException(401, "Войдите в аккаунт")
    return value[0]


def user_payload(user, auth):
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "csrf_token": auth.csrf,
    }


class Login(BaseModel):
    username: str = Field(max_length=80)
    password: str = Field(max_length=1024)


@dataclass
class LoginAttempts:
    failures: deque = field(default_factory=deque)
    pending: int = 0
    blocked_until: float = 0


class LoginLimiter:
    def __init__(self):
        self.entries = {}
        self.lock = Lock()
        self.clock = time.monotonic

    @contextmanager
    def attempt(self, key):
        with self.lock:
            timestamp = self.clock()
            for stale, entry in list(self.entries.items()):
                expires = max(
                    entry.blocked_until, entry.failures[-1] + 900 if entry.failures else 0
                )
                if entry.pending == 0 and expires <= timestamp:
                    del self.entries[stale]
            entry = self.entries.setdefault(key, LoginAttempts())
            if entry.blocked_until > timestamp:
                raise HTTPException(
                    429,
                    "Слишком много попыток. Попробуйте через 15 минут",
                    headers={"Retry-After": str(math.ceil(entry.blocked_until - timestamp))},
                )
            while entry.failures and entry.failures[0] <= timestamp - 900:
                entry.failures.popleft()
            # Reserve before hashing: parallel requests cannot exceed the same limit.
            if len(entry.failures) + entry.pending >= 3:
                raise HTTPException(
                    429,
                    "Слишком много одновременных попыток входа. Попробуйте позже",
                    headers={"Retry-After": "1"},
                )
            entry.pending += 1
        succeeded, failed = False, False
        try:
            yield
            succeeded = True
        except HTTPException as error:
            failed = error.status_code == 401
            raise
        finally:
            with self.lock:
                entry.pending -= 1
                if succeeded:
                    entry.failures.clear()
                    entry.blocked_until = 0
                elif failed:
                    entry.failures.append(self.clock())
                    if len(entry.failures) >= 3:
                        entry.blocked_until = self.clock() + 900
                if entry.pending == 0 and not entry.failures:
                    self.entries.pop(key, None)


@router.post("/login")
def login(body: Login, request: Request, response: Response):
    with (
        request.app.state.login_limiter.attempt(request.client.host),
        request.app.state.db.session() as db,
    ):
        user = db.scalar(select(User).where(User.username == body.username.strip().lower()))
        try:
            valid = hasher.verify(user.password_hash if user else dummy_hash, body.password)
        except VerificationError:
            valid = False
        if not valid or not user or not user.active:
            raise HTTPException(401, "Неверный логин или пароль")
        old = request.cookies.get("study_session")
        if old:
            previous = db.get(AuthSession, token_hash(old))
            if previous:
                db.delete(previous)
        token = secrets.token_urlsafe(32)
        auth = AuthSession(
            id=token_hash(token),
            user_id=user.id,
            csrf=secrets.token_urlsafe(32),
            expires=now() + timedelta(days=30),
        )
        db.add(auth)
        response.set_cookie(
            "study_session",
            token,
            max_age=30 * 86400,
            httponly=True,
            secure=request.app.state.settings.cookie_secure,
            samesite="lax",
            path="/",
        )
        return user_payload(user, auth)


@router.get("/me")
def me(request: Request):
    value = identity(request)
    if not value:
        raise HTTPException(401, "Войдите в аккаунт")
    return user_payload(*value)


@router.post("/logout")
def logout(request: Request, response: Response):
    value = identity(request)
    if not value:
        raise HTTPException(401, "Войдите в аккаунт")
    with request.app.state.db.session() as db:
        db.delete(db.get(AuthSession, value[1].id))
    response.delete_cookie("study_session", path="/")
    return {"ok": True}

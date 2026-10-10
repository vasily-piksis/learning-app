import hashlib
import secrets
import time
from collections import defaultdict, deque
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


class LoginLimiter:
    def __init__(self):
        self.entries = defaultdict(deque)
        self.lock = Lock()

    def check(self, key):
        with self.lock:
            timestamp = time.monotonic()
            for stale in list(self.entries):
                if not self.entries[stale] or self.entries[stale][-1] < timestamp - 600:
                    del self.entries[stale]
            bucket = self.entries[key]
            while bucket and bucket[0] < timestamp - 600:
                bucket.popleft()
            if len(bucket) >= 10:
                raise HTTPException(429, "Слишком много попыток. Попробуйте через 10 минут")
            bucket.append(timestamp)


@router.post("/login")
def login(body: Login, request: Request, response: Response):
    request.app.state.login_limiter.check(request.client.host)
    with request.app.state.db.session() as db:
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

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import secrets
from .config import Settings
from .db import Database
from .auth import router as auth_router, identity, LoginLimiter


def create_app(settings: Settings | None = None, ai=None, worker=True) -> FastAPI:
    settings = settings or Settings()
    db = Database(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield

    app = FastAPI(title="Учиться", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.db = db
    app.state.ai = ai
    app.state.login_limiter = LoginLimiter()

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("origin") != settings.app_origin.rstrip("/"):
                return JSONResponse({"detail": "Недопустимый источник запроса"}, status_code=403)
            if request.url.path != "/api/auth/login":
                value = identity(request)
                if not value:
                    return JSONResponse({"detail": "Войдите в аккаунт"}, status_code=401)
                if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), value[1].csrf):
                    return JSONResponse({"detail": "Обновите страницу: защитный токен устарел"}, status_code=403)
        return await call_next(request)

    app.include_router(auth_router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app


def production_app():
    return create_app()

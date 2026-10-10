from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import secrets
import threading
from .config import Settings
from .db import Database
from .auth import router as auth_router, identity, LoginLimiter
from .library import router as library_router
from .jobs import router as jobs_router, recover_jobs, worker_loop
from .ai import AI
from .study import router as study_router


def create_app(settings: Settings | None = None, ai=None, worker=True) -> FastAPI:
    settings = settings or Settings()
    db = Database(settings)

    @asynccontextmanager
    async def lifespan(app):
        recover_jobs(db)
        stop = threading.Event()
        thread = None
        if worker:
            thread = threading.Thread(target=worker_loop, args=(db, app.state.ai, stop), daemon=True)
            thread.start()
        try:
            yield
        finally:
            stop.set()
            if thread:
                thread.join(timeout=2)

    app = FastAPI(title="Учиться", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.db = db
    app.state.ai = ai or AI(settings)
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
    app.include_router(library_router)
    app.include_router(jobs_router)
    app.include_router(study_router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app


def production_app():
    return create_app()

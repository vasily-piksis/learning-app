import secrets
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .ai import AI
from .auth import LoginLimiter, identity
from .auth import router as auth_router
from .config import Settings
from .db import Database
from .deletion import router as deletion_router
from .jobs import recover_jobs, worker_loop
from .jobs import router as jobs_router
from .library import router as library_router
from .study import router as study_router
from .youtube import router as youtube_router


def create_app(settings: Settings | None = None, ai=None, worker=True) -> FastAPI:
    settings = settings or Settings()
    frontend, storage = settings.frontend_dir.resolve(), settings.data_dir.resolve()
    if frontend.is_relative_to(storage) or storage.is_relative_to(frontend):
        raise ValueError("FRONTEND_DIR и DATA_DIR должны быть отдельными каталогами")
    for entry in (frontend / "assets", frontend / "index.html"):
        if entry.exists() and not entry.resolve().is_relative_to(frontend):
            raise ValueError(f"Public {entry.name} must stay inside FRONTEND_DIR")
    db = Database(settings)

    @asynccontextmanager
    async def lifespan(app):
        recover_jobs(db)
        stop = threading.Event()
        thread = None
        if worker:
            thread = threading.Thread(
                target=worker_loop, args=(db, app.state.ai, stop), daemon=True
            )
            thread.start()
        try:
            yield
        finally:
            stop.set()
            if thread:
                thread.join(timeout=2)

    app = FastAPI(
        title="Учиться", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.settings = settings
    app.state.db = db
    app.state.ai = ai or AI(settings)
    app.state.login_limiter = LoginLimiter()

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method not in {
            "GET",
            "HEAD",
            "OPTIONS",
        }:
            if request.headers.get("origin") != settings.app_origin.rstrip("/"):
                return JSONResponse({"detail": "Недопустимый источник запроса"}, status_code=403)
            if request.url.path != "/api/auth/login":
                value = identity(request)
                if not value:
                    return JSONResponse({"detail": "Войдите в аккаунт"}, status_code=401)
                if not secrets.compare_digest(
                    request.headers.get("x-csrf-token", ""), value[1].csrf
                ):
                    return JSONResponse(
                        {"detail": "Обновите страницу: защитный токен устарел"}, status_code=403
                    )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(auth_router)
    app.include_router(library_router)
    app.include_router(deletion_router)
    app.include_router(jobs_router)
    app.include_router(study_router)
    app.include_router(youtube_router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    frontend = settings.frontend_dir.resolve()
    if (frontend / "index.html").is_file():
        if (frontend / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

        @app.get("/{path:path}")
        def frontend_file(path: str):
            if path == "api" or path.startswith("api/"):
                raise HTTPException(404, "Не найдено")
            candidate = (frontend / path).resolve()
            if not candidate.is_relative_to(frontend):
                raise HTTPException(404, "Не найдено")
            return FileResponse(candidate if candidate.is_file() else frontend / "index.html")

    return app


def production_app():
    return create_app()

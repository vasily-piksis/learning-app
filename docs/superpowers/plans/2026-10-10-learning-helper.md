# Learning Helper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver the approved family study app with persistent documents, scoped AI generation, private study history and Docker deployment.

**Architecture:** FastAPI serves a React SPA and same-origin API. SQLAlchemy/Alembic manage SQLite; a single durable worker processes jobs outside database transactions. OpenAI Responses uses Pydantic Structured Outputs.

**Tech Stack:** Python 3.13+, FastAPI, SQLite, SQLAlchemy, Alembic, OpenAI SDK, Argon2, PyMuPDF, Pillow; React/TypeScript/Vite, shadcn/ui; Docker Compose.

**Spec:** docs/superpowers/specs/2026-10-10-learning-helper-design.md

## Global Constraints

- Family shared library; user-owned history; no public signup or default accounts.
- Subjects → topics → cards; documents belong to topics. Original files persist.
- Files: PDF/JPEG/PNG/WebP; 20 MB; maximum 50 PDF pages; SHA256 deduplication within a topic.
- Generation: explicit topics, 1–30 cards, count ≥ topics, maximum 100,000 source characters, no silent truncation or cross-topic blending.
- Model defaults to gpt-6-luna; every model response has a strict typed schema; validate citations and MCQ correctness.
- Argon2; hashed opaque sessions, 30 days, HttpOnly/SameSite=Lax, Secure in production; CSRF/origin checks; login throttling.
- One process/container/SQLite worker; /data volume; Node only builds the frontend.
- Immutable study snapshots; idempotent attempts; optimistic conflict handling; retry interrupted jobs explicitly.

## Review Focus

- Malformed/encrypted PDFs, image decompression bombs and unsupported byte formats must fail before persistent import. The actual byte format determines MIME; misleading file extensions cannot bypass validation.
- Multiple browser tabs must not skip questions or duplicate grades.
- A valid JSON response with invented source references must be rejected atomically.
- Restart during extraction must retain completed pages and original files.
- Long Russian titles/text and narrow screens must remain usable with keyboard and touch.

## File Map

- backend/app/{config,db,models,schemas,auth,library,ai,jobs,study,main,cli}.py — bounded backend responsibilities.
- backend/alembic/{env.py,versions/0001_initial.py}, backend/alembic.ini — schema migrations.
- backend/tests/{conftest,test_auth,test_library,test_jobs,test_study,test_ai}.py — real database/API tests; only AI transport is replaced.
- frontend/src/{App,api,types}.tsx/ts, frontend/src/features/{Login,Library,Generation,Study,History}.tsx — application views.
- frontend/src/components/ui/* — CLI-installed shadcn components.
- Dockerfile, compose.yaml, .env.example, README.md — deployment and operations.

### Task 1: Persistent database and private login

**Files:** backend requirements/pytest config, app/config.py, db.py, models.py, auth.py, main.py, cli.py; migrations; tests/conftest.py, test_auth.py.
**Interfaces:** `create_app(settings: Settings, ai: AI | None = None, worker: bool = True) -> FastAPI`; `Database(settings)` with `session()`; `require_user(Request) -> User`; `create_user(db, username, display_name, password)`.

- [x] Write tests: unauthenticated API returns 401; valid login persists an opaque cookie and /auth/me identity; invalid credentials fail uniformly; missing CSRF/wrong origin fail; logout invalidates cookie; duplicate accounts fail; restart retains users.
- [x] RED: `.venv/bin/pytest backend/tests/test_auth.py -q`; expected missing application/login behavior.
- [x] Implement database pragmas, migration, models, session/auth endpoints, hidden CLI password entry and same-origin protection.
- [x] GREEN: `.venv/bin/pytest backend/tests -q`; expected all passing.
- [x] Commit `feat: add persistent private authentication`.

### Task 2: Subjects, topics and retained imports

**Files:** app/library.py, schemas.py; tests/test_library.py.
**Interfaces:** library routes `/api/subjects`, `/api/topics`, `/api/topics/{id}/documents`, `/api/documents/{id}/download`; `inspect_upload(data: bytes) -> (mime, page_count)`; persistent ingestion Job per accepted upload.

- [x] Write tests: subject/topic hierarchy; rename; PDF/image upload/download; same-topic deduplication; cross-topic duplicates allowed; invalid/oversize/encrypted/51-page uploads fail; original survives reopen.
- [x] RED: `.venv/bin/pytest backend/tests/test_library.py -q`; expected absent library routes.
- [x] Implement streamed size bounds, actual MIME checks, generated file paths, SHA256 uniqueness, persisted originals/jobs and topic version increments.
- [x] GREEN: `.venv/bin/pytest backend/tests -q`.
- [x] Commit `feat: add durable learning library and uploads`.

### Task 3: Typed AI and durable generation jobs

**Files:** app/ai.py, jobs.py; tests/test_ai.py, test_jobs.py.
**Interfaces:** `AI.extract(path, mime, page_number, local_text) -> Extraction`; `AI.generate(topic_id, sources, mode, count) -> Generated`; `AI.explain(snapshot, question, history) -> ExplanationResult`; `run_job(db, ai, job_id)`; `/api/generate`, `/api/jobs`, `/api/jobs/{id}/retry`, `/api/cards`.

- [x] Write tests: selected topics produce isolated prompts; source selection rejects foreign documents; unfinished files require consent; character/count limits fail; invalid references/refusal/incomplete responses save no cards; page cache survives partial failure; interrupted jobs fail on restart and queued survive; retry has no duplicate output.
- [x] RED: `.venv/bin/pytest backend/tests/test_ai.py backend/tests/test_jobs.py -q`.
- [x] Implement strict schemas/Responses parse, page-by-page PDF vision and cached local text, frozen source payloads, drafts/selection/edit, single worker, status polling and safe explicit retries.
- [x] GREEN: `.venv/bin/pytest backend/tests -q`.
- [x] Commit `feat: generate grounded study cards with typed AI jobs`.

### Task 4: Study snapshots, history and explanations

**Files:** app/study.py; tests/test_study.py.
**Interfaces:** `/api/study`, `/api/study/{id}`, `/api/study/{id}/reveal`, `/api/study/{id}/answer`, `/api/study/{id}/explain`, `/api/study/{id}/repeat`; answer request contains position and idempotency_key.

- [x] Write tests: MCQ hides correct answer; grade precedes advance; duplicate request unchanged; stale position conflicts; changed library card leaves snapshot unchanged; other user denied; resume after restart; repeat errors; explanation grounded in snapshot and threaded history.
- [x] RED: `.venv/bin/pytest backend/tests/test_study.py -q`.
- [x] Implement one-time shuffle, stored snapshots/order, atomic answer transaction, private history, reveal, explanation jobs, resume and new repeat session.
- [x] GREEN: `.venv/bin/pytest backend/tests -q`.
- [x] Commit `feat: persist personal study sessions and explanations`.

### Task 5: Mobile React/shadcn interface

**Files:** frontend package/config, src/api.ts, types.ts, App.tsx, features/*.tsx; tests/study.test.tsx.
**Interfaces:** typed fetch wrapper with CSRF; view state uses server sessions/jobs as source of truth.

- [x] Scaffold Vite; install shadcn via CLI and consult component documentation.
- [x] Write UI behavior tests: login error; explicit topic selection; answer saves before next question; stale session reload; drafts edit/save; loading/error states.
- [x] RED: `npm test --prefix frontend`; expected missing views.
- [x] Implement Russian screens, responsive navigation, files/download/status/retry, document filtering, generation draft selection, study/reveal/grade/explanations and history.
- [x] GREEN: `npm test --prefix frontend` and `npm run build --prefix frontend`; browser verify at 360/390/1280 widths including long text and keyboard focus.
- [x] Commit `feat: add mobile study interface`.

### Task 6: Container, operations and final integration

**Files:** Dockerfile, compose.yaml, .dockerignore, .gitignore, .env.example, README.md, scripts/backup.sh; final integration tests.
**Interfaces:** `docker compose up --build -d`; `docker compose exec app python -m app.cli create-user <login>`; /api/health; host port127.0.0.1:8080.

- [x] Package multistage image, non-root runtime, migrations before start, persistent /data, healthcheck; document login setup, env/key, HTTPS, update, consistent backup and isolated restore.
- [x] Verify pytest and frontend build; Docker build/start/create-user/login/upload/recreate retain data; backup/restore a separate volume; optionally real Luna probe only if a key is configured.
- [x] Arrange fresh whole-branch review, fix material findings with regression tests, rerun checks.
- [x] Commit `chore: package and document family study deployment`.

## Execution decision

The user explicitly confirmed the specification and requested implementation now. Proceed inline in the current workspace on a feature branch; do not add another approval round for an execution-method choice. This preserves the requested workflow and all functional requirements.

## Final verification — 2026-10-10

17 backend tests and 9 frontend tests passed; Ruff check/format, ESLint, Bandit and production frontend build passed. Docker build, login, imports, grading/resume, history, recreation and isolated backup/restore verified. Browser checks at 360/390/1280 px, including long quiz choices. Fresh whole-branch review findings corrected with RED→GREEN regressions, including hidden topic selection on subject change. Live AI probe remains conditional on the user adding a key; no paid request was made. Tasks 5 and 6 shipped together in `f40faf3`; subsequent fixes are a separate commit.

# Topic study and languages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Start either study mode from a topic, separate management screens,
preserve source languages and offer Polish, English and Russian UI.

**Architecture:** Keep existing FastAPI, SQLAlchemy/SQLite, job queue and
immutable study snapshots. Use a single bank of questions, prepare missing
quiz options in the queue, and route React pages by subject/topic. Localize
interface strings through a small typed dictionary independent of content.

**Tech Stack:** Python/FastAPI, Pydantic Structured Outputs, Alembic, React,
TypeScript/shadcn, SQLite, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-11-topic-study-redesign.md`.
Additional user instruction: Polish default interface, English and Russian
switcher; prepare plan and proceed directly to implementation in this session.

## Global Constraints

- Preserve original documents, topic IDs, question IDs and prior study snapshots.
- Keep auth, CSRF, private history, timed citations and explicit topic scoping.
- No manual subtitles or audio/video downloads; preserve transcript transport limits.
- New questions have 2–6 distinct quiz choices and one correct answer.
- Existing material limits and 1–30 questions per generation still apply.
- No implicit translation or paid generation when adding a document.
- UI locale is independent of source/question language; locale choice persists.
- Take backup before deploying migration to the existing Docker volume.

## Review Focus

- Multi-language sources must not inherit Russian from interface or warning language.
- Simultaneous auto/explicit YouTube import must converge on one retained track.
- Stale card versions during quiz preparation must reject the entire write.
- Closing/reopening a page must preserve preparation and generation tasks.
- Legacy URLs and empty topics must offer correct navigation without accidental API spend.

---

### Task 1: Content language and additive data migration

**Files:** Modify `backend/app/{models,schemas,ai,sources,jobs,library}.py`;
create `backend/alembic/versions/0003_languages.py`,
`backend/tests/test_languages.py`; update `backend/tests/fakes.py`.

**Interfaces:** Extraction and GeneratedCard add nullable `language`;
GeneratedCard/Card add nullable `target_language`. AI.generate accepts optional
`target_language=None, existing=None`; GenerateBody.mode defaults quiz for
compatibility, adds target_language. Source includes nullable language;
Card responses/snapshots include language and target_language;
Document response includes `used_for_questions` from generation payloads.

- [x] Write tests capturing AI system/user inputs for Polish/Lithuanian/English
  extraction, generation and explanation; assert no forced Russian, target
  language is explicit and store=False/typed parsing remain.
- [x] Run `.venv/bin/pytest -q backend/tests/test_languages.py`; expect failures.
- [x] Implement migration, language policy and metadata propagation. Keep older
  results valid with nullable defaults; translated output retains original sources.
- [x] Pass existing question summaries to generation. Reject exact normalized
  question/answer/language duplicates against DB and within result, transactionally,
  reporting skipped duplicates in warnings. Scope summaries and refs to topic.
- [x] Test defaults, explicit translation, mixed source language, duplicate requests
  and untouched snapshots. Run backend suite and Ruff; expect success. Commit.

### Task 2: Original YouTube subtitle selection

**Files:** Modify `backend/app/youtube.py`, `backend/tests/test_youtube.py`.

**Interfaces:** POST `/api/youtube/resolve` accepts URL, returns canonical URL,
tracks `{language,name,is_generated}`, and `selected_language: string|null`.
POST `/api/topics/{id}/youtube` accepts optional language; missing language uses
unambiguous track resolution or asks for choice. Response includes `duplicate`.
Function `list_tracks(video)` uses the existing bounded TranscriptSession.

- [x] Write tests for one track, unique generated source language, ambiguous
  manual tracks, missing captions, and auto/explicit duplicate convergence.
- [x] Run targeted tests; expect failures before implementation.
- [x] Implement resolution without calling translate or defaulting to Russian.
  Prefer manual track matching the sole generated language; if original cannot
  be inferred, return no selected language. Explicit existing imports remain valid.
- [x] Test timeouts/blocked service are useful errors, normalization/security/cache
  behavior unchanged. Run YouTube suite and Ruff; expect success. Commit.

### Task 3: Prepare legacy questions for tests

**Files:** Create `backend/app/quiz.py`, `backend/tests/test_quiz_preparation.py`;
modify `backend/app/{ai,schemas,jobs,study}.py` and test fakes.

**Interfaces:** AI.prepare_quiz(snapshot) returns typed `{card_id,options,
correct_index}`. `prepare_quiz` jobs hold topic_ids and immutable card/version/
sources snapshots. POST study returns normal session or HTTP 202
`{preparation_job: Job}`. Job data adds topic_ids for topic navigation;
prepare jobs are private to their creator. Queue worker atomically adds options
to unchanged legacy cards; no new question IDs. Existing quiz-only topics start
without preparation; flashcards always hide quiz options.

- [x] Write tests for mixed legacy/saved/draft questions, repeated start reusing
  one job, successful prep then full-topic quiz, version conflict, failure/retry,
  private job access, restart recovery and unchanged old history.
- [x] Run preparation tests; expect failures.
- [x] Implement BEGIN IMMEDIATE claim/dedup, strict result checks and all-or-none
  versioned writes; no network while holding DB transaction. Route queue execution.
- [x] Test original answer appears as the single correct option; preserved text
  and references, flash/quiz snapshots and retry semantics. Run backend suite,
  Ruff and Bandit; expect success. Commit.

### Task 4: Separate topic pages and immediate study

**Files:** Modify `frontend/src/{App,types}.tsx`/`types.ts`,
`frontend/src/features/{Library,Generation}.tsx`; create
`Topic.tsx`, `Materials.tsx`, `Questions.tsx`, `StartStudy.tsx`, `Drafts.tsx`;
modify `frontend/tests/app.test.tsx`.

**Interfaces:** routes `library`, `library/subject/:id`, `library/topic/:id`,
`library/topic/:id/materials`, `library/topic/:id/questions`,
`library/topic/:id/question/:cardId`, `library/topic/:id/create`,
`generation/:jobId`; preserve legacy generate URLs.
StartStudy receives topic_ids and renders two actions, resumes pending prep,
polls job then starts study. Creation always requests quiz bank questions.

- [x] Add regression tests for hierarchical home, two immediate study actions,
  separate question details/materials, creation without format choice, scoped
  draft review, auto subtitle choice and preparation progress/errors.
- [x] Run tests; expect failures with old pages.
- [x] Split topic management out of Library; topic overview shows study actions
  and navigation only. Separate create/status/review pages and persist direct links.
- [x] Add original subtitle resolver/chooser, duplicate notice, retained sources,
  new-material selection and translation opt-in to separate materials/create pages.
- [x] Update tests whose old mixed-screen expectations intentionally changed.
  Run Vitest, ESLint and production build; expect success. Commit.

### Task 5: Polish, English and Russian interface

**Files:** Create `frontend/src/i18n.tsx`, `frontend/src/locales.ts`,
`frontend/tests/i18n.test.tsx`; modify all feature/shared UI copy, API errors,
HTML language/title and locale-sensitive history timestamps.

**Interfaces:** `t(source, vars?)`, `useLocale()`, LocaleProvider and
LanguageSwitcher. Locale codes pl/en/ru; default pl, store only UI preference
in localStorage. Dictionary values include interface-owned states/errors.

- [x] Write tests for Polish default, switch/persistence, English and Russian
  screens, HTML lang and study content unchanged after UI switch.
- [x] Run locale tests; expect failures.
- [x] Implement explicit translated strings, interpolated counts/names and
  persistent switcher available before and after login. Localize built-in server
  errors/warnings/status messages without translating supplied academic text.
- [x] Set old Russian UI tests to explicit ru preference; check complete dictionary
  coverage. Run frontend checks; expect success. Commit.

### Task 6: Full verification, review and existing Docker update

**Files:** Update `README.md`, this plan and execution ledger.

- [x] Run `sh scripts/check.sh`; expect all tests, Ruff, ESLint, Bandit and build pass.
- [x] Build disposable QA Docker and exercise both modes, materials, generation
  review, locale persistence and old URL navigation on 360/390/1280 screens.
- [x] Run small real typed-model language probes with existing API configuration,
  preserve store=False and never print secrets or alter real study data.
- [x] Dispatch one fresh read-only whole-change reviewer under executing-plans;
  address important findings with failing regression then fix and green suite.
- [x] Back up existing Docker data; rebuild main app with same volume/settings;
  verify health, migration, previous row IDs and original file hashes preserved.
- [x] Commit final docs and report outcome plus any actual limitations.

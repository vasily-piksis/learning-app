# Свободные ответы, картинки и голос — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Native execution; implement only after the user's implementation instruction. This document does not authorize paid probes or deployment.

**Goal:** Последовательно добавить свободный письменный ответ со счётчиком
слов, описание картинки и голосовой ввод, с сохранением результатов в истории.

**Architecture:** Новые question_type free_response/picture_description в quiz,
закрытые критерии в snapshots, отдельная асинхронная Evaluation вместо изменения
детерминированного grader. Vision использует версионированный ImageAsset, голос
даёт транскрипт для той же Evaluation; бюджеты, private jobs и cleanup раздельны.

**Tech Stack:** Существующие FastAPI/Pydantic/SQLAlchemy/Alembic/SQLite,
OpenAI Structured Outputs/Audio API, React/shadcn, pytest/Vitest/Playwright;
ffprobe/ffmpeg в Docker добавляются только в голосовом этапе.

**Spec:** `docs/superpowers/specs/2026-10-14-free-responses.md`.
**Совместимость:** `2026-10-14-language-exercises.md`, `2026-10-14-question-images.md`.
**Ревью:** `docs/superpowers/reports/2026-10-14-free-responses-integration-review.md`.

## Global Constraints

- Последовательность: Tasks 1–4 письменный ответ → Task 5 картинка → Tasks 6–7 голос.
- written и прежние шесть типов сохраняют проверку без модели, mode quiz/flashcard прежний.
- Новые типы только quiz; Start не вызывает AI, paid methods только явно, не default mixed.
- Prepare/Drafts/Save до занятия; typed Structured Outputs, не парсинг свободного текста.
- Текстовый источник/ответ не переводится, UI PL/EN/RU независим; picture language явный.
- CEFR A1/A2/B1/B2/C1/C2 только language goal, тренировочная оценка по rubric.
- text ≤10000 символов/2000 слов; min/max null или 1–2000; word_count_version=1.
- word counter NFC/Unicode, internal apostrophe/hyphen; сервер источник окончательного count.
- min/max вне диапазона — предупреждение и отдельный word_limit, не запрет отправки.
- Free rubric ≤8/sum weights=100, expected points ≤12, model_answer ≤4000.
- Snapshot evidence ≤20×4000 символов, суммарно ≤80000; не runtime truncation.
- score ROUND_HALF_UP weighted 0–4 → 0–100; correct ≥70 + essential + language + word limit.
- Evaluation queued/running/failed/unknown не создаёт Attempt/не двигает position.
- Text retries ≤3 в одном бюджете, SDK retries=0; image/audio не наследуют их автоматически.
- FREE_RESPONSE_ENABLED/PICTURE_DESCRIPTION_ENABLED/TRANSCRIPTION_ENABLED=false до фаз выпуска.
- FREE_RESPONSE_DAILY_REQUEST_LIMIT=100, TRANSCRIPTION_DAILY_SECONDS_LIMIT=1800 для семьи.
- BUDGET_TIMEZONE=Europe/Vilnius, timestamps UTC; квоты не dollar cap, no quota refunds.
- Audio 15 MiB/180 s, private /data/answer-audio; raw после transcript сразу удалить,
  failed raw ≤24 h, transcript/history до явного удаления; без произношения/live/TTS.
- Миграции 0009→0010→0011 после 0008; paid Images API может оставаться отключённым.
- Прежние .env/Traefik/данные сохраняются; docs сейчас, реализация/выпуск отдельно.

## Review Focus

1. Сбой/невалидная оценка не превращается в неверный ответ; staged result и
   завершение двух workers создают ровно одну Attempt/сдвиг позиции (Tasks 2–4).
2. Старый вопрос/картинка удалены во время занятия: snapshot и собственные asset
   refs позволяют оценить прежний ответ, history delete отменяет late jobs (Tasks 3/5/6).
3. Платный повтор/double click/две вкладки/DST не обходят idempotency и квоты;
   новый результат для завершённой Attempt запрещён (Tasks 3/5/6/7).
4. Литовская/польская диакритика и распознанная/отредактированная речь не создают
   скрытый перевод или ложную оценку произношения (Tasks 1/2/4/6/7).
5. iOS/отказ микрофона/MP4 вместо WebM, blob CSP и медиа с ложным duration/MIME:
   текст остаётся доступен, сервер не доверяет браузеру (Tasks 6/7).

## Карта файлов

- `backend/app/free_responses.py` (new): Strict schemas, count, rubric/grade validation.
- `backend/app/evaluation_ai.py` (new): только model adapter, context/prompts/parse.
- `backend/app/evaluations.py` (new): private jobs/idempotency/CAS/result API и quota ledger.
- `backend/app/picture_responses.py` (new): image-source validation/preparation/snapshots.
- `backend/app/answer_audio.py` (new): media validation/private files/retention/API.
- `backend/app/transcription.py` (new): Audio API adapter и duration budget hooks.
- Existing exercises/schemas/ai/jobs/study/library/deletion/models/config/main/quiz:
  маршрутизация новых типов и сохранение прежних веток, без общего рефакторинга.
- `frontend/src/features/exercises/FreeResponse.tsx`, `FreeResponseSettings.tsx`,
  `EvaluationFeedback.tsx`, `VoiceAnswer.tsx` (new): отдельные editor/input/feedback.
- `frontend/src/lib/word-count.ts` и `tests/fixtures/word-count-v1.json` (new):
  клиентский счётчик и общий fixture для pytest/Vitest.
- Alembic 0009_free_responses/0010_picture_responses/0011_answer_audio;
  numbers проверить на исполнении. Existing check/deploy/backup продолжают работать.

## Task 1: Контракт свободного ответа и счётчик

**Files:** Create `backend/app/free_responses.py`,
`backend/tests/test_free_response_schemas.py`, `backend/tests/test_word_count.py`,
`tests/fixtures/word-count-v1.json`, `frontend/src/lib/word-count.ts`,
`frontend/tests/word-count.test.ts`; modify `backend/app/exercises.py`, `schemas.py`,
`frontend/src/types.ts`, `frontend/src/lib/exercises.ts` (создаются предыдущим планом).

**Interfaces:**
- `count_words(text: str) -> int`, TS `countWords(text: string): number`, version=1.
- `FreeResponseExercise`/`FreeResponseEvaluation` по spec; enum goal/level,
  closed lists вместо dynamic dict в модельном response; answer text остаётся raw.
- `validate_evaluation(exercise: FreeResponseExercise, answer: str,
  result: FreeResponseEvaluation) -> EvaluationGrade`: computed score/correct,
  word_count/word_limit, validated IDs/corrections/evidence; не вызывает модель.
- `solution_text` для нового типа возвращает model_answer; обычный grade_answer
  отвергает этот тип как `RequiresEvaluation`, никогда не запускает exact match.
- `public_exercise` выдаёт goal/level/language/min/max до ответа, скрывает
  expected_points/model_answer/criteria details/source text. После ответа feedback
  может показывать rubric и пример. Обязательный набор критериев не изменяется AI.
- `canonical_submission` для новых типов сохраняет free_text/audio_answer_id,
  отвергает клиентскую _grading; прежние поля типов не расширяются. _grading v2
  по spec, deterministic v1 и legacy без версии читаются по своим веткам.

- [ ] Написать тесты: empty/punctuation/emoji=0; don't/biało-czerwony/123=1;
  «Ąžuolas, stalas!»=2; NFC/NFD count равен; em dash/zero width разделяет.
  pytest/Vitest читают один fixture, supplementary Unicode и combining marks.
- [ ] Тесты schemas: min>max/level для content/weights !=100/duplicate IDs/слишком
  большой ответ отвергаются; min/max=null допустимы; вне учебного диапазона не 422.
  Unknown критерии, corrections.original не подстрока ответа, несовпадение refs
  и отсутствие criterion score отвергаются, weighted округление HALF_UP проверено.
  Insufficient_context → failed/no grade, не zero score; до Attempt нельзя reveal/explain.
- [ ] Run `.venv/bin/pytest -q backend/tests/test_word_count.py backend/tests/test_free_response_schemas.py` и `npm test --prefix frontend -- word-count` → новые тесты FAIL.
- [ ] Реализовать схемы/счётчик/маршрутизацию; контракты прежних six types неизменны.
- [ ] Повторить команды → PASS; локальный коммит только исходников/fixtures после git audit.

## Task 2: Подготовка критериев и адаптер оценки

**Files:** Create `backend/app/evaluation_ai.py`,
`backend/tests/test_free_response_generation.py`, `backend/tests/test_evaluation_ai.py`;
modify `backend/app/ai.py`, `jobs.py`, `schemas.py`, `regeneration.py`, `quiz.py`.

**Interfaces:**
- GenerateBody.free_response_settings: goal, language, level, min_words, max_words;
  один topic, тип free_response (до Task 5); смешение со старым семейством=422.
  language level обязателен, content level=null; known source language locked,
  unknown требует явного подтверждения, incompatible/mixed selection=422 без перевода.
- `EvaluationAI.evaluate(snapshot: dict, answer: str,
  before_request: Callable[[], None]) -> FreeResponseEvaluation`: hook непосредственно
  перед каждой внешней отправкой, включая retry. AI.parse получает optional
  before_request hook, default None; прежние callers/retry поведение неизменны.
- `build_free_snapshot(card: dict, source_fragments: list) -> dict`, snapshot v3;
  evidence refs из разрешённого подготовленного набора, bounds из Global Constraints.
- Preparation сохраняет exercise/evidence с draft, version guard и fingerprint;
  критерии свободного ответа регенерируются вместе с вопросом и примером.
  Applied fingerprint/result и image_updates предыдущих планов сохраняются.

- [ ] Тест generation: content не штрафует орфографию, language содержит level,
  альтернативный ответ принимается по rubric, criteria edits влияют только на
  новые snapshots; противоречие/слишком широкий evidence → insufficient outcome.
  A1 принимает простое достаточное объяснение; B2 получает отдельную обратную
  связь о связности/словаре, а не автоматический фиксированный минимум слов CEFR.
- [ ] Тест без источников/чужие refs/неоднородный язык/target_language/смешение
  семейств; отсутствие автоматического перевода, исправления на языке задания.
  Prompt treats documents/user answer как данные, команды «поставь 100» игнорируются.
- [ ] Тест SDK-generated JSON schema: closed root/nested objects, required/nullable,
  compatible unions, отсутствие Any/dynamic dict; raw completion parsed and validated.
  Refusal/incomplete/invalid rubric → failed, не zero score/repair paid request.
  Assessability insufficient_context также без Attempt/score; bounds списков/строк
  и реальная enum/int в score защищают парсер от неограниченного результата.
- [ ] Retry tests: transient ≤3, each before_request invoked; nontransient/quota
  error=1, долгий Retry-After не игнорируется, SDK retries=0; mock only.
- [ ] Run `.venv/bin/pytest -q backend/tests/test_free_response_generation.py backend/tests/test_evaluation_ai.py backend/tests/test_retry.py` → FAIL; реализовать → PASS.
- [ ] Проверить regenerate/apply/discard/replay нового типа и legacy regression;
  зафиксировать локальный коммит этапа.

## Task 3: Асинхронная Evaluation, история, лимиты и миграция

**Files:** Create `backend/app/evaluations.py`,
`backend/alembic/versions/0009_free_responses.py`,
`backend/tests/test_evaluations.py`, `backend/tests/test_evaluation_recovery.py`,
`backend/tests/test_evaluation_history.py`; modify `models.py`, `config.py`,
`jobs.py`, `study.py`, `library.py`, `deletion.py`, `main.py`, `.env.example`.

**Interfaces:**
- Evaluation(unique session_card_id, user_id, request_key/fingerprint, Job,
  submission, status, revision, staged_result, applied_result), EvaluationRequest
  по spec; original submission immutable. 0009 после 0008, старые rows/JSON не менять.
- POST `/api/study/{id}/answer`: для free_response новый `free_text` ≤10000,
  `audio_answer_id` только с Task 6; text прежнего written ≤1000 не расширять.
  Ровно один input; response 202 `{evaluation_id,job_id,status}` либо готовый feedback.
- GET `/api/study/{id}/evaluations?position=N`: свой status/immutable submission,
  безопасная ошибка и готовый feedback; не выдать source prompt/private solutions.
- POST `/api/evaluations/{id}/retry {idempotency_key,acknowledge_extra_cost:true}`:
  тот же submission, only failed/unknown; новый key с учётом квоты, completed=409.
  Generic `/jobs/{id}/retry` для evaluate_response=409; list/detail только owner.
  Private ownership распространяется на prepare_picture/transcribe_answer
  при следующих задачах; очистка сохраняет Job tombstone/ledger без учебного контента.
- `finalize_evaluation(database, evaluation_id, revision, validated_result)`:
  BEGIN IMMEDIATE/CAS alive session/current position/revision/status, одна Attempt
  (_grading v2), один position increment, stage result+commit атомарны в SQLite.
- `reserve_evaluation_request(database, job_id, request_key)`: family daily100,
  BUDGET_TIMEZONE/DST, UTC timestamps, called Task 2 before_request на каждом retry.
- StartBody.include_ai_evaluated=false; new types explicit flag/availability;
  runtime feature off/missing key →409, no Job/provider call. Defaults exclude them.

- [ ] Тест 202→pending→feedback/history: позиция/счёт до финала неизменны, ошибка
  API не неверный ответ; failed виден после reload; duplicate key/payload возвращает
  прежнее, другой текст/key=409; completed retry/generic retry запрещены.
- [ ] Две вкладки/workers: один active Evaluation, один Attempt/position advance;
  crash before/after staged result, commit timeout replay, no provider rerun on restart.
  Worker не держит write-lock во время вызова; before_request квота каждого retry.
- [ ] Лимиты concurrent100/101, ручной retry, failed/unknown no refund,
  DST/сутки/смена конфигурации; history delete не обнуляет ledger. Ledger purge30d.
- [ ] Старые deterministic/flashcard Start/Answer/Repeat/Explain unchanged;
  types=null/mixed не включает free, explicit missing_pairs и runtime недоступность;
  flashcard не включает free. Авторизация/CSRF/owner jobs/no solutions в ошибках.
- [ ] Delete Card/Topic/Subject во время ответа оставляет session evidence;
  delete session cancels/clears Evaluation/Job payload/result и late worker;
  repeat копирует v3 snapshot/images, создаёт новую Evaluation только на новый ответ.
- [ ] Run `.venv/bin/pytest -q backend/tests/test_evaluations.py backend/tests/test_evaluation_recovery.py backend/tests/test_evaluation_history.py backend/tests/test_study.py backend/tests/test_history_deletion.py` → FAIL; реализация → PASS.
- [ ] Миграция 0008→0009 на копии: old data/files неизменны, integrity/FK checks;
  model config без платной пробы. Локальный коммит.

## Task 4: Письменный UI и самостоятельный выпуск

**Files:** Create `frontend/src/features/exercises/FreeResponse.tsx`,
`FreeResponseSettings.tsx`, `EvaluationFeedback.tsx`,
`frontend/tests/free-response.test.tsx`, `frontend/e2e/free-response.spec.ts`;
modify Generation/Drafts/Questions/StartStudy/StudySelection/Study/History,
exercises/EditQuestion.tsx/ExerciseSolution.tsx, types.ts, locales.ts,
`backend/tests/browser_server.py`, README.

- [ ] Vitest: settings goal/level/min/max, local count100–150, below/above
  warning can submit, no API per keystroke; private criteria editing only editor,
  paid method opt-in, unavailable evaluation не скрывает готовые задания.
- [ ] Реализовать textarea/free_text, paid submit, frozen submission pending,
  reload статус, explicit same-answer retry; результаты score/rubric/errors/
  word_limit раздельно, failed отдельно от red wrong answer, labels+icons.
- [ ] E2E desktop/mobile: Prepare/Draft/Edit/Save/Start/Answer/Pending/Result/
  History/Repeat; PL/EN/RU; Lithuanian answer remains Lithuanian, A1 vs B2 rubric;
  source/card delete, private foreign access, две вкладки, return to originating topic.
- [ ] `npm test --prefix frontend -- free-response` и `npm run test:e2e --prefix frontend -- free-response` сначала FAIL, после реализации PASS; console/keyboard/overflow screenshots.
- [ ] `sh scripts/check.sh`; независимый письменный выпуск, аудио/vision flags off.
  Cold backup с остановкой writes, миграция копии, smoke/health, реальный rollback
  старым image+backup в изолированном томе; .env/Traefik/uploads не затираются.

## Task 5: Описание картинки как отдельный законченный этап

**Files:** Create `backend/app/picture_responses.py`,
`backend/alembic/versions/0010_picture_responses.py`,
`backend/tests/test_picture_responses.py`, `frontend/e2e/picture-response.spec.ts`;
modify exercises.py/free_responses.py/evaluation_ai.py/regeneration.py/
question_images.py/models.py/jobs.py/study.py/deletion.py/library.py/config.py,
FreeResponseSettings.tsx/QuestionImages.tsx/EvaluationFeedback.tsx,
frontend/tests/free-response.test.tsx, locales.ts, browser_server.py, README.

**Interfaces:**
- TextEvidence/ImageEvidence discriminated union; старый SourceRef сохранён.
  `PictureDescriptionExercise`, snapshot_version=4, image_role=source/hash bound.
  JobImage.role candidate/context с default candidate для старых rows; context
  удерживает source только до terminal/отмены и не участвует в candidate discard.
- POST `/api/topics/{id}/picture-drafts`: multipart image/language/level/min/max/key;
  PictureDraftSetup(needs_criteria), draft Card и normalized image без AI;
  PictureDraftRequest unique(user_id,key), fingerprint→Card ID, no resurrection.
  Question template на выбранном языке задания, не locale UI; пустой draft
  не попадает в ready/start. image_role принадлежит CardImage/SessionImage связи.
- POST `/api/cards/{id}/prepare-picture {version,language,level,min_words,max_words,
  idempotency_key}`: draft question image → criteria candidate private Job;
  нет обязательного Document. Existing regeneration apply contract применяет
  question/criteria/image_updates атомарно и увеличивает Card.version один раз.
- `get_picture_evidence(db, session_card_id, user_id) -> VerifiedImageBytes`:
  только SessionImage источника, без cookie URL/direct paths в model input.
  generate/evaluate/regenerate/explain picture используют источник по своему
  Card/Session snapshot, illustration ветки не изменяются.
- Availability new type uses source ImageAsset, не только has_ready_materials
  текстового Document; отсутствующий image/criteria не ready. New config flag.

- [ ] Тест image-only draft/prepare/save/start без Document, source language
  явно PL/EN/RU/LT, generated picture optional; no translation/model input для
  остальных типов. Same key/сохранившийся candidate не повторяет платную preparation.
  Upload duplicate не создаёт две Card, changed body=409, deleted draft replay=410;
  criteria-pending draft cannot Save/Start until full validated exercise exists.
- [ ] Source replace/remove делает Card draft и инвалидирует criteria; parent
  edit criteria/no source replace остаётся разрешён. Asset/hash mismatch/удалённый
  candidate отвергается до paid call. Atomic apply source+criteria+version/replay.
- [ ] Тест модели: правильные байты, typed visual points, чужие IDs/ссылки
  запрещены; не принимает отсутствующую vision capability как text-only успех.
  Наблюдаемые детали без вымышленных имён/мест; alt/public JSON не содержит эталон.
- [ ] Study/Card delete/replace/repeat используют старую source картинку,
  history delete/late jobs/last refs очищают файл; owner answer refs сохраняются.
  Pending vision job входит в image cleanup refs до terminal/очистки payload.
- [ ] `.venv/bin/pytest -q backend/tests/test_picture_responses.py backend/tests/test_question_images.py backend/tests/test_evaluations.py` → FAIL; реализация → PASS.
- [ ] E2E picture draft→prepare→save→describe→result/history/repeat, desktop/mobile,
  PL/EN/RU, source conflict/no files leak; no paid fixture. `sh scripts/check.sh`.
- [ ] Миграция 0009→0010, backup/restore/rollback с illustration/source отличием,
  отдельный выпуск только picture flag, transcription off; .env preserve.

## Task 6: Приватное аудио, транскрипция и очистка

**Files:** Create `backend/app/answer_audio.py`, `backend/app/transcription.py`,
`backend/alembic/versions/0011_answer_audio.py`,
`backend/tests/test_answer_audio.py`, `backend/tests/test_transcription.py`,
`backend/tests/test_audio_cleanup.py`; modify models/config/jobs/study/
evaluations/deletion/main, Dockerfile, `.env.example`, README/backup documentation.

**Interfaces:**
- AudioAnswer по spec; TranscriptionRequest metadata/duration ledger;
  `validate_audio(path: Path) -> ValidatedAudio` (mime, duration, sha256, normalized_path),
  ffprobe argv/timeout10 s, ffmpeg argv/timeout30 s, only local files/no shell/network.
- POST `/api/study/{id}/audio {position,idempotency_key,file}` multipart:
  ≤15 MiB/180 s, own active session/free family, return202 audio_answer_id/private Job.
- GET `/api/audio-answers/{id}`: own transcript/status/expires, no filesystem path;
  GET `/{id}/recording`: own/not expired, no-store/nosniff, after transcript=404.
  DELETE `/{id}`: own before Evaluation, cancel active Job and cleanup, idempotent.
- POST `/{id}/retry {idempotency_key,acknowledge_extra_cost:true}`: failed/unknown,
  raw still available, one call/one new duration reservation; generic retry=409.
- `Transcriber.transcribe(audio: ValidatedAudio, language: str) -> Transcript`:
  gpt-transcribe default, SDK retries=0, original language/no translation,
  timeout result unknown. Cache transcript before raw unlink; missing raw=record again.
- Final POST /answer `{free_text,audio_answer_id}` checks owner/card/expected_language,
  AudioAnswer transcript ready; original vs submitted text stored in _grading v2,
  was_edited computed server-side. Other Answer forms + audio ID=422.
- `cleanup_answer_audio(database)` uses terminal state/revision, expiry24h,
  shared exclusive claim then unlink; raw file deletion never erases transcript.

- [ ] Тест MIME spoof/corrupt/video/audio bombs/max bytes/duration unknown/infinite,
  MP4/WebM/Ogg/WAV; server duration overrides client; argv/no shell/protocol/timeout.
  Invalid/media validation fail no API request; normalized temporary file cleanup.
  Decoded WAV samples определяют duration; ffprobe metadata не обходят180 s;
  decode максимум181 s, >180 отвергается, не обрезается в допустимую запись.
- [ ] Idempotent hash/key/active request, private endpoints/CSRF, quota1800 s
  including concurrent/manual retries/round-up/DST/no refund; one audio call max.
  No key/model/flag → no external call, text works; payload cannot change language.
- [ ] Transcript persisted before cleanup, raw unlink fail retry without new API;
  unknown RAM-only completion not called cached, expired recording requires re-record.
  Edited transcript marks was_edited and stores original/final counts in history.
- [ ] Delete session during upload/transcribe/evaluate prevents late resurrection,
  removed Card doesn't break active snapshot; .part/crash/stale worker expires;
  running job not deleted by TTL, orphan recovery marks unknown; ledger30d retention.
- [ ] `.venv/bin/pytest -q backend/tests/test_answer_audio.py backend/tests/test_transcription.py backend/tests/test_audio_cleanup.py backend/tests/test_evaluations.py` → FAIL; реализация → PASS.
- [ ] Install ffmpeg/ffprobe only in runtime stage, preserve non-root; small actual
  generated media fixtures in tests, no user's audio/paid API. Migration0010→0011
  preserves data, private audio dir included in protected backup, review build context.

## Task 7: Голосовой UI, браузер и общая приёмка

**Files:** Create `frontend/src/features/exercises/VoiceAnswer.tsx`,
`frontend/tests/voice-answer.test.tsx`, `frontend/e2e/voice-answer.spec.ts`;
modify FreeResponse.tsx/EvaluationFeedback.tsx/Study.tsx/History.tsx/locales.ts,
frontend/playwright.config.ts, backend/tests/browser_server.py, main.py CSP, README.

- [ ] Vitest fake MediaRecorder: start/stop180 s/track cleanup, format selection,
  permission denied/not supported/text fallback, local replay/re-record, release
  blob URLs; no API on recording, explicit paid transcription then explicit grading.
- [ ] Реализовать Напиши/Расскажи только free family, timer before transcript/count
  after; original/edited distinction; message raw audio not retained in history;
  retry/error without attempt penalty, reload transcript/private Job восстановление.
- [ ] CSP only media-src self blob, no broader image/connect rules; no microphone
  on mount/background, tab leave releases tracks. Auth recording endpoint after upload.
- [ ] E2E Chromium fake microphone: voice→transcript→edit→count→grade/history;
  quota/timeout/duplicate submit/reload/text fallback/private access/deletion.
  WebKit recorder/MP4 path + permission denial through controlled fixtures;
  supported MIME feature detection instead of claiming all browsers use WebM.
- [ ] `npm test --prefix frontend -- voice-answer` и `npm run test:e2e --prefix frontend -- voice-answer` → FAIL, после реализации PASS. Вручную actual iOS Safari
  microphone/HTTPS/record/upload; если устройства нет, явно ограничить QA claim.
- [ ] Полная браузерная регрессия прежних types/images/library/history/password;
  desktop/mobile PL/EN/RU/keyboard/console; `sh scripts/check.sh` и Docker media smoke.
- [ ] Проверить все migrations/restore/cold-backup/rollback на копии данных;
  flags только по фазам, no paid startup tests, .env secrets не Git. Перед commit/
  push/main/deploy сверить разрешение пользователя; эта подготовка плана не выпуск.

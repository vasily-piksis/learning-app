# Изображения вопросов и ответов — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Execute after the language-exercises plan; no implementation or paid calls have started.

**Goal:** Добавить приватные иллюстрации к вопросу/ответу, ручную загрузку и
необязательную поштучную AI-генерацию, сохранив изображения в истории.

**Architecture:** Неизменяемые ImageAsset и связи CardImage/SessionImage/JobImage.
Редактор работает с кандидатами; атомарное сохранение Card фиксирует изображение,
занятие сохраняет собственные ссылки и alt. Авторизованные endpoints выдают
файлы с проверкой контекста; cleanup проверяет все ссылки перед удалением.

**Tech Stack:** Существующие FastAPI/SQLAlchemy/Alembic/SQLite/Pillow,
React/shadcn, OpenAI Python SDK Images API, pytest/Vitest/Playwright и Docker.

**Spec:** `docs/superpowers/specs/2026-10-14-question-images.md`.
**Второе ревью:** `docs/superpowers/reports/2026-10-14-language-images-integration-review.md`.
I01–I06/I08–I10 уточнены ниже; I07 закрыт ответом пользователя: только иллюстрации.

## Global Constraints

Ограничения этого этапа не запрещают отдельно подтверждённый следующий план
`2026-10-14-free-responses.md`. Его picture_description добавляет source роль
на связи CardImage/SessionImage и vision только этому типу; illustration остаётся
без vision. При интеграции cleanup учитывает новые Job refs, заменённый source
требует новых criteria, история использует собственные неизменные связи.
0008 можно установить с IMAGE_GENERATION_ENABLED=false до 0009; реальная
генерация картинок не является prerequisite свободных ответов или описания.

- По одной необязательной картинке к вопросу и к ответу.
- Upload: JPEG/PNG/WebP, 10 MiB, 20 мегапикселей, длинная сторона ≤2048.
- Static WebP, ориентация исправлена, EXIF удалён, alpha сохранена; alt ≤500 символов.
- Файлы в /data/question-images; никаких публичных static URLs или Git-данных.
- Answer image/ID/alt скрыты в занятии до answer/reveal и не предзагружаются.
- Старые занятия используют свои неизменные изображения; очистка только последней ссылки.
- Нет перевода учебного содержимого, аудио и автоматической генерации картинок.
- Картинки только иллюстрации; вопрос/ответ определяются из текста без картинки.
- Regenerate/explain не получают изображения; соответствие иллюстрации проверяется в preview.
- IMAGE_GENERATION_ENABLED=false, OPENAI_IMAGE_MODEL задаёт оператор.
- n=1, 1024x1024, quality=low, webp; limit default 10 попыток провайдера/день для семьи.
- IMAGE_BUDGET_TIMEZONE=Europe/Vilnius по умолчанию; timestamps UTC, границы через ZoneInfo/DST.
- Для Images API нет автоматических retries; текстовая политика трёх попыток не меняется.

## Review Focus

1. Замена/удаление картинки Card, на которую ссылаются несколько старых занятий —
   байты доступны через собственную историю/повтор до удаления последней ссылки (Task 1/2/4).
2. Скрытая answer image может утечь через ID/alt/direct URL/preload — проверяются
   JSON и оба контекста выдачи; общая библиотека не обещает режим экзамена (Task 1/2/4).
3. Worker завершает generation после ручной правки/удаления вопроса — не
   прикрепляет картинку и не оставляет бесхозный файл (Task 3/4).
4. Двойной клик/timeout/повтор HTTP не должны незаметно удвоить оплату — проверяются
   idempotency, лимит ImageRequest, запрет generic retry и SDK retries (Task 3).
5. Изменение текста и изображения в одной форме не конфликтует само с собой —
   upload лишь создаёт кандидата, Card.version меняется один раз при Save (Task 1/2/4).

## Task 1: Приватные файлы, кандидаты и ссылки истории

**Files:** Create `backend/app/question_images.py`,
`backend/alembic/versions/0007_question_images.py`,
`backend/tests/test_question_images.py`, `backend/tests/test_image_cleanup.py`;
modify `backend/app/models.py`, `schemas.py`, `jobs.py`, `study.py`, `deletion.py`,
`main.py`. На реализации проверить, что текущий head действительно 0006.

**Interfaces:**
- ImageAsset/CardImage/SessionImage/JobImage по spec; unique CardImage(card_id,slot),
  SessionImage(session_card_id,slot), индекс asset_id и FK checks.
  CardImage хранит alt; SessionImage фиксирует её при создании занятия.
  Repeat копирует старые SessionImage с новыми session_card_id/URL атомарно.
  Нынешний repeat(snapshot-only) расширяется; Legacy session без связей — без картинки.
- `POST /api/cards/{id}/image-candidates`: multipart file, slot, version →
  приватный draft asset; версия Card не меняется. Клиент получает ID, metadata,
  безопасный endpoint предпросмотра, без пути на диске.
- `GET /api/cards/{id}/image-candidates`: собственные draft/obsolete,
  пагинация до 50, явный can_apply и причина конфликта. Чужие private draft не видны.
- `GET /api/image-candidates/{id}/preview`: owner/auth/card alive,
  декодированные безопасные байты, no-store. Same-origin src, без blob URLs/CSP изменения.
- `POST /api/image-candidates/{id}/rebase {version}`: owner и текущая Card.version;
  после явного просмотра переводит obsolete в draft с новым target_version,
  без изменения файла, Card.version и вызова модели. Deleted Card → 404.
- CardEdit.image_updates: необязательные question/answer `{asset_id: str | None, alt: str}`.
  None для image_updates оставляет связи прежними; asset_id=null явно убирает slot.
  Проверяются принадлежность кандидата/target/version/slot и разрешение пользователя;
  текст и картинки сохраняются одной транзакцией с одним увеличением Card.version.
  Применение переводит asset в ready и убирает draft target/JobImage refs;
  Job сохраняет только applied metadata без отдельного удержания файла.
  В image-этапе apply-regeneration получает тот же image_updates и выполняет
  текст+связи+version+applied_result/fingerprint в той же транзакции.
- `DELETE /api/image-candidates/{id}`: только разрешённый draft,
  идемпотентный отказ; текущие/исторические asset не удаляются.
  Discard удаляет все candidate/Job refs и ставит discarded; obsolete остаётся
  видимым владельцу до решения. Не использовать target_card_id как вечную ссылку.
- `GET /api/cards/{id}/images/{slot}`: общая библиотека после входа.
- `GET /api/study/{id}/cards/{position}/images/{slot}`: владелец+SessionImage,
  answer требует revealed или Attempt. Внешних ссылок на файловый путь нет.
- `cleanup_image_assets(database)`: удаляет только недостижимые assets через
  CardImage/SessionImage/JobImage и допустимые draft references; безопасен повтор.
  Под write-lock claim deleting после проверки ссылок; attach запрещён для
  deleting/discarded. Retry unlink идемпотентен. Учитываются writing rows и .part
  файлы, восстановление проверяет все точки сбоя записи/rename/commit.

- [ ] Написать тесты upload real bytes, MIME spoof, SVG/animation, corrupt,
  10 MiB/20MP границы, EXIF/ориентация/alpha; несоответствие version/target/slot.
- [ ] Тесты атомарности: ошибка текста не прикрепляет картинку, Save меняет
  version ровно раз; старый CardEdit без поля сохраняет image; replace/cancel
  сохраняют оригинал. Собственный кандидат возвращается после закрытия страницы.
  Stale кандидат доступен для preview/free rebase/delete; atomic regeneration
  keep/remove/replace не конфликтует сама с собой и не применяет половину операции.
- [ ] Тесты study: snapshot фиксирует image+alt, до ответа нет answer ID/alt;
  direct URL hidden answer=403/404; anonymous/other-user history запрещены,
  library image требует auth; после reveal/attempt — правильные байты.
- [ ] Тесты last-reference: Card delete→история жива; две истории, удаление
  одной не убирает файл; final bulk-delete очищает файл; topic/subject delete
  отменяет кандидатов/Job; повреждённая/отменённая запись не оставляет файл.
- [ ] Repeat после replace/delete Card использует прежний asset/alt, затем
  удаление исходного занятия не удаляет файл повтора; final delete очищает его.
  Concurrent attach/cleanup не оставляет связь на удалённые байты;
  failed unlink/writing/.part восстанавливаются без нового вызова API.
- [ ] `.venv/bin/pytest -q backend/tests/test_question_images.py backend/tests/test_image_cleanup.py` → новые тесты FAIL; реализовать; повтор → PASS.
- [ ] Миграция на копии 0006 добавляет таблицы, не меняет старые строки/JSON/файлы;
  FK/integrity проверки проходят. Резервная копия включает новый каталог.

## Task 2: Интерфейс ручной загрузки и самостоятельная приёмка

**Files:** Create `frontend/src/features/exercises/QuestionImages.tsx`,
`frontend/tests/question-images.test.tsx`, `frontend/e2e/question-images.spec.ts`;
modify `frontend/src/features/exercises/EditQuestion.tsx`, `RegenerateQuestion.tsx`,
`ExerciseSolution.tsx`, `frontend/src/features/Study.tsx`, `Questions.tsx`,
`Drafts.tsx`, `types.ts`, `locales.ts`, `backend/tests/browser_server.py`, README.

- [ ] Написать Vitest: upload→same-origin preview→replace/cancel→совместный Save,
  alt, list draft/obsolete после reload, бесплатный явный rebase. Никакого
  image-provider import/call и платной кнопки на этом независимом этапе.
- [ ] Реализовать два slot блока и image_updates; extend apply-regeneration
  тем же контрактом. Одно увеличение Card.version; прежний image остаётся
  до применения, история не меняется. Старый текстовый apply без image_updates
  сохраняет текущие связи; keep/remove/replace явно видны в сравнении.
- [ ] Подпись уточняет роль иллюстрации; вопрос не требует визуального
  распознавания. Тесты regenerate/explain проверяют отсутствие image inputs
  и новых asset-source references. Preview не утверждает AI-проверку картинки.
- [ ] E2E desktop/mobile: upload→save→study→reveal→history→repeat;
  replace/delete Card→старый repeat сохраняет image/alt; удалить исходную
  историю→repeat сохраняет файл; final delete→последняя ссылка очищается.
  Hidden answer не грузится до раскрытия; active snapshot не меняется.
- [ ] Проверить авторизацию/CSRF, own draft preview и private history,
  CSP без blob URLs, обе локализации входов и PL/EN/RU, keyboard/overflow/console.
  Неприменённые text/alt поля не обещают autosave; файл draft возвращается.
- [ ] Тесты сначала FAIL, затем PASS; `sh scripts/check.sh`, визуальные снимки,
  аудит tracked файлов. Этот upload-only этап можно выпустить без Images API
  по согласованному backup/migration/rollback регламенту и разрешению пользователя.

## Task 3: Необязательная поштучная генерация через OpenAI

**Files:** Create `backend/app/image_generation.py`,
`backend/tests/test_image_generation.py`,
`backend/alembic/versions/0008_image_requests.py`; modify `backend/app/config.py`,
`jobs.py`, `deletion.py`, `.env.example`, README; реальную .env не коммитить.

**Interfaces:**
- `POST /api/cards/{id}/generate-image {version, slot, prompt, idempotency_key}` →
  Job.kind=generate_image; prompt ≤2000 символов, настройки серверные.
- `ImageGenerator.generate(prompt: str) -> GeneratedImage`:
  bytes и доступные metadata; model из config, n=1, 1024/low/webp,
  SDK max_retries=0. Ошибка неопределённого исхода выделена отдельно.
- Worker пишет тот же проверенный draft ImageAsset через Task 1, не меняет Card;
  JobImage связывает файл с Job. Применение — обычный CardEdit.image_updates.
- ImageRequest: unique(job_id,attempt_no), unique(user_id,request_key),
  UTC reserved_at, status reserved/sent/succeeded/failed/unknown, captured
  model/settings и безопасные usage metadata, без prompt/изображений/секретов.
  Миграция 0007→0008 не затрагивает старые учебные строки/файлы.
- Transactional idempotency/daily request counter: default limit 10;
  известный повтор того же key возвращает Job, новый payload с тем же key=409.
  При running card/slot не создаётся второй запрос. API-квота/секреты не логируются.
- `POST /api/jobs/{id}/retry-image {idempotency_key, acknowledge_extra_cost:true}`:
  только владелец failed/unknown image Job, новая ImageRequest/attempt_no,
  явно платная кнопка; общий /jobs/{id}/retry для generate_image=409 без вызова.
  Под worker write-lock квота резервируется непосредственно перед API-send,
  а не по Job.created. Нет auto restart/retry после unknown; false refunds запрещены.
- Config/model проверяются без тестовой генерации. Job фиксирует model/settings
  для выполнения; одинаковый request key не меняет их при последующем изменении .env.
  Feature flag отключён до отправки — Job не вызывает API. Private image Job
  detail/result/retry доступны только владельцу, active другой user → busy без Job data.
- `POST /api/jobs/{id}/retry-image-save`: если байты долговременно staged,
  завершает только локальное сохранение без новой ImageRequest/API-call;
  если байтов нет после сбоя — unknown с честным указанием возможной оплаты.

- [ ] Тесты disabled/missing model/no provider access не затрагивают upload/текст;
  один Job/одна картинка/один вызов; общий дневной лимит с concurrent requests;
  duplicate key/mismatched payload; settings от клиента не обходят лимит/quality.
- [ ] Один Job после 10 ручных попыток исчерпал лимит; 11-я/конкурентная
  не отправляются. DST/граница суток по IMAGE_BUDGET_TIMEZONE, Job вчера/
  attempt сегодня. Timeout/crash/cancel не возвращают слот; retry generic=409.
  Перезапуск/config toggles/list model не создают картинку и не обходят budget.
- [ ] Тесты timeout/refusal/400/429: нет второго автоматического вызова;
  пользовательский ручной повтор отдельно учитывается. Локальная ошибка сохранения
  не вызывает генерацию повторно. Кандидат сохраняется для preview после reload.
- [ ] Перед отправкой и после ответа восстановление не выдумывает успех;
  staged bytes позволяют только local-save retry, RAM-only lost не объявляется
  сохранённой картинкой. ImageRequest metadata переживает очистку учебного payload.
- [ ] Тесты изменение Card.version/delete/cancel во время вызова: Job не
  прикрепляет данные к новому вопросу, поздний файл убирается по правилам ссылок.
- [ ] `.venv/bin/pytest -q backend/tests/test_image_generation.py` → FAIL;
  реализовать адаптер, Job и ограничения → PASS. Реальных платных вызовов в CI нет.
- [ ] Перед включением отдельно выбрать model и сверить актуальную цену/доступ
  по официальной документации. Не обещать фиксированную стоимость за изображение.

## Task 4: Платная опция в интерфейсе, браузер и выпуск

**Files:** Modify `frontend/src/features/exercises/QuestionImages.tsx`,
`frontend/tests/question-images.test.tsx`, `frontend/e2e/question-images.spec.ts`,
`frontend/src/features/exercises/EditQuestion.tsx`,
`RegenerateQuestion.tsx`, `ExerciseSolution.tsx`,
`frontend/src/features/Study.tsx`, `Questions.tsx`, `Drafts.tsx`,
`frontend/src/types.ts`, `frontend/src/locales.ts`,
`backend/tests/browser_server.py`, README.

- [ ] Vitest: два slot блока, upload preview, replace/cancel, alt,
  совместный Save; нет автоматических генераций; платная кнопка явно подписана;
  disabled config, pending existing Job, timeout с сообщением, parent review.
- [ ] RegenerateQuestion сравнивает старый/новый текст с текущими картинками,
  предлагает keep/remove; регенерация текста не регенерирует картинки.
  Concurrent image Save увеличивает version и защищает от старого текстового apply.
- [ ] apply-regeneration candidate+image_updates атомарен: keep/remove/replace,
  один version increment, hash включает изображение; другой повтор payload=409,
  одинаковый возвращает applied_result, failure не применяет половину изменений.
- [ ] Browser desktop/mobile: upload→save→quiz/flashcard→reveal→history;
  answer image не грузится до раскрытия (проверка сетевых запросов); замена
  картинки не меняет старую историю; отказы/удаление/PL/EN/RU/keyboard/long alt.
  AI provider подменён на границе; реальная обработка файлов и SQLite работают.
- [ ] Прогнать точечные тесты, затем `sh scripts/check.sh`; визуально проверить
  скриншоты, console/overflow. Проверить Gitignore/Dockerignore/secret audit.
- [ ] Финальное ревью, backup, миграция/откат на отдельной копии volume,
  сравнение старых данных и изображений, затем выпуск после разрешения пользователя.
  .env/Traefik/семейный volume сохраняются; image generation по умолчанию выключена.

## Порядок

Сначала текстовый план с регенерацией. Затем image Task 1 → Task 2:
полностью работающая ручная загрузка с UI/QA, отдельный выпуск возможен.
Task 3 → Task 4 добавляют выключенную по умолчанию AI-опцию и её UI/QA.
Никакого платного теста и изменения семейного сервера при подготовке плана не выполнялось.

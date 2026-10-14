# Пять типов языковых заданий — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Recommended execution: native, in this session; implementation has not started.

**Goal:** Добавить письменный ответ, пропуски, окончания, пары и сборку
предложения с проверкой на сервере, сохранив старые вопросы и историю.

**Architecture:** Разделить режим занятия и тип вопроса. К существующей Card
добавить типизированный exercise; снимок занятия фиксирует перемешанные элементы
и закрытое решение. Модель создаёт только черновики, сервер проверяет ответы
детерминированно, React выводит компонент соответствующего типа.

**Tech Stack:** Существующие FastAPI/Pydantic/SQLAlchemy/Alembic/SQLite,
OpenAI Structured Outputs, React/TypeScript/shadcn, pytest/Vitest/Playwright, Docker.

**Spec:** `docs/superpowers/specs/2026-10-14-language-exercises.md` — проект
решений для проверки пользователем вместе с этим планом.

**Результат критического ревью:** замечания R01–R12 описаны
в `docs/superpowers/reports/2026-10-14-language-exercises-plan-review.md`;
актуальные решения закреплены ниже и в спецификации.
Уточнения пользователя после ревью: подготовка строго до занятия, явная
готовность тема×способ, отсутствие перевода учебного содержимого и регенерация
одного вопроса. Они включены ниже вместе с исправлениями R02–R04/R08–R12.
Изображения вынесены в
отдельный последующий план `2026-10-14-question-images.md`.
Второе ревью: `docs/superpowers/reports/2026-10-14-language-images-integration-review.md`.
Уточнения I01–I06/I08–I10 закреплены в контрактах и тестах обоих планов.
I07 закрыт: пользователь выбрал только иллюстрации. Новые vision-входы и
самостоятельные задания по прикреплённой картинке не входят в этот этап.

## Global Constraints

Границы этого этапа сохраняются. Последующее расширение описано в
`2026-10-14-free-responses.md`: written остаётся коротким ответом, новые
free_response/picture_description используют отдельную async Evaluation.
Ни одна задача этого плана не добавляет AI grading/аудио прежним типам.
При интеграции нового этапа mixed default не включает платные типы,
_grading v1 и v2 читаются отдельно, mode и Start-without-AI сохраняются.

- Пять новых типов: письменный ответ, пропуски, окончания, пары, сборка предложения.
- Озвучка, диктант, запись голоса и новые платные API не входят в эту работу.
- Проверка ответа выполняется на сервере без вызова модели.
- `mode` остаётся `quiz | flashcard`; `question_type` — отдельное поле.
- В теме селектор способа проверки и одна кнопка «Начать», вместо двух кнопок.
- Цель генерации content/language выбирает пользователь; запуск использует saved вопросы.
- `count` — общее число вопросов, от 1 до 30; новые зависимости не обязательны.
- Язык материала/вопросов/ответов сохраняется; переводится только интерфейс.
- Подготовка модели явная и до занятия; start никогда не создаёт AI-задачи.
- Интерфейс PL/EN/RU; темы и материалы не смешиваются; история принадлежит пользователю.
- Исходные файлы, `.env`, Traefik и постоянный Docker-том сохраняются.
- Успех задания — полностью правильный ответ; поля/пары получают отдельную обратную связь.

## Review Focus

1. Старые активные и завершённые снимки не имеют question_type/exercise — читаются
   без миграции их JSON и сохраняют результат; тесты задач 1, 3 и 6.
2. В литовском/польском диакритика значима, а Unicode может быть составным —
   NFC эквивалентен, похожая буква без диакритики неверна; тесты задачи 1.
3. В предложении встречаются одинаковые слова, а допустимый порядок не один —
   такие ответы принимаются без обхода подсчёта элементов; тесты задач 1, 3 и 6.
4. Перезагрузка, повтор HTTP после таймаута и две вкладки не меняют пары,
   порядок, число попыток или историю; тесты задач 3 и 6.
5. Ни решения, ни скрытые ID соответствий не попадают в публичный JSON,
   ошибки валидации и клиентское состояние до ответа; тесты задач 1, 3 и 6.

## Карта файлов и ответственность

- `backend/app/exercises.py` (новый): типизированные упражнения, проверка,
  нормализация, закрытый/публичный снимки. Не обращается к БД или модели.
- `backend/app/schemas.py`: типы generation/edit и проверки квот.
- `backend/app/models.py`, `backend/alembic/versions/0006_question_types.py`:
  две добавочные колонки Card, без переписывания истории.
- `backend/app/ai.py`, `backend/app/jobs.py`, `backend/app/quiz.py`:
  создание, дедупликация, сохранение, редактор и совместимость prepare_quiz.
- `backend/app/study.py`: фильтр типов, снимки, проверка/идемпотентность/результаты.
- `backend/app/library.py`: готовность по способам в topic_data, без решений.
- `backend/app/regeneration.py` (новый): создание, применение и отказ от
  регенерации одного вопроса; транзакции и защита версий.
- `backend/app/deletion.py`: очистка кандидатов и защита от поздних workers.
- `frontend/src/lib/exercises.ts` (новый), `frontend/src/types.ts`:
  публичные/редакторские типы, формы ответа и подписи.
- `frontend/src/features/exercises/` (новый): компоненты учебного ввода,
  решения и редактирования; не смешивать их с генерацией/навигацией.
- `frontend/src/features/Generation.tsx`, `Drafts.tsx`, `Questions.tsx`,
  `StartStudy.tsx`, `StudySelection.tsx`, `Study.tsx`, `frontend/src/components/shared.tsx`:
  подключение новых компонентов в существующие экраны.
- `frontend/src/locales.ts`, `backend/tests/browser_server.py`, README:
  переводы, изолированные тестовые данные, пользовательская документация.

## Task 1: Контракт упражнений, проверка и миграция

**Files:** Create `backend/app/exercises.py`,
`backend/alembic/versions/0006_question_types.py`,
`backend/tests/test_exercise_schemas.py`, `backend/tests/test_exercise_grading.py`,
`backend/tests/test_exercise_migration.py`; modify `backend/app/models.py`,
`backend/app/schemas.py`.

**Interfaces:**
- `QuestionType = Literal["choice", "written", "gap", "ending", "matching", "ordering"]`.
- `validate_exercise(question_type: QuestionType, value: dict | None) -> dict | None`:
  нормализованный JSON одной из пяти Strict/Pydantic-схем; choice требует null.
- `normalize_text(value: str, case_sensitive: bool = False) -> str`.
- `build_snapshot(card: dict) -> dict`: закрытый снимок с `snapshot_version=2`,
  случайными ID/перемешиванием только для matching/ordering.
- `public_exercise(snapshot: dict, revealed: bool) -> dict`:
  разрешённые поля задания; полное решение только при revealed=true.
- `grade_answer(snapshot: dict, submission: dict) -> GradeResult`:
  `correct: bool`, `parts: list[{id: str, correct: bool}]`; исключение
  `InvalidSubmission` для неполного/чужого/неверно сформированного ответа.
- `canonical_submission(snapshot: dict, submission: dict) -> dict`:
  строгая проверка формы, сортировка ключей gap_answers/пар, сохранение
  исходного текста и порядка токенов. Не смешивает неверный ответ с неверным запросом.
- `solution_text(question_type: QuestionType, exercise: dict) -> str`:
  written — допустимые ответы; gap/ending — заполненные сегменты первой
  допустимой комбинацией; matching — соответствия; ordering — допустимые
  порядки. Для новых типов это серверный источник Card.answer, не отдельная
  редактируемая истина. Renderer может показывать структуру удобнее plain text.
- GradeResult дополнительно `message_code: str | None`; для несовместимого
  сочетания gap — `incompatible_combination`. accepted_combinations: 1–20
  полных векторов по порядку gaps, все элементы допустимы для своего поля.
  Проекция комбинаций каждого поля точно равна accepted_answers после
  normalize_text; дубли полных сочетаний после нормализации запрещены.

- [ ] Написать тесты: границы всех пяти схем, unknown fields, несовпадение
  типа, повтор gap_id, два слота ending, пустые варианты, неоднозначные пары,
  неверное мультимножество ordering, все границы из спецификации.
- [ ] Написать тесты проверки: `normalize_text("  ŻÓŁĆ  ")=="żółć"`,
  NFC/NFD равны, `żółć` не равен `zolc`, явный case_sensitive; written с
  двумя допустимыми ответами на одном языке; неверный gap/пара делает correct=false;
  отсутствие/лишний ID — InvalidSubmission; повторяющиеся токены и второй
  допустимый порядок принимаются; чужие/повторные ID отклоняются.
- [ ] Зависимые gaps: I+am/We+are верны, I+are неверен; parts относительно
  ближайшей комбинации, tie по сохранённому порядку и сообщение о несовместимости.
  Повторные/неполные сочетания отклоняются. Метаданные комбинаций не публичны.
  Решение после правки exercise соответствует новым accepted значениям.
- [ ] «Мёртвое» accepted значение, не входящее в комбинации, отклоняется;
  редактор формирует варианты из комбинаций, не независимый список.
- [ ] Написать тесты публичного снимка: accepted_answers/orders, mapping,
  answer скрыты рекурсивно; текст токенов доступен; ID не совпадают с исходными
  позициями/парами; повторное чтение того же снимка сохраняет перестановку.
- [ ] Новый snapshot/repeat создаёт новые ID/раскладку без обращения к Card
  и модели; reload внутри занятия стабилен. Проверить свойства перемешивания
  детерминированно, включая одинаковые токены и уже правильный банк слов.
- [ ] Подготовить SQLite на ревизии 0005 с Card, активной флеш-картой,
  завершённым тестом, Attempt и файлом. Мигрировать до 0006: прежние столбцы,
  JSON и файл неизменны, новые значения choice/null, integrity/FK checks успешны.
- [ ] Запустить `.venv/bin/pytest -q backend/tests/test_exercise_schemas.py backend/tests/test_exercise_grading.py backend/tests/test_exercise_migration.py`; увидеть падение до реализации.
- [ ] Реализовать интерфейсы и добавочную миграцию без массовой модификации снимков.
- [ ] Повторить тесты; все проходят. Проверить совместимость ORM defaults с
  существующими тестовыми Card. Зафиксировать этап локально после разрешения реализации.

## Task 2: Генерация, хранение и редактирование

**Files:** Modify `backend/app/schemas.py`, `backend/app/ai.py`,
`backend/app/jobs.py`, `backend/app/quiz.py`; create
`backend/tests/test_exercise_generation.py`, `backend/tests/test_exercise_editing.py`;
extend `backend/tests/test_ai.py`, `backend/tests/test_languages.py`,
`backend/tests/test_quiz_preparation.py`, `backend/tests/test_retry.py`.

**Interfaces:**
- GeneratedCard: `question_type: QuestionType = "choice"`, `exercise` — узкая
  типизированная схема или null, прежние поля сохранены. Новые типы имеют
  mode=quiz, options=[], correct_indices=[], correct_index=null.
  Для новых типов после валидации answer вычисляется через solution_text;
  совпадение модели с произвольным форматированием answer не считается критерием.
  CardEdit.answer для новых типов можно не передавать; если передан и противоречит
  вычисленному решению — 422. Старый PATCH для choice остаётся прежним.
- GenerateBody: `question_types: list[QuestionType] = ["choice"]`,
  `practice_goal: Literal["content", "language"] = "content"`;
  уникальность и count>=topics×types; content разрешает только
  choice/written/gap/matching, language — все шесть.
- Generated: `unsupported_types: list[UnsupportedType]`;
  `UnsupportedType` — Strict-модель `{question_type: QuestionType, reason: str}`,
  причина непустая. Проверять выбранные типы, уникальность и отсутствие
  одновременной генерации вопросов объявленного неподходящим типа.
- `generation_quotas(topic_ids: list[int], question_types: list[QuestionType], count: int) -> dict[int, dict[str, int]]`
  в jobs.py: минимум один на сочетание, остаток по стабильному порядку topic/type.
- `AI.generate(..., question_types=None, type_counts=None, practice_goal="content")`
  сохраняет прежние аргументы; старый Job без новых полей получает content/choice
  и старую квоту. Оценка пригодности — в том же вызове, без отдельного анализа.
- `question_key(topic_id, question, answer, language, question_type="choice", exercise=None)`:
  канонический JSON с сортировкой ключей; не стирает диакритику/пунктуацию.
- CardEdit: необязательный `exercise`, неизменный question_type, version guard.
- GenerateBody и prepare-options получают `idempotency_key: str | None`
  (до 80 символов для legacy-совместимости); новая UI всегда передаёт ключ.
  Под write-lock key+fingerprint привязываются к Job; тот же key возвращает
  исходную задачу, другое тело=409. Active scope включает версии/хеши выбранных
  источников, темы, типы, цель, mode и count; сохраняет один Job до генерации.

- [ ] Тесты /generate: выбор 1/нескольких типов, общее count, квоты, неверная
  тема/тип/источник/язык, невозможное грамматическое упражнение с причиной,
  старый payload, повтор Job без дублей и одинаковое слово в разных типах.
- [ ] Тесты цели: content+ending/ordering=422 до AI; language+ending проходит;
  название «История» не запрещает language, польский язык не включает его сам.
  unsupported_types в том же ответе: частично/полностью неподходящие материалы,
  причина в job.result.warnings и пустой результат без подмены типа; конфликт
  unsupported+generated отклоняется. Старые Job/result без поля продолжаются.
- [ ] Параллельная подготовка/response lost/другая вкладка — один Job и вызов;
  одинаковый key после completion возвращает исходный Job, другое тело=409.
  Источники/count изменены — не переиспользовать несовместимую активную задачу.
- [ ] Тесты редактирования: accepted_answers/segments/pairs/orders меняются
  и валидируются; нельзя изменить тип, старый PATCH работает; конфликт version=409.
- [ ] Тесты языка: новый generate с target_language непустым=422 до AI;
  LT/PL/EN содержимое не меняется при смене UI; смешанные материалы не дают
  разноязычный ответ одного вопроса; старые translated Card/history читаются;
  старая незавершённая задача/retry с переводом завершается понятной ошибкой,
  готовые результаты сохраняются.
- [ ] Тесты адаптера: JSON-schema для нового результата действительно совместима
  с существующим Structured Outputs, не использует свободный dict/Any в
  модельном контракте; исходный язык и retry budget=3 сохранены.
  Использовать существующий подменённый транспорт, не оплачиваемые запросы.
- [ ] Проверить фактическую SDK-сериализацию схемы: root object, required,
  additionalProperties=false, nullable, вложенный anyOf без unsupported
  конструкций; это отдельная офлайн-проверка, а не mock success. Модельные
  комбинации — списки структурированных элементов, без dynamic dict.
  Проверить incomplete на больших ответах: ошибка не сохраняет половину
  результата и не запускает дополнительные платные запросы/увеличение budget.
- [ ] Запустить `.venv/bin/pytest -q backend/tests/test_exercise_generation.py backend/tests/test_exercise_editing.py backend/tests/test_ai.py backend/tests/test_languages.py backend/tests/test_quiz_preparation.py backend/tests/test_retry.py`; подтвердить новые падения.
- [ ] Добавить схемы, квоты, prompt, сериализацию Card, дедупликацию и редактор.
  Существующий quiz_ready/prepare_quiz обрабатывает только choice; остальные
  типы нельзя преобразовать в choice и затереть упражнение.
- [ ] Подготовка старых choice явно вызывается отдельным endpoint
  `POST /api/study/prepare-options {topic_ids}` и возвращает Job.
  Worker сохраняет варианты в Job.result, не меняет Card. Endpoint
  `POST /api/jobs/{id}/save-preparation {card_ids}` принимает выбранные
  кандидаты после проверки версии/статуса/источников. Тесты двойного запуска,
  пустого набора, принятия, конфликта, удаления и отказа без изменения Card.
- [ ] Повторить тесты; проверить старые фоновые задачи и подготовку старой
  флеш-карты в тест. Локальный коммит этапа.

## Task 3: Занятия, ответы и неизменная история

**Files:** Modify `backend/app/study.py`, `backend/app/quiz.py`;
modify `backend/app/library.py`;
create `backend/tests/test_exercise_study.py`,
`backend/tests/test_exercise_history.py`; extend `backend/tests/test_study.py`,
`backend/tests/test_history_detail.py`, `backend/tests/test_history_deletion.py`.

**Interfaces:**
- StartBody: `question_types: list[QuestionType] | None = None` (все),
  уникальные непустые значения при наличии. Для quiz фильтруются только
  действительно готовые saved вопросы; choice требует quiz_ready.
  Каждый явно выбранный тип должен быть готов в каждой выбранной теме;
  пробелы=422 с missing_pairs; лимит 300 сохраняется. AI не вызывается.
  Если types=None, сервер выбирает общий набор готовых типов во всех выбранных
  темах; UI всегда передаёт явный набор для quiz.
- Topic.practice_availability: flashcard и шесть типов, у каждого ready_count,
  draft_count, needs_options_count, preparation_job_id/status, has_ready_materials.
  Видны только разрешённые текущему пользователю Job. Наличие подготовки
  не отменяет уже готовые вопросы. API не возвращает решения ради счётчиков.
  last_outcome содержит method/source_fingerprint/reason/stale; новая версия
  выбранных материалов не использует старую оценку неподходящего типа.
- AnswerBody: старые choice/choices/remembered и новые `text: str | None`,
  `gap_answers: dict[str, str] | None`, `pairs: list[{left_id, right_id}] | None`,
  `order: list[str] | None`. Strict строки/ID: text до 1000 символов,
  gap_answers до 6 значений по 200 символов, pairs до 8, order до 20,
  ID до 80 символов; unknown fields запрещены;
  ровно одна форма ответа, appropriate question_type проверяется по снимку.
- feedback: прежние поля плюс `parts/message_code` из сохранённого результата.
  Attempt.value хранит канонический пользовательский ответ и служебный
  `_grading: {version:1, correct, parts, message_code}`. Идемпотентность сравнивает
  только пользовательскую часть; feedback/Review не пересчитывают grader.
  Старые Attempt без _grading читают сохранённый correct. Repeat создаёт новый
  snapshot из старого содержания с новым перемешиванием, не текущей Card.

- [ ] API-тест полного пути каждого типа: saved→start→resume→answer→history→repeat;
  верно/неверно/неполно, пустой фильтр, выбранная тема, черновики исключены.
  Проверить счётчики: новые типы, старые Card, исключение draft/deleted,
  нулевые типы и две темы; совпадают с набором, который реально запускается.
- [ ] Тест готовности: A=written, B=choice, выбран written → missing B, без
  Job/списания/молчаливого исключения. Legacy choice без options не запускает
  prepare_quiz из start; после явной подготовки/принятия запускается.
  Готовые+A queued новые вопросы показываются одновременно; status/draft
  не считаются готовыми. Повтор start перепроверяет удалённые Card атомарно.
- [ ] Mixed по умолчанию использует общий набор типов выбранных тем; пустое
  пересечение показывает подготовку, не исключает тему. Явное добавление
  отсутствующего типа показывает missing_pairs. Unsupported outcome виден
  для исходного fingerprint; новые материалы помечают его устаревшим.
- [ ] Проверить рекурсивное отсутствие решения в start/resume/422 до ответа;
  после ответа решение доступно только владельцу. Авторизация/CSRF/Origin работают.
- [ ] Идемпотентность: одинаковый key+payload — тот же результат/одна попытка;
  переставленные пары/ключи gap_answers — тот же ответ; изменённый текст/order —
  409; две вкладки и устаревшая position не записывают вторую попытку.
- [ ] История: редактирование/удаление Card/материала не меняет snapshot;
  повтор только ошибок без AI; bulk-delete удаляет новые Attempt.value и снимки;
  старые снимки choice и flashcard без новых полей продолжаются и повторяются.
- [ ] После изменения grader старые correct/parts/message_code неизменны;
  feedback при повторе key читает сохранённую оценку. Metadata не мешает
  сравнению payload. Сохранённый ответ доступен после потерянного HTTP response.
  History metadata добавляет фактические типы/количества снимков без решений.
  Для flashcard подпись «Флеш-карты», для quiz — тип или mixed по реальным снимкам.
- [ ] Запустить `.venv/bin/pytest -q backend/tests/test_exercise_study.py backend/tests/test_exercise_history.py backend/tests/test_study.py backend/tests/test_history_detail.py backend/tests/test_history_deletion.py`; увидеть новые падения.
- [ ] Подключить функции Task 1 к API, собирать public_card по разрешённым
  полям; не раскрывать вложенные exercise посредством `**snapshot`.
- [ ] Повторить тесты; локальный коммит этапа.

## Task 4: Создание и управление вопросами в интерфейсе

**Files:** Create `frontend/src/lib/exercises.ts`,
`frontend/src/features/exercises/ExerciseEditor.tsx`,
`frontend/src/features/exercises/ExerciseSolution.tsx`,
`frontend/tests/exercise-editing.test.tsx`;
modify `frontend/src/types.ts`, `frontend/src/features/Generation.tsx`,
`Drafts.tsx`, `Questions.tsx`, `frontend/src/components/shared.tsx`,
`frontend/src/locales.ts`, `frontend/src/App.tsx`.

**Interfaces:**
- Разделить `PublicExercise`, `FullExercise`, `ExerciseSubmission`,
  `GradePart`; публичные типы не содержат accepted_answers/orders/mapping.
- `ExerciseEditor({questionType, value, onChange, disabled})`: редактирует
  полную схему текущего типа. `ExerciseSolution({card})`: полное решение
  раскрытого/редакторского вопроса; используется также в истории/флеш-карте.

- [ ] Vitest: генерация selected types+общего count; count<числа типов блокирует
  запуск; правки каждого типа отправляются с version; ошибки сохраняют ввод;
  старая карточка choice редактируется; типы отображаются в черновиках/списках.
- [ ] Vitest: «Что тренируем?» по умолчанию content; language открывает ending/
  ordering; смена на content снимает их с пояснением и без запроса AI; выбранная
  цель отправляется с запросом. Предупреждения unsupported_types показываются
  и при частичном результате, и когда нет вопросов. PL/EN/RU переводы причин
  интерфейса; модельные причины остаются на языке результата.
- [ ] Удалить переключатель перевода учебных вопросов. Добавить preset
  маршрута `#library/topic/{id}/create/{method}`: flashcard задаёт
  mode=flashcard/choice, другие методы — mode=quiz/[method]. Старый /create
  остаётся общей формой. Предзаполненная тема/тип не теряются при загрузке
  материалов и возвращении. Отдельный экран принятия вариантов не стартует тест.
- [ ] `npm test --prefix frontend -- --run tests/exercise-editing.test.tsx` — новые тесты падают.
- [ ] Реализовать выбор типов отдельным полем формы; переводы PL/EN/RU,
  типовые редакторы и решение. Вынести EditCard из shared.tsx в новый
  `frontend/src/features/exercises/EditQuestion.tsx`, оставив совместимый
  реэкспорт для существующих импортов; не расширять shared.tsx пятью формами.
- [ ] В редакторе новых типов answer вычисляется/не редактируется независимо;
  ручные правки accepted_answers/комбинаций/порядков возможны. Тест: нельзя
  получить разные ответы в проверке, флеш-карте и explain.
- [ ] Повторить тесты и `npm run build --prefix frontend`; локальный коммит этапа.

## Task 5: Ввод, фильтры и обратная связь в занятии

**Files:** Create `frontend/src/features/exercises/ExerciseInput.tsx`,
`TextExercise.tsx`, `GapExercise.tsx`, `MatchingExercise.tsx`,
`OrderingExercise.tsx`, `PracticeSelector.tsx`,
`frontend/tests/exercise-study.test.tsx`;
modify `frontend/src/features/Study.tsx`, `StartStudy.tsx`,
`StudySelection.tsx`, `History.tsx`, `frontend/src/types.ts`, `frontend/src/locales.ts`.

**Interfaces:**
- `ExerciseInput({card, value, onChange, disabled, feedback})` возвращает
  ExerciseSubmission через onChange; renderer по question_type.
- `PracticeMethod = "flashcard" | "choice" | "written" | "gap" | "ending" | "matching" | "ordering" | "mixed"`.
- `PracticeSelector({counts, method, onMethodChange, selectedTypes, onTypesChange, disabled})`:
  counts/readiness из Topic.practice_availability, для нескольких тем
  проверяется каждая тема×тип. Нулевой тип выбирается, но вместо старта
  открывается подготовка. Фильтр только при mixed; initial selectedTypes —
  пересечение готовых типов выбранных тем. Default flashcard.
- `practice_request(method: PracticeMethod, selectedTypes: QuestionType[]) -> {mode: Mode, question_types?: QuestionType[]}`
  в frontend/src/lib/exercises.ts: flashcard→mode=flashcard без фильтра;
  один тип→mode=quiz с `[method]`; mixed→mode=quiz с выбранными доступными типами.
  StartStudy/StudySelection используют одну основную кнопку: «Начать» при
  готовности, «Подготовить задания» при пробелах, «Проверить задания» при
  черновиках. При preparing показывают прогресс/ссылку на существующий Job.
  Подготовка нескольких тем перечисляет только пробелы и выполняется по
  одной теме за раз. Готовые задания не перегенерируются автоматически.
- Study.answerRequest сохраняет полный payload и key при retry после сети;
  не меняет ввод после отправки до определённого результата.

- [ ] Vitest: input written; gap/ending labels и все поля; выбор/отмена пары;
  сборка/возврат/очистка слов; одинаковые слова выбираются по разным ID;
  кнопка проверки доступна только для полного ответа; Enter/клавиатура работают.
- [ ] Vitest: неверные части красные и отмечены словами/значком; решение после
  ответа, до него отсутствует; сеть сохраняет key/payload; filter сохраняет
  topic_ids; флеш-карты/история показывают полное решение каждого типа.
- [ ] Сообщение incompatible_combination, отдельные результаты по заданиям
  и частям (0/1 и 7/8); submitted восстановлен, unsubmitted не объявляется
  сохранённым. History показывает тип практики; нет пересчёта старой оценки.
- [ ] Vitest селектора: нет двух старых кнопок запуска, default flashcard,
  все восемь подписей, счётчики, нулевой тип доступен для подготовки; выбор способа
  даёт точный mode/question_types, mixed позволяет исключить тип, пустой mixed
  не запускается; изменение тем обновляет готовность; выбор не запускает
  генерацию, «Подготовить» открывает явную форму. Повтор клика preparing не
  создаёт второй Job. Старый URL занятия продолжает открываться.
- [ ] `npm test --prefix frontend -- --run tests/exercise-study.test.tsx` — новые тесты падают.
- [ ] Реализовать компоненты без новых drag-and-drop зависимостей; общая
  инфраструктура навигации, Explain, busy/error, next остаётся в Study.
  Убрать инструкцию «Выбери ответ» для типов, где ответ нужно вводить/собирать.
- [ ] Повторить тесты и сборку; локальный коммит этапа.

## Task 6: Регенерация одного вопроса с просмотром кандидата

**Files:** Create `backend/app/regeneration.py`,
`backend/tests/test_regeneration.py`,
`frontend/src/features/exercises/RegenerateQuestion.tsx`,
`frontend/tests/regeneration.test.tsx`, `frontend/e2e/regeneration.spec.ts`;
modify `backend/app/ai.py`, `jobs.py`, `main.py`, `deletion.py`,
`frontend/src/features/Questions.tsx`, `Drafts.tsx`,
`frontend/src/types.ts`, `frontend/src/locales.ts`.

**Interfaces:**
- `POST /api/cards/{id}/regenerate {version, idempotency_key}` → Job.kind=regenerate,
  payload={card_id, base_version, immutable source/question/type/language snapshot}.
- `AI.regenerate(card, sources)` → typed один GeneratedCard или
  typed причина недостаточности; не список новых вопросов темы.
- `POST /api/jobs/{id}/apply-regeneration {candidate}`: валидированный
  отредактированный кандидат, версия из сохранённого payload; атомарный update
  одной Card, status/job_id сохраняются. Job.result хранит applied_version,
  applied_fingerprint и compact applied_result. Одинаковое тело повторяется
  без изменения; другое тело после apply=409. Apply/Discard — взаимоисключающие
  транзакционные состояния, discard не откатывает уже сохранённую правку.
- `POST /api/jobs/{id}/discard-regeneration`: идемпотентно очищает кандидат/
  исходные фрагменты; не меняет Card. Отклонённый кандидат не применяется.
- RegenerateQuestion показывает progress → исходный/кандидат → редактирование/
  применение/отказ. Не вызывает генерацию картинок и не переводит текст.

- [ ] API-тесты: новый текст и варианты только одного вопроса, один тип/язык,
  не меняются остальные Card; ошибка/недостаточный источник сохраняют оригинал;
  двойной клик одного card/version возвращает существующий queued/running Job.
- [ ] Ответ потерян/клик после completed-кандидата возвращает имеющийся Job;
  «Другой вариант» отправляет новый key явно. Чужой private Job не раскрывается
  по active fingerprint, busy не содержит его кандидата/секретных данных.
- [ ] До apply оригинал неизменен; apply увеличивает version на 1; повтор apply
  возвращает уже применённый результат без второго изменения. Конкурентное
  ручное редактирование/удаление → 409/404; кандидат-дубликат другой Card запрещён.
  История/активный SessionCard.snapshot не меняются; стадия draft остаётся draft.
- [ ] Тот же apply после более поздней правки Card возвращает сохранённый
  applied_result, не новую Card; изменённый кандидат=409; parallel apply/discard
  имеет один победивший переход. В image-этапе fingerprint включает image_updates.
- [ ] Удаление Card/Topic/Subject очищает Job и кандидат; поздний worker не
  восстанавливает данные. После discard старый кандидат не применим.
- [ ] Авторизация/Origin/CSRF сохранены; GET/apply/discard кандидата разрешены
  только владельцу задачи, доступ другого пользователя не раскрывает
  её содержимое. Общий сохранённый вопрос остаётся общей библиотекой.
- [ ] Vitest/Playwright: обе кнопки рядом (изменить/регенерировать), preview,
  поправка кандидата, отказ, ошибка, закрытие/возврат к задаче, конфликт версий.
  Все подписи PL/EN/RU, desktop/mobile; до применения нет автоматической замены.
- [ ] Сначала воспроизвести падения, реализовать минимально, затем
  `.venv/bin/pytest -q backend/tests/test_regeneration.py`,
  `npm test --prefix frontend -- --run tests/regeneration.test.tsx`,
  `npm run test:e2e --prefix frontend -- regeneration.spec.ts` → PASS.

## Task 7: Браузерная приёмка, проверки и подготовка выпуска

**Files:** Create `frontend/e2e/exercises.spec.ts`;
modify `backend/tests/browser_server.py`, `README.md`,
`scripts/deploy.py`, `scripts/backup.sh`, `backend/tests/test_deploy_scripts.py`;
create `backend/tests/test_migration_rollback.py` для isolated Docker проверки.

- [ ] Добавить изолированные готовые упражнения пяти типов к браузерным
  fixtures; внешняя модель подменена только на границе транспорта.
- [ ] Desktop/mobile: создать/проверить/изменить/сохранить упражнения,
  запустить смешанный тест и тест с фильтром; ошибиться и проверить feedback;
  перезагрузить пары/порядок; закончить, открыть историю, повторить ошибки.
- [ ] Сценарий применимости: создать тему истории, content не предлагает
  окончания; явно выбрать language в этой же теме и получить/сохранить
  подходящее упражнение из языкового материала. Неподходящий источник возвращает
  причину без выдуманных заданий. На теме запуск каждого способа через selector;
  начинать можно только готовые saved задания, отсутствующие можно выбрать
  для явной подготовки. Выбор не делает внешних запросов; ready используется повторно.
- [ ] Дополнительно: литовские диакритики, два допустимых ответа written, одинаковые
  слова ordering, PL/EN/RU, keyboard-only, поля под экранной клавиатурой,
  длинные подписи, возврат в тему, старое занятие, отсутствие overflow/console errors.
- [ ] `npm run test:e2e --prefix frontend -- exercises.spec.ts` — подтвердить
  воспроизводимость новых сценариев; сохранённые скриншоты проверить визуально.
- [ ] Выполнить `sh scripts/check.sh`. Все pytest/Vitest/Playwright,
  Ruff/format/ESLint/build/Bandit/Semgrep проходят; не заявлять заранее число тестов.
- [ ] Проверить `git diff --check`, состав tracked/staged файлов и секреты;
  новый пользовательский контент/SQLite/.env/артефакты браузера не входят в Git.
- [ ] Независимое финальное ревью diff — если разрешено выбранным способом
  выполнения; исправления повторно проверяются соответствующими тестами.
- [ ] Для будущего выпуска после разрешения пользователя: полный backup,
  миграция на приватной копии, сравнение старых таблиц и JSON плюс хеши файлов;
  ожидаемые новые колонки/ревизия отдельно. Затем commit/push main, серверный
  `./update.sh`, health/TLS, браузерная проверка без изменения семейных данных.
- [ ] Учесть ограничение rollback: старый образ не откатывает схему; при
  необходимости восстанавливаются старый образ и проверенный полный backup.
  `.env`/override/volume остаются приватными. Подтвердить историю и загруженные файлы.
- [ ] До выпуска с 0006 уточнить `scripts/deploy.py` и `scripts/backup.sh`:
  сборка/проверка нового образа до downtime; при смене ревизии stop записи,
  финальный cold backup с режимом keep-stopped (не перезапускать app trap-ом),
  миграция/healthcheck до открытия приложения. Если сбой — сохранить состояние
  сбоя и восстановить проверенный том+старый image; fallback одного image не
  считать успешным откатом. .env/Traefik не менять. Закрепить host+SQLite+Docker
  интеграционным тестом на отдельном QA-volume, не семейном томе.

## Проверка плана и порядок исполнения

Порядок: 1 → 2 → 3 → 4 → 5 → 6 → 7. Все пять типов используют один контракт;
рекомендуется реализация здесь по шагам, без параллельных изменений общего
study.py/jobs.py. Сначала тесты каждого этапа падают, затем проходят.

Покрытие требований: типы/границы/диакритика — 1; генерация/редактор/квоты/язык/
цель и применимость — 2 и 4; приватность/идемпотентность/старая история — 1 и 3;
селектор запуска/навигация/touch/feedback —
5 и 7; регенерация — 6; миграция/файлы/проверки/выпуск — 1 и 7.
Изображения — отдельный следующий этап, аудио во всех этапах исключено.

План подготовлен для просмотра. Реализация, коммиты и изменения на сервере
не выполнялись в рамках подготовки этого документа.

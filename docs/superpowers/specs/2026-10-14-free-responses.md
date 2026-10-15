# Свободные ответы, описание картинки и голос — дополнение к спецификациям

## Подтверждённый объём и порядок

Пользователь подтвердил 14 октября 2026: добавить последовательно свободный
письменный ответ со счётчиком слов, описание картинки и голосовой ввод.
Документ дополняет `2026-10-14-language-exercises.md` и
`2026-10-14-question-images.md`; эти этапы не реализуются внутри прежних пяти типов.
Сейчас меняются только документы, без оплачиваемых запросов и выпуска.

Три самостоятельных результата:
1. `free_response`: письменное объяснение темы или языковое сочинение.
2. `picture_description`: описание явно выбранной картинки текстом.
3. Голос как дополнительный способ ввода обоих типов, не новый тип вопроса.

`written` остаётся коротким ответом с детерминированной проверкой. Старые
choice/written/gap/ending/matching/ordering не отправляются модели для оценки.
Обычные картинки остаются иллюстрациями. Только picture_description использует
картинку как обязательный материал. Озвучки, live transcription, оценки
произношения и разговорного ассистента в этих трёх этапах нет.

Совместный порядок миграций: 0006 типы → 0007 картинки → 0008 журнал image
requests → 0009 свободные ответы → 0010 визуальный источник → 0011 аудио.
0008 можно установить при отключённой платной генерации картинок; включение
Images API, выбор image model и реальные image requests не являются зависимостью.
Upload-only выпуск прежнего image-плана остаётся самостоятельным до этих этапов.
На реализации проверить фактический Alembic head, не создавать вторую ветку head.

## Подготовка и выбор способа

Для новых типов используется прежний сценарий Prepare → Drafts → Save → Start.
Вопрос и критерии подготавливаются заранее, старт не вызывает модель.
GenerateBody принимает новый тип и `free_response_settings`; один запрос
готовит только семейство свободных заданий, смешивать его с прежними шестью
типами в одном GenerateBody нельзя (422). Count остаётся 1–30 на одну тему.
Идемпотентность, дедупликация, варианты регенерации и version guards сохраняются.

В теме добавляются «Свободный ответ» и затем «Описание картинки». Ready/draft/
preparation/last_outcome считаются отдельно для каждого. Готовность задания
не равна доступности платной проверки: при disabled/missing key виден отдельный
runtime_unavailable, старт новых типов возвращает 409 без внешнего запроса.
Проверка конфигурации не делает пробный вызов API. На уже начатое занятие
отключение влияет как временная недоступность проверки, не как неверный ответ.

Новые типы только quiz; во flashcard не включаются и не преобразуются в choice.
Смешанный режим по умолчанию берёт пересечение готовых старых шести типов.
Новые платно проверяемые типы включаются только явно с пометкой о стоимости;
для всех выбранных типов по-прежнему нужна готовность в каждой выбранной теме.
StartBody дополнительно `include_ai_evaluated: bool = false`; явный выбор новых
типов требует true. types=null не включает их. Лимит занятия остаётся 300.

## Критерии и язык

`FreeResponseExercise` — закрытый Strict/Pydantic JSON:
- goal content/language; language — фиксированный ISO/BCP-47 код задания;
- level A1/A2/B1/B2/C1/C2 только для language; для content null;
- Для language пользователь явно выбирает level; скрытого default уровня нет.
- min_words/max_words: null или целые 1–2000, min ≤ max; default оба null;
- model_answer: пример, 1–4000 символов, не строка для exact match;
- rubric: 1–8 критериев с уникальными id, label и weight, сумма weight=100;
- expected_points: 1–12 пунктов {id, text, essential, sources};
- sources: реальные ссылки на выбранные материалы; нет свободного dict/Any
  в модельной схеме. Ответ пользователя не может менять criteria/level/goal.

Content оценивает факты, объяснение и полноту, а не орфографию. Language оценивает
выполнение задания, грамматику, словарь и связность с учётом выбранного уровня.
Свободная переформулировка принимается; без обязательного совпадения с примером.
Если материалы неоднозначны/противоречивы, подготовка не создаёт вопрос с
единственным выдуманным фактом: сохраняет insufficient_reason по fingerprint.
Родитель видит и редактирует критерии, пример и ограничения до Save.

Язык содержимого сохраняется, интерфейс PL/EN/RU независим. Language и content
по текстовым материалам используют исходный язык; несовместимые языки выбранных
источников показываются в подготовке и требуют выбрать однородный набор.
При известном едином языке source language в settings фиксирован сервером;
если extraction language=null, пользователь подтверждает язык исходного текста
до подготовки, модель проверяет соответствие, не получает поручение переводить.
Голос транскрибируется без перевода; исправления и пример остаются на языке
задания. Поясняющие подписи UI локализованы. Для picture_description нет исходного
текстового языка: пользователь явно выбирает язык описания (PL/EN/RU/LT первой
версии), а не получает его из локали UI. Это не перевод загруженных документов.
CEFR служит ориентиром требований, не сертификатом/диагностикой общего уровня.

## Счётчик слов

`word_count_version=1` одинаков на сервере и клиенте, общий JSON набор примеров. Категории L/N/M закреплены за Unicode 15.1.0 в общем генерируемом профиле `backend/app/word-count-profile.json`; новые символы Unicode 16+ остаются границами, независимо от версии Python/браузера. NFC применяется только для подсчёта, исходный текст сохраняется.
Нормализация NFC, Unicode буквы/числа образуют слово; combining marks принадлежат
предыдущей букве. Внутренний апостроф ('/’) и дефис (-/‐/‑) соединяют слово,
если окружены буквами/числами. Остальная пунктуация, пробелы и zero-width
разделители разделяют слова; emoji отдельно словом не считаются.
Примеры: don't=1, biało-czerwony=1, 123=1, «Ąžuolas, stalas!»=2,
«слово—слово»=2; NFC/NFD дают одинаковое количество. Правило предназначено для
текстов с разделением слов, в том числе PL/EN/RU/LT, не обещает сегментацию CJK.

Письменный счётчик обновляется локально, без запросов модели. Сервер считает
повторно. Пустой/только пунктуационный текст отклоняется 422 до Job. Верхний
технический предел: 10000 символов и 2000 слов. Ответ вне учебного min/max
можно отправить после видимого предупреждения: лимит отмечается в результате
отдельно и не обнуляет оценку содержания. AI не подсчитывает слова.

## Проверка и сохранение результата

Проверка только по явной кнопке «Проверить ответ (AI)». Используется существующая
текстовая модель с Structured Outputs, SDK retries=0 и существующим максимумом
трёх попыток только для временных ошибок. Нет исправляющего запроса после
невалидного JSON/refusal/incomplete; это failed, а не нулевая оценка.
Результат `FreeResponseEvaluation` включает rubric_scores {criterion_id, score
0–4, explanation}, point_checks {point_id, met, evidence}, language_match,
corrections {original, suggested, explanation}, summary и suggestions.
Все списки/строки ограничены: criteria 8, points 12, corrections 20 по 500
символов, summary ≤2000, suggestions ≤8 по 500. Unknown/duplicate criterion IDs,
чужие source refs и цитаты original не из ответа отклоняются сервером.
Результат также имеет assessability assessable/insufficient_context и reason
nullable. Insufficient_context после отправки — failed без Attempt, не score=0;
контекст не расширяется автоматически новыми материалами для уже отправленного ответа.

Итог 0–100 вычисляет сервер: ROUND_HALF_UP(sum(weight * score / 4)). Выполнение
задания: score ≥70, все essential points met, language_match и учебный диапазон
слов соблюдён. Attempt.correct — этот сохранённый итоговый bool; отдельные
score/content/language/word_limit поля объясняют причину. Порог и rubric
фиксированы снимком; история не пересчитывается после изменения критериев.
Содержательные альтернативные объяснения и рекомендации модели считаются
тренировочной обратной связью. Они не выдаются за безошибочную экспертную оценку.

Снимок version=3 сохраняет критерии, пример и ровно те фрагменты материалов,
которые подтверждают expected_points. ≤20 фрагментов по ≤4000 символов, суммарно
≤80000. Они уже должны быть выбраны при подготовке, не обрезаются при ответе.
Если не помещаются, подготовка требует меньший объём/более узкий вопрос.
Удаление материала убирает исходный файл, но фрагменты своего занятия остаются
в истории, как и прежние текстовые snapshots. Public whitelist не выдаёт
model_answer/expected_points/fragment text/AI prompt до ответа. Объяснение после
оценки использует фиксированный контекст занятия, не другую тему или текущую Card.

`Evaluation` с unique(session_card_id) отдельно хранит неизменный отправленный
ответ, request fingerprint/key, статус, Job, результат и evaluation_revision=1.
POST answer для нового типа возвращает 202/Job, позиция ещё не увеличивается.
Queued/running/failed/unknown не создают Attempt и не ухудшают счёт. Worker после
полного валидного ответа атомарно создаёт одну Attempt, сохраняет _grading v2,
перемещает position ровно раз. Snapshot/SessionImage не меняются.
Перед вызовом и сохранением проверяет владельца, живое занятие и текущую позицию.
Внешний вызов выполняется вне SQLite write transaction; завершение — compare-and-set.

Attempt.value = {free_text, audio_answer_id:null|id, _grading}; v2 _grading хранит
evaluation_id, score, correct, word_count, word_count_version:1, word_limit
{min,max,met}, language_match, rubric_scores, point_checks, corrections, summary,
suggestions, input_method text/voice. Для voice добавляется voice
{original_transcript,original_word_count,was_edited}. Перед созданием Evaluation
canonical_submission валидирует эти новые поля; служебную _grading клиент прислать
не может. Replay сравнивает только free_text/audio_answer_id, не результат модели.
Quiz reveal нового типа до Attempt запрещён, Explain до финальной Attempt тоже.

Одинаковый key+payload возвращает тот же Evaluation/Job/feedback; изменённый
payload/key при существующей Evaluation=409. После отправки текст неизменяем;
ошибку исправляют новым занятием, а не повторной оценкой того же ответа.
Manual retry разрешён только failed/unknown, с новым ключом и явной платностью,
но тем же отправленным текстом. Completed не переоценивается. Generic job retry
для evaluate_response отвергается 409. При возврате/reload UI восстанавливает
Evaluation; локальный ещё не отправленный текст autosave не обещает.

`EvaluationRequest` считает каждую попытку провайдера, включая retries/timeout:
job_id, attempt_no, request_key, reserved_at UTC, status, model и безопасный usage.
FREE_RESPONSE_DAILY_REQUEST_LIMIT default 100 для семьи, FEATURE flag
FREE_RESPONSE_ENABLED=false до выпуска; timezone BUDGET_TIMEZONE default
Europe/Vilnius. Reserve под write-lock перед каждой отправкой внутри retry,
не вокруг Job; лимит и Retry-After не обходятся. Unknown/crash не дают refund;
перезапуск не повторяет внешнюю операцию автоматически. Повтор полученного
durably staged результата сохраняет локально без новой модели. Отдельные
image/evaluation/audio лимиты не заменяют долларовый лимит аккаунта OpenAI.

## История, повтор и удаление

Старые Attempt без _grading и v1 читаются прежним образом; v2 содержит исходный
ответ, счётчик, rubric scores и computed correctness, не пересчитывается.
Repeat берёт неверные завершённые Attempt и закрытые снимки источника, копирует
старые SessionImage. Новый ответ получает новую Evaluation, прежняя не переносится.
Незавершённые/failed Evaluation не становятся «неверными для повторения».
Удаление Card/Topic/Subject сохраняет активное/завершённое занятие и его snapshot.
Bulk-delete истории отменяет evaluation/transcription jobs, удаляет их текстовые
payload/result, Evaluation/Attempt и session refs; поздний worker не восстанавливает
их. Небольшой учёт запросов без учебных текстов удерживается 30 дней для квоты,
чтобы удаление истории не возвращало расход; затем очищается идемпотентно.
Job list/result/retry этих типов только владельцу, без ответов в общих Jobs.

## Этап 2: Картинка как материал задания

`PictureDescriptionExercise` наследует языковую часть свободного ответа, goal
только language. Подготовка выбирает сохранённую question ImageAsset, одной
картинки достаточно. Новая Card сначала draft с image attachment; подготовка
criteria — отдельная явная AI задача. Запуск не генерирует новую картинку.
Флаг PICTURE_DESCRIPTION_ENABLED=false до этого этапа. Пользователь видит
платность визуальной подготовки и оценки; доступ модели проверяется без пробной оплаты.

Создание до критериев: `POST /api/topics/{id}/picture-drafts` принимает upload
и language/level/min/max/key, нормализует картинку без AI и создаёт Card draft.
Exercise в этом draft — PictureDraftSetup с preparation_state=needs_criteria;
это отдельная внутренняя схема, не валидное готовое упражнение. PictureDraftRequest
unique(user_id,key) хранит fingerprint/settings и Card ID, duplicate совпадающего
upload возвращает Card, другой payload=409; удалённая Card не воскрешается.
Начальный вопрос «Опиши картинку» записывается на явно выбранном языке задания,
не на текущем языке UI. Пользователь может отредактировать его до подготовки.

CardImage/SessionImage сохраняют `image_role=source`, остальные — illustration;
роль принадлежит связи, не глобальному asset, чтобы одна картинка могла служить
иллюстрацией другого вопроса. Источник неизменяем
и закреплён CardImage(question) и SessionImage(question); замена/удаление после
Save требует нового preview с criteria и Card.version, делает текущую Card draft.
Нельзя применять старые criteria к другому asset. Apply фиксирует source asset,
его hash, criteria и version одной транзакцией. Для нового типа регенерация
передаёт выбранную question image, у остальных regenerate/explain по-прежнему
не видят иллюстраций. Explanation picture после ответа использует SessionImage.
Answer illustration может оставаться необязательной по прежним правилам скрытия.

Snapshot version=4 хранит source asset/hash и скрытый эталон наблюдаемых деталей,
при оценке модель получает реальные безопасные байты через сервер, не private
HTTP URL с cookie. Vision capability/config mismatch → failed/unavailable,
никакого silently text-only grading. Alt содержит нейтральную подпись,
не эталонное описание. Public JSON не раскрывает скрытые visual criteria.
Модель оценивает наблюдаемые детали, не выдумывает имена/место/исторические факты.
В этом типе SourceRef для текстовых Document необязательны; typed union
TextEvidence(document_id,page)/ImageEvidence(asset_id,sha256) не ломает старую
SourceRef или проверку refs старых вопросов. Доступ не даётся по одному asset ID.

Image cleanup учитывает CardImage/SessionImage и активные vision Job refs.
JobImage получает role candidate/context (default candidate для старых связей);
context удерживает source asset только до terminal/отмены job и не становится
редактируемым кандидатом. Discard candidate не удаляет context другой активной задачи.
Старое занятие/повтор всегда видит старую картинку и criteria после замены/удаления
Card. После последней связи history/current/candidate/active job файл удаляется.
Новый task generation не переиспользует недоступный source asset и не воскрешает Card.

## Этап 3: Голосовой ввод

Пользователь выбирает «Напиши» или «Расскажи» на том же свободном задании.
Голос доступен только free_response/picture_description. Язык фиксирован заданием.
TRANSCRIPTION_ENABLED=false по умолчанию; начальная модель gpt-transcribe,
переопределяемая оператором. Это отдельный Audio API adapter, не изменение
текстовой модели и не озвучка. Config/startup не делают тестовых платных запросов.

Сценарий: нажать запись → остановить → локально прослушать/перезаписать →
«Распознать (платно)» → проверить транскрипцию → «Проверить ответ (AI)».
Во время записи видны таймер и лимит 180 секунд; счётчик слов появляется после
распознавания. Live счётчик/streaming не обещаются. Microphone только HTTPS,
после пользовательского действия; отказ/неподдерживаемый браузер оставляет текст.
MediaRecorder выбирает поддерживаемый mime, не только Chrome webm.
Предел upload 15 MiB/180 секунд; сервер проверяет реальные media streams и duration.
WebM/MP4(Ogg/WAV при поддержке клиента) с аудио, video track запрещён.
ffprobe/ffmpeg в Docker: argv без shell, stdin disabled, bounded timeout 10/30 s,
без network/protocol URLs; только UUID файл сервера; normalize mono 16 kHz WAV.
Проверка duration использует число декодированных WAV samples, не только metadata
ffprobe. Decode ограничен 181 секундой, результат >180 отвергается целиком,
не превращается молча в обрезанное допустимое аудио. Unknown duration и video
отвергаются; квота резервируется по проверенной декодированной длительности.

Файлы `/data/answer-audio`, owner/session-bound, не static. Local replay требует
только `media-src 'self' blob:`; img-src/connect-src прежние, blob URL освобождается
при discard/unmount. После upload replay через authenticated endpoint до очистки.
AudioAnswer связывает session_card, owner, hash, duration, status, raw path,
expires_at, original_transcript, expected_language и was_edited. Результат
транскрипции фиксируется до оценки; повтор запроса не распознаёт снова.
Редактировать транскрипт можно до отправки: оригинал и окончательный текст
сохраняются, edited явно означает оценку отредактированного текста. Грамматика
распознанного текста не объявляется точной оценкой произнесённой грамматики.
Не оцениваются произношение, акцент, темп и паузы по одной транскрипции.

POST multipart audio содержит position/key; duplicate bytes/key возвращает
тот же AudioAnswer/Job. Другие bytes с тем же key=409; чужая session=404.
Одна активная transcription на session card; явная перезапись после discard,
если ещё нет отправленной Evaluation. Обычный /answer не вызывает transcription.
Распознавание создаёт private Job, без Attempt/движения position. Ошибка не
считается неверным ответом, текстовый ввод остаётся доступен. Transcribe отвечает
исходным языком без translation endpoint. language mismatch виден до оценки.

TRANSCRIPTION_DAILY_SECONDS_LIMIT default 1800 для семьи, та же BUDGET_TIMEZONE.
TranscriptionRequest резервирует ceil(server_duration_seconds) перед каждым
внешним запросом, включая ручной retry; одна отправка, SDK retries=0.
Три попытки текста/DownSub автоматически на Audio API не переносятся: timeout
может уже стоить денег. Retry failed/unknown только явно платной кнопкой и новым
key, без generic retry и без нового evaluation. Бюджет не возвращается при удалении.
Минимальная цена не обещается — usage/model фиксируются, реальные тарифы проверяются
при включении. 1800 секунд — ограничение длительности запросов, не dollar cap.

Raw audio удаляется сразу после долговременного сохранения транскрипции/явного
discard/history delete; failed запись доступна для retry до 24 часов, затем
чистится. Чужие/невалидные upload и .part очищаются после отказа/сбоя; failed
unlink остаётся в очереди очистки. AudioAnswer/transcript хранится до удаления
истории, сам звук в истории не воспроизводится. Пользователь видит это правило.
Cleanup не удаляет запись running Job: зависший worker помечается unknown,
его late completion проверяет revision/cancelled; timeout storage recovery
не обещает сохранение байтов, оставшихся только в памяти. Во время backup
временно сохранённый raw может попасть в защищённый архив; backup не публичный.
Retention действующих файлов не обещает очистку старых резервных копий задним числом.

## Приёмка и источники

Тесты каждой фазы с подменой провайдера и сериализацией реальной JSON schema;
никаких оплачиваемых CI-запросов. Browser desktop/mobile PL/EN/RU, keyboard,
ошибки/timeout/reload, две вкладки, лимиты/пустые ответы, возврат к теме,
старые deterministic задания/история. Голос дополнительно Chromium и WebKit,
fake microphone/permission denial, реальная проверка iOS Safari до заявления
о поддержке; отсутствие устройства фиксируется как ограничение проверки.
Полный `sh scripts/check.sh`: pytest, Vitest, Playwright, Ruff/format, ESLint,
build, Bandit, Semgrep. Миграции/backup/rollback на копии с новым и старым контентом,
production .env/Traefik/том сохраняются. Только после отдельной реализации
возможны commit/push/deploy по авторизации пользователя, не в этой работе.

Документация проверена 14 октября 2026:
[OpenAI transcription](https://developers.openai.com/api/docs/guides/transcription),
[OpenAI pricing](https://developers.openai.com/api/docs/pricing),
[CEFR levels](https://www.coe.int/en/web/common-european-framework-reference-languages/level-descriptions).

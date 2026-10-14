# Третье критическое ревью: свободный ответ, картинка и голос

Дата: 14 октября 2026. Ревью документов и контрактов с текущим кодом,
без реализации, оплачиваемых вызовов, коммита, push и обновления сервера.
Основание: пользователь подтвердил три этапа и повторную проверку совместимости.

Проверены спецификации/планы language-exercises, question-images и free-responses.
Ревью I01–I10 остаётся верным для первых этапов; прежняя граница «иллюстрации»
явно расширяется только новым типом picture_description.

## F01 — P1: Два разных письменных ответа нельзя объединить в written

Прежний written ожидает допустимые короткие строки, grade_answer детерминирован.
Если расширить его текст до сочинения, старые вопросы внезапно сменят правила.
Решение: новый free_response, free_text до10000/2000 слов, written text до1000
по прежнему контракту. Старый label уточнить до «Короткий письменный ответ».
Tests: plan Tasks1/3/4, RequiresEvaluation routing, legacy grader/Attempt regression.

## F02 — P1: API-сбой нельзя записывать как неверный ответ

Текущий `backend/app/study.py` создаёт Attempt с bool correct и сразу двигает
позицию. Для фоновой AI-оценки такой порядок потеряет ответы/исказит счёт.
Решение: Evaluation отдельно; 202, pending без Attempt. Полный валидный результат
фиксируется CAS/транзакцией один раз. Failed/unknown/insufficient_context не score0.
Tests: Tasks2/3/4, две вкладки/workers, staged result, timeout commit, reload/retry.

## F03 — P1: Оценка должна иметь фиксированную шкалу и жизненный цикл

Обещание «модель проверяет смысл» без критериев допускает другую оценку при
каждом открытии/повторе HTTP. Решение: rubric до занятия, weights100, scores0–4,
серверный HALF_UP итог/threshold70/essential/language/word_limit. _grading v2
не пересчитывается; исправление отправленного текста только новым занятием.
Completed retry запрещён. Одинаковый request возвращает прежний результат.
Tests: Tasks1/3, schema/IDs/quotes/rounding, saved feedback после изменения Card.

## F04 — P2: Счётчик слов может спорить сам с собой и с требованиями задания

Whitespace split не обрабатывает Unicode/апострофы/дефисы одинаково в Python/JS.
CEFR также не задаёт единый word target для любого вопроса одного уровня.
Решение: word_count_version1/общие fixtures; min/max на задании, server count,
outside target warning не блокирует отправку и не обнуляет content score.
Технические bounds отдельно. Для речи timer сейчас, count после transcription.
Tests: Tasks1/4/7, PL/LT NFC/NFD/дефисы/пунктуация/emoji и client tampering.

## F05 — P1: Локаль UI, язык источника и уровень — разные настройки

Решение: текстовый источник не переводится, known language фиксирован, mixed
sources требуют уточнения, unknown требует явного подтверждения. Language goal
требует выбрать CEFR, content level=null. Picture без текстового языка имеет
явный язык описания. Исправления на языке задания. CEFR feedback тренировочный.
Tests: Tasks2/4/5/6/7, польский/литовский контент при русском UI, level input validation.

## F06 — P1: Смешанная практика не должна незаметно стать платной

Раньше default выбирал общий готовый набор всех известных типов. После добавления
AI grading он включил бы новые методы без намерения пользователя оплатить проверку.
Решение: default old six intersection; explicit include_ai_evaluated и выбранные
types. Ready отдельно от runtime availability. Start без AI, все missing_pairs
проверяются по-прежнему. Конфигурация проверяется без платной пробной операции.
Tests: Tasks3/4/5, default/explicit/multi-topic/off/missing key/no job assertions.

## F07 — P1: Источники и критерии нельзя заново собирать из текущей библиотеки

Материал/Card могут измениться/удалиться до отправки ответа или повторения.
Решение: fixed source fragments и rubric в snapshot v3, bounded preparation,
no runtime truncation. Repeat копирует старое задание и SessionImage, новая
Evaluation только по новому ответу. Никакого нового материала при retry failed.
History delete очищает учебные payload/results и отменяет поздние workers.
Tests: Tasks2/3/5/6, source delete, repeated history, privacy, last refs/recovery.

## F08 — P1: Визуальному заданию нужен путь создания без текстового Document

Текущий GeneratedCard/SourceRef требует текстовые sources, image-план лишь
прикреплял иллюстрации к существующей Card. Из этого нельзя начать picture-only.
Решение: upload picture-drafts без AI, PictureDraftSetup needs_criteria,
идемпотентный PictureDraftRequest; затем явная prepare-picture/preview/Save.
Pending draft не ready. Typed TextEvidence/ImageEvidence не меняет старый SourceRef.
Tests: Task5, image-only topic, duplicate upload, deleted draft replay410, no model calls.

## F09 — P1: Замена картинки делает прежние визуальные критерии недействительными

Решение: роль source на CardImage/SessionImage, не на глобальном asset. Source
replacement/remove делает Card draft; source hash+criteria применяются атомарно.
Обычные illustration/regenerate/explain не получают vision. В новом типе модель
видит настоящие безопасные bytes, не закрытый URL. Context JobImage refs отдельно
от кандидатов; history/repeat сохраняют старую картинку/criteria. Нет text-only fallback.
Tests: Task5, asset/version conflict, atomic apply, source delete/repeat/last-reference.

## F10 — P1: Общая retry-политика может умножить оплату

В `backend/app/retry.py` три попытки; SDK retry выключен. Квота, проверенная
один раз вокруг Job, не посчитает вторую/третью отправку и ручной retry.
Решение: EvaluationRequest hook на каждый внешний вызов, family daily100,
UTC/DST/timezone, no refund при unknown/crash/delete; generic retry запрещён.
Image policy прежняя без auto retry. Audio отдельно one call с duration ledger,
ручной явно платный retry, лимит1800 секунд/день. Ledger без контента хранить30д.
Tests: Tasks2/3/6, concurrent budget boundaries, retries same Job, DST/reset/delete.

## F11 — P1: Транскрипция не доказывает качество произношения и не всегда точна

Решение: голос — input method, не новый тип grader. Показать исходный transcript,
позволить правку до grading, сохранить original/final/was_edited/count. Это оценка
текста; ошибки ASR не объявлять доказательством произнесённых грамматических ошибок.
Никакого pronunciation/accent/tempo score по транскрипции, TTS или live counters.
Tests: Tasks6/7, changed transcript audit, language mismatch, no pronunciation fields.

## F12 — P1: Browser MIME и duration клиента нельзя считать надёжными

Текущая CSP `backend/app/main.py` не разрешает media blob; WebM-only ломает Safari.
Решение: format feature detection, HTTPS/user click, permission/text fallback,
только media-src self blob. Server decode аудио, actual WAV sample duration,
15MiB/180s, bounded ffprobe/ffmpeg без shell/network, video reject.
Decode181s с отказом >180, не усечение для обхода бюджета. Docker non-root.
Tests: Tasks6/7, MP4/WebM fixtures, false MIME/duration, timeout, Chromium/WebKit,
actual iOS smoke отдельно с честным ограничением QA при отсутствии устройства.

## F13 — P1: Raw audio нельзя сохранять бесконечно или удалить посреди распознавания

Решение: private owner/session files, local replay before submit, raw после durable
transcript удалить, failed24h, running исключён из TTL до recovery/unknown.
Late completion проверяет revision/cancelled. История хранит текст, не replay аудио.
Backup защищён и может содержать временный raw; retention не означает удаление
из старых архивов. History deletion отменяет private jobs/чистит raw и transcripts.
Миграции0009–0011 после0008 без competing heads; Images API можно оставить off.
Tests: Tasks3/5/6/7, writing/.part/unlink failure/recovery, bulk history deletion,
backup restore/rollback с новой схемой и private files, git/build context audit.

## Результат самопроверки

F01–F13 включены в новые spec/plan с владельцами реализации и проверками.
У обоих предыдущих планов/spec добавлены явные границы последующего расширения.
Исторические отчёты первых двух ревью не переписаны задним числом.
Три фазы выпуска независимы: письменный режим, затем визуальный, затем голос;
платная генерация картинок может оставаться отключённой во всех трёх.
Готовы только документы. Тесты приложения/браузер/линтеры будут выполнены
во время реализации каждого этапа, сейчас они не объявляются пройденными.

import json

from fastapi import HTTPException
from sqlalchemy import select

from .models import Card, Job
from .schemas import QuizOptions


def correct_indices(card):
    if isinstance(card, dict):
        indices, index = card.get("correct_indices"), card.get("correct_index")
    else:
        indices, index = card.correct_indices, card.correct_index
    return indices or ([] if index is None else [index])


def quiz_ready(card):
    if getattr(card, "question_type", "choice") != "choice":
        return False
    return (
        2 <= len(card.options) <= 6
        and len(set(card.options)) == len(card.options)
        and bool(correct_indices(card))
        and len(set(correct_indices(card))) == len(correct_indices(card))
        and all(0 <= index < len(card.options) for index in correct_indices(card))
    )


def preparation_job(db, user_id, topic_ids, snapshots):
    snapshots = [
        {key: value for key, value in card.items() if key != "images"} for card in snapshots
    ]
    signature = [
        (card["id"], card["version"], json.dumps(card.get("sources", []), sort_keys=True))
        for card in snapshots
    ]
    for job in db.scalars(
        select(Job)
        .where(
            Job.kind == "prepare_quiz",
            Job.user_id == user_id,
            Job.status.in_(["queued", "running", "failed"]),
        )
        .order_by(Job.id.desc())
    ):
        if (
            job.payload["topic_ids"] == topic_ids
            and [
                (card["id"], card["version"], json.dumps(card.get("sources", []), sort_keys=True))
                for card in job.payload.get("cards", [])
            ]
            == signature
        ):
            return job
    sources = {
        (source["document_id"], source["page"]): source
        for card in snapshots
        for source in card["sources"]
    }
    if sum(len(source.get("text", "")) for source in sources.values()) > 100000:
        raise HTTPException(422, "Материалы превышают 100 000 символов. Выберите меньше документов")
    job = Job(
        user_id=user_id, kind="prepare_quiz", payload={"topic_ids": topic_ids, "cards": snapshots}
    )
    db.add(job)
    db.flush()
    return job


def prepare_options(ai, payload, before_each=None):
    results = []
    for snapshot in payload["cards"]:
        if before_each is not None:
            before_each()
        result = QuizOptions.model_validate(ai.prepare_quiz(snapshot))
        if result.card_id != snapshot["id"] or (
            len(result.correct_indices) == 1
            and result.options[result.correct_indices[0]] != snapshot["answer"]
        ):
            raise ValueError("Модель изменила правильный ответ при подготовке теста")
        results.append(result)
    return results


def validate_preparation(db, payload):
    cards = [db.get(Card, snapshot["id"]) for snapshot in payload["cards"]]
    if any(
        card is None
        or card.version != snapshot["version"]
        or card.status != "saved"
        or card.question_type != "choice"
        for card, snapshot in zip(cards, payload["cards"], strict=True)
    ):
        raise ValueError("Вопрос изменён во время подготовки теста. Запустите тест заново")
    return cards


def save_options(db, payload, results):
    cards = validate_preparation(db, payload)
    for card, result in zip(cards, results, strict=True):
        card.mode, card.options, card.correct_index = "quiz", result.options, result.correct_index
        card.correct_indices = result.correct_indices
        card.version += 1


def free_settings(exercise):
    """The settings that preparation/regeneration must preserve exactly."""
    from .schemas import FreeResponseSettings

    return FreeResponseSettings.model_validate(
        {key: exercise.get(key) for key in ("goal", "language", "level", "min_words", "max_words")}
    ).model_dump()


def validate_free_preparation(card, sources, settings=None):
    """Validate selected evidence against authorized original pages, never model refs alone."""
    from .free_responses import FreeResponseExercise

    exercise = FreeResponseExercise.model_validate(card["exercise"])
    if card.get("question_type") != "free_response" or card.get("mode") != "quiz":
        raise ValueError("Нужен свободный ответ в режиме quiz")
    if card.get("target_language") or card.get("language") != exercise.language:
        raise ValueError("Язык задания должен совпадать с исходным языком")
    if settings is not None and free_settings(exercise.model_dump()) != free_settings(settings):
        raise ValueError("Модель изменила настройки свободного ответа")
    originals = {(s["document_id"], s["page"]): s for s in sources}
    refs = {(s["document_id"], s["page"]) for s in card["sources"]}
    if not refs or not refs <= originals.keys():
        raise ValueError("Недопустимый источник задания")
    languages = {s.get("language") for s in sources if s.get("language")}
    if len(languages) > 1 or languages and exercise.language not in languages:
        raise ValueError("Источники должны сохранять язык задания")
    used = {(r.document_id, r.page) for point in exercise.expected_points for r in point.sources}
    for fragment in exercise.source_fragments:
        ref = (fragment.source.document_id, fragment.source.page)
        if (
            ref not in refs
            or ref not in used
            or fragment.text not in originals[ref].get("text", "")
        ):
            raise ValueError("Фрагмент должен дословно входить в разрешённый источник пункта")
    return exercise


def build_free_snapshot(card: dict, source_fragments: list) -> dict:
    """Freeze only previously prepared evidence; never fetch or truncate current pages."""
    import copy

    from .free_responses import FreeResponseExercise

    exercise = FreeResponseExercise.model_validate(card["exercise"])
    prepared = exercise.model_dump()["source_fragments"]
    if source_fragments != prepared:
        raise ValueError("Снимок должен использовать ранее подготовленные фрагменты")
    if (
        card.get("question_type") != "free_response"
        or card.get("mode") != "quiz"
        or card.get("language") != exercise.language
        or card.get("target_language")
    ):
        raise ValueError("Настройки снимка не согласованы")
    # Membership in full original pages was checked at preparation/edit time.
    originals = {
        (source["document_id"], source["page"]): source for source in card.get("sources", [])
    }
    sources = {}
    for fragment in prepared:
        ref = (fragment["source"]["document_id"], fragment["source"]["page"])
        if ref not in originals:
            raise ValueError("Фрагменты не принадлежат источникам карточки")
        if ref not in sources:
            sources[ref] = {key: value for key, value in originals[ref].items() if key != "text"}
            sources[ref]["text"] = fragment["text"]
        else:
            sources[ref]["text"] += "\n\n" + fragment["text"]
    snapshot = copy.deepcopy(card)
    snapshot.update(
        snapshot_version=3, exercise=exercise.model_dump(), answer=exercise.model_answer
    )
    # Preserve source display labels while replacing full pages with selected excerpts.
    snapshot["sources"] = copy.deepcopy(list(sources.values()))
    return snapshot

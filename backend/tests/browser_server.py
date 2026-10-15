"""Disposable browser-test server; never included in the production image."""

import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from app import downsub, evaluations, image_generation
from app.cli import create_user
from app.config import Settings
from app.main import create_app
from fakes import FixtureAI
from PIL import Image

_data = TemporaryDirectory(prefix="learning-browser-")


class BrowserAI(FixtureAI):
    def generate(
        self,
        topic_id,
        sources,
        mode,
        count,
        target_language=None,
        existing=None,
        question_types=None,
        type_counts=None,
        practice_goal="content",
        free_response_settings=None,
    ):
        from app.schemas import Generated, GeneratedCard, SourceRef

        if free_response_settings:
            ref = {"document_id": sources[0]["document_id"], "page": sources[0]["page"]}
            settings = free_response_settings
            exercise = {
                **settings,
                "model_answer": "Ąžuolas yra medis. Jis auga miške.",
                "rubric": [
                    {
                        "id": "clarity",
                        "label": "Aiškumas " + (settings["level"] or "turinys"),
                        "weight": 100,
                    }
                ],
                "expected_points": [
                    {"id": "tree", "text": "Ąžuolas yra medis", "essential": True, "sources": [ref]}
                ],
                "source_fragments": [{"source": ref, "text": sources[0]["text"]}],
            }
            return Generated(
                insufficient_reason=None,
                cards=[
                    GeneratedCard(
                        topic_id=topic_id,
                        question=f"Aprašyk ąžuolą {i}",
                        answer=exercise["model_answer"],
                        mode="quiz",
                        options=[],
                        question_type="free_response",
                        exercise=exercise,
                        sources=[SourceRef(**ref)],
                        language=settings["language"],
                    )
                    for i in range(count)
                ],
            )
        kinds = question_types or ["choice"]
        if kinds == ["choice"]:
            result = super().generate(topic_id, sources, mode, count, target_language, existing)
            for index, card in enumerate(result.cards):
                card.question = f"Jak nazywa się rzeka? {len(existing or []) + index + 1}"
                card.answer = "Nil"
                card.options = ["Nil", "Wisła", "Odra"] if mode == "quiz" else []
                card.language = "pl"
            return result
        exercises = {
            "written": {"accepted_answers": ["Nil"], "case_sensitive": False},
            "gap": {
                "segments": [
                    {"text": "Nil to "},
                    {"gap_id": "river"},
                    {"text": " w "},
                    {"gap_id": "country"},
                ],
                "gaps": [
                    {"id": "river", "accepted_answers": ["rzeka"]},
                    {"id": "country", "accepted_answers": ["Egipcie"]},
                ],
                "accepted_combinations": [["rzeka", "Egipcie"]],
                "case_sensitive": False,
            },
            "ending": {
                "segments": [{"text": "Nil to rzek"}, {"gap_id": "end"}],
                "gaps": [{"id": "end", "accepted_answers": ["a"]}],
                "accepted_combinations": [["a"]],
                "case_sensitive": False,
            },
            "matching": {
                "pairs": [{"left": "Nil", "right": "rzeka"}, {"left": "Egipt", "right": "kraj"}]
            },
            "ordering": {
                "tokens": ["Nil", "to", "rzeka"],
                "accepted_orders": [["Nil", "to", "rzeka"]],
            },
        }
        return Generated(
            insufficient_reason=None,
            cards=[
                GeneratedCard(
                    topic_id=topic_id,
                    question=f"Zadanie {kind} {i}",
                    answer="",
                    mode="quiz",
                    options=[],
                    question_type=kind,
                    exercise=exercises[kind],
                    sources=[
                        SourceRef(document_id=sources[0]["document_id"], page=sources[0]["page"])
                    ],
                    language="pl",
                )
                for kind in kinds
                for i in range((type_counts or {}).get(kind, count))
            ],
        )

    def explain(self, snapshot, question, history):
        assert "images" not in snapshot
        assert all("asset_id" not in source for source in snapshot["sources"])
        return super().explain(snapshot, question, history)

    def regenerate(self, card, sources):
        assert "images" not in card
        assert all("asset_id" not in source for source in sources)
        from app.regeneration import Regenerated
        from app.schemas import GeneratedCard, SourceRef

        values = {
            key: card[key]
            for key in (
                "topic_id",
                "question_type",
                "question",
                "answer",
                "mode",
                "options",
                "correct_index",
                "correct_indices",
                "language",
                "exercise",
            )
        }
        values["question"] += " (nowy wariant)"
        values["sources"] = [
            SourceRef(document_id=s["document_id"], page=s["page"]) for s in sources
        ]
        return Regenerated(card=GeneratedCard(**values), insufficient_reason=None)


def subtitle_boundary(method, url, **kwargs):
    """Only external HTTP is replaced; parsing, caching and jobs stay real."""
    if method == "POST" and url == "https://get.downsub.com/":
        canonical = json.loads(kwargs["data"])["url"]
        language = "lt" if "LTfree12345" in canonical else "pl"
        return json.dumps(
            {
                "url": canonical,
                "state": 2,
                "subtitles": [
                    {
                        "name": "Polish (auto-generated)",
                        "language": language,
                        "type": "youtube",
                        "code": language + "_auto",
                        "url": "browser-test-reference-" + language,
                    }
                ],
                "subtitlesAutoTrans": [{"language": "ru"}],
            }
        ).encode()
    if method == "GET" and url.startswith("https://subtitle.downsub.com/srt/"):
        text = (
            "Ąžuolas yra medis. Jis auga miške."
            if "reference-lt" in url
            else "Nil to rzeka w Egipcie."
        )
        return ("1\n00:00:05,894 --> 00:00:09,250\n" + text + "\n").encode()
    raise AssertionError("Unexpected external request in browser tests")


class BrowserImageGenerator:
    """Provider boundary only: SQLite, workers, normalization and private files stay real."""

    attempts = {}

    def __init__(self, settings, model):
        assert model == "browser-image-fixture"

    def generate(self, prompt):
        self.attempts[prompt] = self.attempts.get(prompt, 0) + 1
        if "timeout once" in prompt and self.attempts[prompt] == 1:
            raise image_generation.ImageOutcomeUnknown()
        if "provider denied" in prompt:
            raise image_generation.ImageProviderFailure("access_denied")
        data = io.BytesIO()
        Image.new("RGBA", (320, 180), (40, 110, 200, 128)).save(data, format="PNG")
        return image_generation.GeneratedImage(data.getvalue(), {"usage": {"total_tokens": 1}})


class BrowserEvaluationAI:
    """Paid provider boundary only; real reservation, durable stages and finalization."""

    attempts = {}

    def __init__(self, settings):
        pass

    def evaluate(self, snapshot, answer, before_request):
        import time

        from app.ai import TransientError
        from app.free_responses import FreeResponseEvaluation

        before_request()
        time.sleep(2)
        self.attempts[answer] = self.attempts.get(answer, 0) + 1
        if "nežinoma" in answer and self.attempts[answer] == 1:
            raise TransientError("Fixture unknown outcome")
        exercise = snapshot["exercise"]
        return FreeResponseEvaluation.model_validate(
            {
                "assessability": "assessable",
                "reason": None,
                "language_match": True,
                "rubric_scores": [
                    {"criterion_id": row["id"], "score": 3, "explanation": "Aišku ir suprantama."}
                    for row in exercise["rubric"]
                ],
                "point_checks": [
                    {"point_id": row["id"], "met": True, "evidence": []}
                    for row in exercise["expected_points"]
                ],
                "corrections": [],
                "summary": "Geras atsakymas.",
                "suggestions": ["Rašyk daugiau."],
            }
        )


def browser_app():
    port = int(os.environ.get("E2E_PORT", "18940"))
    settings = Settings(
        _env_file=None,
        data_dir=Path(_data.name),
        app_origin=f"http://localhost:{port}",
        cookie_secure=False,
        openai_api_key="browser-fixture-only",
        free_response_enabled=True,
        image_generation_enabled=True,
        openai_image_model="browser-image-fixture",
        image_daily_request_limit=100,
        youtube_provider="downsub",
        frontend_dir=Path("frontend/dist"),
    )
    evaluations.EvaluationAI = BrowserEvaluationAI
    downsub.request = subtitle_boundary
    image_generation.ImageGenerator = BrowserImageGenerator
    instance = create_app(settings, ai=BrowserAI())
    create_user(instance.state.db, "child", "Browser Child", "browser-child-password")
    create_user(instance.state.db, "parent", "Browser Parent", "browser-parent-password")
    for device in ("desktop", "mobile"):
        create_user(
            instance.state.db, f"profile_{device}", "Browser Profile", "browser-profile-password"
        )
    return instance


if __name__ == "__main__":
    uvicorn.run(
        browser_app(),
        host="127.0.0.1",
        port=int(os.environ.get("E2E_PORT", "18940")),
        access_log=False,
    )

"""Disposable browser-test server; never included in the production image."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from app import downsub
from app.cli import create_user
from app.config import Settings
from app.main import create_app
from fakes import FixtureAI

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
    ):
        from app.schemas import Generated, GeneratedCard, SourceRef

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
        return json.dumps(
            {
                "url": canonical,
                "state": 2,
                "subtitles": [
                    {
                        "name": "Polish (auto-generated)",
                        "language": "pl",
                        "type": "youtube",
                        "code": "pl_auto",
                        "url": "browser-test-reference",
                    }
                ],
                "subtitlesAutoTrans": [{"language": "ru"}],
            }
        ).encode()
    if method == "GET" and url.startswith("https://subtitle.downsub.com/srt/"):
        return b"1\n00:00:05,894 --> 00:00:09,250\nNil to rzeka w Egipcie.\n"
    raise AssertionError("Unexpected external request in browser tests")


def browser_app():
    port = int(os.environ.get("E2E_PORT", "18940"))
    settings = Settings(
        _env_file=None,
        data_dir=Path(_data.name),
        app_origin=f"http://localhost:{port}",
        cookie_secure=False,
        openai_api_key="",
        youtube_provider="downsub",
        frontend_dir=Path("frontend/dist"),
    )
    downsub.request = subtitle_boundary
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

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
    def generate(self, topic_id, sources, mode, count, target_language=None, existing=None):
        result = super().generate(topic_id, sources, mode, count, target_language, existing)
        for index, card in enumerate(result.cards):
            card.question = f"Jak nazywa się rzeka? {len(existing or []) + index + 1}"
            card.answer = "Nil"
            card.options = ["Nil", "Wisła", "Odra"] if mode == "quiz" else []
            card.language = target_language or "pl"
        return result


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
    return instance


if __name__ == "__main__":
    uvicorn.run(
        browser_app(),
        host="127.0.0.1",
        port=int(os.environ.get("E2E_PORT", "18940")),
        access_log=False,
    )

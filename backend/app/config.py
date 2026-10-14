from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    data_dir: Path = Path("data")
    app_origin: str = "http://localhost:8080"
    cookie_secure: bool = True
    openai_api_key: str = ""
    openai_model: str = "gpt-6-luna"
    image_generation_enabled: bool = False
    openai_image_model: str = ""
    image_daily_request_limit: int = 10
    image_budget_timezone: str = "Europe/Vilnius"
    youtube_provider: Literal["downsub", "direct"] = "downsub"
    frontend_dir: Path = Path("frontend/dist")
    max_upload_bytes: int = 20 * 1024 * 1024

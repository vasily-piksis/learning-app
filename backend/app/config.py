from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    data_dir: Path = Path("data")
    app_origin: str = "http://localhost:8080"
    cookie_secure: bool = True
    openai_api_key: str = ""
    openai_model: str = "gpt-6-luna"
    oxylabs_username: SecretStr = SecretStr("")
    oxylabs_password: SecretStr = SecretStr("")
    frontend_dir: Path = Path("frontend/dist")
    max_upload_bytes: int = 20 * 1024 * 1024

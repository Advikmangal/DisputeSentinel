from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    paypal_client_id: str = ""
    paypal_client_secret: SecretStr = SecretStr("")
    paypal_base_url: Literal["https://api-m.sandbox.paypal.com"] = (
        "https://api-m.sandbox.paypal.com"
    )
    gemini_api_key: SecretStr = SecretStr("")
    database_url: SecretStr = SecretStr("")
    jwt_secret: SecretStr = SecretStr("")
    paypal_webhook_id: str = ""
    gemini_model: str = ""
    # T1.4 is partial; revisit after a captured Sandbox payment (docs/DECISIONS.md).
    dispute_source: Literal["fixture", "paypal"] = "fixture"
    upload_dir: Path = Path("uploads")
    frontend_origin: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()

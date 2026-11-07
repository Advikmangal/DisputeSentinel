from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
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
    demo_merchant_email: str = ""
    demo_merchant_password: SecretStr = SecretStr("")
    environment: Literal["development", "test", "production"] = "development"

    @field_validator("frontend_origin")
    @classmethod
    def exact_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if ("*" in value or parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("FRONTEND_ORIGIN must be one exact HTTP(S) origin without a path or wildcard")
        return value

    def validate_production(self) -> None:
        if self.environment == "production":
            secret = self.jwt_secret.get_secret_value()
            if len(secret) < 32 or secret.startswith("replace-"):
                raise RuntimeError("Production requires a JWT_SECRET of at least 32 characters; placeholders are not accepted")
            if not self.frontend_origin.startswith("https://"):
                raise RuntimeError("Production FRONTEND_ORIGIN must be the frontend HTTPS origin")


@lru_cache
def get_settings() -> Settings:
    return Settings()

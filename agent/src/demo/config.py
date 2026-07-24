"""Typed settings for the first-test demo."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    linq_api_key: str = ""
    linq_webhook_secret: str = ""
    runware_api_key: str = ""
    runware_base_url: str = "https://api.runware.ai/v1"
    runware_model: str = "gpt-5.6-luna"
    public_base_url: str = ""

    # Terac confirm-then-act
    terac_api_key: str = ""
    terac_base_url: str = "https://terac.com/api/external/v2"
    terac_dry_run: bool = True
    terac_dry_run_decision: str = "approve"
    terac_project_id: str = ""
    terac_webhook_secret: str = ""
    terac_require_confirmation: bool = False
    terac_expert_role: str = "robotics / manufacturing operator"

    @field_validator(
        "terac_dry_run",
        "terac_require_confirmation",
        mode="before",
    )
    @classmethod
    def _parse_bool(cls, value: object) -> bool:
        return _as_bool(value)

    @field_validator("terac_dry_run_decision", mode="before")
    @classmethod
    def _normalize_decision(cls, value: object) -> str:
        decision = str(value or "approve").strip().lower()
        if decision not in {"approve", "reject"}:
            return "approve"
        return decision


@lru_cache
def get_settings() -> Settings:
    return Settings()

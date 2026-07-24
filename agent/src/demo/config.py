"""Typed settings for the first-test demo."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    return Settings()

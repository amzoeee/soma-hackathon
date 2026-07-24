"""Typed settings for the first-test demo."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_files() -> tuple[Path, ...]:
    agent_dir = Path(__file__).resolve().parents[2]
    return (agent_dir.parent / ".env", agent_dir / ".env")


def _default_calibration_path() -> str:
    repo_root = Path(__file__).resolve().parents[3]
    return str(repo_root / "robot" / "calibration" / "my_follower.json")


def _default_urdf_path() -> str:
    repo_root = Path(__file__).resolve().parents[3]
    return str(repo_root / "robot" / "config" / "so101.urdf")


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

    robot_enabled: bool = False
    robot_port: str = "/dev/cu.usbmodem5A460824771"
    robot_calibration_path: str = _default_calibration_path()
    robot_urdf_path: str = _default_urdf_path()

    @field_validator(
        "robot_enabled",
        mode="before",
    )
    @classmethod
    def _parse_bool(cls, value: object) -> bool:
        return _as_bool(value)

@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=_env_files())

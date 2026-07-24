"""Run the first-test demo service on ``0.0.0.0:8000``."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import uvicorn

from .config import Settings

logger = logging.getLogger("demo.main")


def _load_settings() -> Settings:
    """Support either a repository-root or agent-local .env file."""
    agent_dir = Path(__file__).resolve().parents[2]
    env_files = (agent_dir.parent / ".env", agent_dir / ".env")
    return Settings(_env_file=env_files)


def _apply_runtime_environment(settings: Settings) -> None:
    """Expose values loaded from .env to modules that read the environment."""
    values = {
        "LINQ_API_KEY": settings.linq_api_key,
        "LINQ_WEBHOOK_SECRET": settings.linq_webhook_secret,
        "RUNWARE_API_KEY": settings.runware_api_key,
        "RUNWARE_BASE_URL": settings.runware_base_url,
        "RUNWARE_MODEL": settings.runware_model,
        "PUBLIC_BASE_URL": settings.public_base_url,
        "ROBOT_PORT": settings.robot_port,
        "ROBOT_CALIBRATION_PATH": settings.robot_calibration_path,
        "ROBOT_URDF_PATH": settings.robot_urdf_path,
    }
    for name, value in values.items():
        if value:
            os.environ.setdefault(name, value)
    os.environ["ROBOT_ENABLED"] = "true" if settings.robot_enabled else "false"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = _load_settings()
    _apply_runtime_environment(settings)
    logger.info(
        "Robot hardware: enabled=%s port=%s calibration=%s urdf=%s",
        settings.robot_enabled,
        settings.robot_port,
        settings.robot_calibration_path,
        settings.robot_urdf_path,
    )

    public_base_url = settings.public_base_url.rstrip("/")
    webhook_url = (
        f"{public_base_url}/webhooks/linq?version=2026-02-03"
        if public_base_url
        else "https://<tunnel>/webhooks/linq?version=2026-02-03"
    )
    logger.info("Expose port 8000 with ngrok or another HTTPS tunnel.")
    logger.info("Configure Linq to send message.received events to %s", webhook_url)

    uvicorn.run("demo.app:app", host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()

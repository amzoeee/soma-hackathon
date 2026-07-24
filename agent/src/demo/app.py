"""FastAPI application for the first-test Linq-to-robot demo."""

from fastapi import FastAPI

from .config import get_settings
from .handler import handle_message
from .linq_client import LinqClient
from .terac.webhook import create_terac_webhook_router
from .webhook import create_webhook_router


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title="Soma First Test Demo")

    @application.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    linq_client = LinqClient(api_key=settings.linq_api_key)
    application.include_router(
        create_webhook_router(
            handle_message,
            linq_client,
            webhook_secret=settings.linq_webhook_secret,
        ),
        prefix="/webhooks",
    )
    application.include_router(
        create_terac_webhook_router(
            linq_client,
            webhook_secret=settings.terac_webhook_secret,
        ),
        prefix="/webhooks",
    )
    return application


app = create_app()

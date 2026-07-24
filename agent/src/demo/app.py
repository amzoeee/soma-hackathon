"""FastAPI app shell for the first-test demo."""

from fastapi import FastAPI

app = FastAPI(title="Soma First Test Demo")


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


def create_app() -> FastAPI:
    # Agent 2 mounts: app.include_router(create_webhook_router(...), prefix="/webhooks")
    return app

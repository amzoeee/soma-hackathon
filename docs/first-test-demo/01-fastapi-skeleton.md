# 01 — FastAPI Skeleton & Config

**Agent role:** Bootstrap the demo package so other agents have a place to land.

**Parallel:** Yes — run alongside Agents 2, 3, and 4.

**Depends on:** [00-shared-contracts.md](./00-shared-contracts.md)

## Owns (only these)

- `agent/src/demo/__init__.py`
- `agent/src/demo/config.py`
- `agent/src/demo/app.py`
- `agent/requirements.txt` (add demo deps; do not remove existing ones)
- `agent/.env.example`

## Must not touch

- `agent/src/linq/**`
- `agent/src/demo/linq_client.py`, `webhook.py`, `llm.py`, `prompts.py`, `handler.py`, `main.py`, `tools/**`

## Goal

Create a runnable FastAPI app shell with typed settings. Other agents will mount routers and wire handlers into this app.

## Requirements

### `config.py`

- Load settings from environment (pydantic-settings preferred).
- Fields matching the shared env table: `linq_api_key`, `linq_webhook_secret`, `runware_api_key`, `runware_base_url`, `runware_model`, `public_base_url`.
- Sensible defaults for `runware_base_url` and `runware_model` where documented; secrets default to empty string.
- Export a `get_settings()` function (lru_cache ok).

### `app.py`

- Create `app = FastAPI(title="Soma First Test Demo")`.
- Provide `create_app()` that returns the app.
- Leave a clear mount point / comment for Agent 2's webhook router, e.g. include a no-op or optional import so the file stays valid if webhook is missing:

```python
# Agent 2 mounts: app.include_router(create_webhook_router(...), prefix="/webhooks")
```

- Add `GET /health` → `{"ok": true}`.

### `requirements.txt`

Add (keep existing langgraph/anthropic lines):

- `fastapi`
- `uvicorn[standard]`
- `httpx`
- `pydantic`
- `pydantic-settings`
- `openai` (or httpx-only OpenAI-compatible client — Agent 3 will use it; include the package here)

### `.env.example`

Document every env var from the contracts with empty placeholders and short comments.

## Acceptance

- `python -c "from demo.config import get_settings; get_settings()"` works when `PYTHONPATH=agent/src`.
- `uvicorn demo.app:app` (or `create_app`) serves `GET /health`.
- No Linq, LLM, or robot logic in these files.

## Out of scope

Webhook parsing, LLM calls, tool execution, ngrok, `main.py`.

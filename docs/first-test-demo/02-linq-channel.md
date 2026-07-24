# 02 — Linq Channel (Webhook + Send)

**Agent role:** Receive iMessages from Linq and send replies back to the same conversation.

**Parallel:** Yes — run alongside Agents 1, 3, and 4.

**Depends on:** [00-shared-contracts.md](./00-shared-contracts.md)

## Owns (only these)

- `agent/src/demo/linq_client.py`
- `agent/src/demo/webhook.py`

## Must not touch

- `agent/src/linq/**`
- `config.py`, `app.py`, `llm.py`, `prompts.py`, `handler.py`, `main.py`, `tools/**`, `requirements.txt`

## Goal

Implement the Linq ingress/egress layer behind a small FastAPI router. Accept a handler callback so Agent 5 can plug in orchestration without you depending on LLM code.

## Requirements

### Research

Use current Linq webhook and send-message API docs. If field names differ from the contracts, adapt parsing in `webhook.py` but still expose `InboundMessage` / `OutboundReply` as specified in contracts.

### `linq_client.py`

- `LinqClient` with `async def send_reply(self, reply: OutboundReply) -> None`.
- Use `httpx.AsyncClient`.
- Auth via `LINQ_API_KEY` (passed into the constructor, not read ad hoc inside methods).
- Raise clear exceptions on non-2xx responses; log request failures.

### `webhook.py`

- Define `InboundMessage` and `OutboundReply` dataclasses here **or** in a tiny shared module only if you must — prefer defining them in `linq_client.py` / `webhook.py` as agreed in contracts (put both dataclasses in `linq_client.py` and import from webhook if cleaner).
- `create_webhook_router(handle_message, linq_client) -> APIRouter`:
  - `handle_message` is `Callable[[InboundMessage], Awaitable[str]]`.
  - On webhook POST: parse body → `InboundMessage` → `reply_text = await handle_message(msg)` → `await linq_client.send_reply(OutboundReply(...))` → return `{"ok": true}`.
  - Verify webhook secret if `LINQ_WEBHOOK_SECRET` is set.
  - Ignore or no-op non-text / empty events without 500ing.
- Route path: `POST /linq` (full path becomes `/webhooks/linq` once Agent 1/5 mounts with prefix `/webhooks`).

### Local stub mode

If useful for Agent 5 before real Linq credentials exist, support a dry path that logs the outbound reply instead of HTTP posting when `api_key` is empty — document it in a module docstring.

## Acceptance

- Unit-testable parser: given a sample Linq JSON payload fixture in a docstring or `if __name__` demo, produces a valid `InboundMessage`.
- `send_reply` issues the correct HTTP call shape (assert with httpx mock or respx if you add a small test; otherwise a documented example is fine).
- Router does not import `llm` or `tools`.

## Out of scope

LLM interpretation, `move_robot`, mounting the router on the app, ngrok.

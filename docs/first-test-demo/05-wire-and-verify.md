# 05 — Wire Up & Verify

**Agent role:** Compose Agents 1–4 into one working demo and prove the Definition of Done.

**Parallel:** No — start after 1–4 have landed (or stub missing imports briefly, then merge).

**Depends on:** all other briefs + [00-shared-contracts.md](./00-shared-contracts.md)

## Owns (only these)

- `agent/src/demo/handler.py`
- `agent/src/demo/main.py`
- Light edits to `agent/src/demo/app.py` **only** to mount the webhook router and wire dependencies (coordinate with Agent 1's mount comment).
- `agent/README.md` — add a short "First test demo" run section (do not rewrite the whole file).

## Must not touch

- `agent/src/linq/**`
- Tool schemas, Linq client internals, LLM prompts (fix imports/wiring only)

## Goal

One inbound iMessage path:

```text
Linq webhook → handle_message → interpret_and_call_tools → move_robot print → reply text → Linq send
```

## Requirements

### `handler.py`

```python
async def handle_message(msg: InboundMessage) -> str:
    ...
```

- Call `interpret_and_call_tools(msg.text)`.
- Prefer the LLM's final assistant text as the reply.
- If the model returned no text but tools succeeded, fall back to the tool result `message` fields joined simply.
- Never raise into the webhook on expected failures — return a short error string for the operator.

### `app.py` wiring (minimal)

- Construct `LinqClient` from settings.
- `app.include_router(create_webhook_router(handle_message, linq_client), prefix="/webhooks")`.

### `main.py`

- Entrypoint: `uvicorn demo.app:app` (or `create_app`) on host `0.0.0.0` port `8000`.
- Log a reminder to expose the server with ngrok / a tunnel and point Linq at `https://<tunnel>/webhooks/linq`.

### Docs in `agent/README.md`

Document:

1. `pip install -r requirements.txt`
2. Copy `.env.example` → `.env` and fill keys
3. `cd agent && PYTHONPATH=src python -m demo.main` (or equivalent)
4. Start ngrok: `ngrok http 8000`
5. Configure Linq webhook to the public URL
6. Send test iMessages: forward, backward, left, right, stop

## Manual verification checklist

Mark each off against the Definition of Done:

- [ ] Real iMessage hits `POST /webhooks/linq`
- [ ] Luna selects `move_robot` with correct args
- [ ] `ROBOT: ...` line appears in service logs / stdout
- [ ] Confirmation returns in the same iMessage thread
- [ ] Forward, backward, left, right, and stop all work
- [ ] Unsupported request gets a polite refusal (no fake movement print)

## Acceptance

- Local `GET /health` works.
- With credentials + tunnel, the checklist above passes.
- Future swap note left in README: replace `tools/move_robot.py` body only; keep schema and webhook/LLM unchanged.

## Out of scope

Building a new LLM stack, redesigning tool schemas, robot team HTTP client (beyond a comment pointing at the swap).

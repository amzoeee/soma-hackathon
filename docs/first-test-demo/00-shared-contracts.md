# 00 — Shared Contracts

**Read this before coding.** Every parallel agent implements against these contracts. Do not invent alternate names, paths, schemas, or ownership.

Agents **1–4** may run in parallel. Agent **5** starts after 1–4 land.

## Ownership matrix

| Agent | Brief | Owns (only these) |
|---|---|---|
| 1 | [01-fastapi-skeleton.md](./01-fastapi-skeleton.md) | `demo/__init__.py`, `config.py`, `app.py`, `requirements.txt`, `.env.example` |
| 2 | [02-linq-channel.md](./02-linq-channel.md) | `linq_client.py`, `webhook.py` |
| 3 | [03-llm-runware.md](./03-llm-runware.md) | `llm.py`, `prompts.py` |
| 4 | [04-move-robot-tool.md](./04-move-robot-tool.md) | `tools/__init__.py`, `tools/move_robot.py` |
| 5 | [05-wire-and-verify.md](./05-wire-and-verify.md) | `handler.py`, `main.py`, mount wiring in `app.py`, demo section in `agent/README.md` |

**Do not modify** `agent/src/linq/` (existing LangGraph arm agent).

## Package layout

All demo code lives under `agent/src/demo/`.

```text
agent/
  requirements.txt          # Agent 1
  .env.example              # Agent 1
  README.md                 # Agent 5 (demo run section only)
  src/
    demo/
      __init__.py           # Agent 1
      config.py             # Agent 1
      app.py                # Agent 1 (+ Agent 5 mounts router)
      main.py               # Agent 5
      handler.py            # Agent 5
      linq_client.py        # Agent 2 — LinqClient + InboundMessage + OutboundReply
      webhook.py            # Agent 2 — FastAPI routes
      llm.py                # Agent 3
      prompts.py            # Agent 3
      tools/
        __init__.py         # Agent 4
        move_robot.py       # Agent 4
```

## Import direction

```text
webhook  →  linq_client (types + LinqClient)
webhook  →  handler     (callback injected by Agent 5; webhook must not import llm/tools)
handler  →  llm
llm      →  tools, prompts, config (optional)
app      →  webhook, linq_client, handler, config   (Agent 5 wiring)
main     →  app / uvicorn
```

Never create circular imports. Prefer dependency injection for the webhook ↔ handler link.

## Environment variables

| Name | Used by | Purpose |
|---|---|---|
| `LINQ_API_KEY` | Agent 2 | Bearer token for Linq Partner API |
| `LINQ_WEBHOOK_SECRET` | Agent 2 | Optional Standard Webhooks secret (`whsec_…`); verify if set |
| `RUNWARE_API_KEY` | Agent 3 | Runware / OpenAI-compatible auth |
| `RUNWARE_BASE_URL` | Agent 3 | OpenAI-compatible base URL |
| `RUNWARE_MODEL` | Agent 3 | Default `gpt-5.6-luna` (or current Runware model id) |
| `PUBLIC_BASE_URL` | Agent 5 | Public tunnel URL noted in logs / README for Linq webhook registration |

Settings field names in `config.py` are snake_case mirrors of the env names above (`linq_api_key`, …).

## HTTP routes

| Method | Path | Owner | Behavior |
|---|---|---|---|
| `GET` | `/health` | Agent 1 | `{"ok": true}` |
| `POST` | `/webhooks/linq` | Agent 2 router at `/linq`, mounted by Agent 5 with prefix `/webhooks` | Parse Linq event → handle → send reply |

Linq webhook subscription URL (after tunnel): `{PUBLIC_BASE_URL}/webhooks/linq?version=2026-02-03`

## Core types

### Where types live

Define **`InboundMessage`** and **`OutboundReply`** in `linq_client.py`. `webhook.py` and `handler.py` import them from there. Do not redefine elsewhere.

### Movement command (tool args)

```python
# direction is one of: "forward" | "backward" | "left" | "right" | "stop"
{
  "direction": str,
  "distance_meters": float | None,  # required for forward/backward; omit/null for turn/stop
  "angle_degrees": float | None,    # optional for left/right; default 90 if omitted
}
```

### Tool result

```python
{
  "ok": bool,
  "printed": str,   # exact ROBOT: line that was printed (empty string on soft failure)
  "message": str,   # human-readable confirmation or error for the operator reply
}
```

### Printed command format (exact)

```text
ROBOT: move forward 2m
ROBOT: move backward 1m
ROBOT: turn left 90deg
ROBOT: turn right 45deg
ROBOT: stop
```

Use meters without a space before `m`, and degrees without a space before `deg`.

### Inbound operator message (handler input)

```python
@dataclass
class InboundMessage:
    text: str
    conversation_id: str          # Linq chat id
    sender: str                   # sender handle, e.g. "+12025559876"
    message_id: str | None = None
    raw: dict | None = None
```

### Outbound reply (Linq send)

```python
@dataclass
class OutboundReply:
    conversation_id: str
    text: str
```

## Linq API mapping (Agent 2)

Use Linq Partner API **v3**, webhook version **`2026-02-03`**.

### Inbound — `message.received`

Parse only `event_type == "message.received"`. Ignore other events with HTTP 200 and no reply.

Map:

| `InboundMessage` field | Source (2026-02-03 payload) |
|---|---|
| `conversation_id` | `data.chat.id` |
| `sender` | `data.sender_handle.handle` |
| `message_id` | `data.id` |
| `text` | join `data.parts[*].value` where `type == "text"` (space-separated); empty → no-op 200 |
| `raw` | full parsed JSON body (optional but useful for debugging) |

If there is no text part, return `{"ok": true}` without calling the handler.

### Outbound — send reply

```http
POST https://api.linqapp.com/api/partner/v3/chats/{chatId}/messages
Authorization: Bearer {LINQ_API_KEY}
Content-Type: application/json

{
  "message": {
    "parts": [
      { "type": "text", "value": "<reply text>" }
    ]
  }
}
```

`chatId` = `OutboundReply.conversation_id`.

### Webhook signature

If `LINQ_WEBHOOK_SECRET` is non-empty, verify Standard Webhooks headers (`webhook-id`, `webhook-timestamp`, `webhook-signature`) against the raw body. Reject invalid signatures with `401`. If the secret is empty, skip verification (local stub mode).

### Send ownership (resolved)

**Webhook owns sending.** Flow:

1. Parse body → `InboundMessage`
2. `reply_text = await handle_message(msg)`
3. `await linq_client.send_reply(OutboundReply(conversation_id=msg.conversation_id, text=reply_text))`
4. Return `{"ok": true}`

`handle_message` must **not** call Linq itself.

## Public function contracts

### Agent 1 — `config.py`

```python
class Settings(BaseSettings):
    linq_api_key: str = ""
    linq_webhook_secret: str = ""
    runware_api_key: str = ""
    runware_base_url: str = ""       # sensible Runware default ok
    runware_model: str = "gpt-5.6-luna"
    public_base_url: str = ""

def get_settings() -> Settings: ...
```

### Agent 1 — `app.py`

```python
app = FastAPI(title="Soma First Test Demo")

def create_app() -> FastAPI: ...
# GET /health → {"ok": true}
# Leave a mount comment for Agent 5:
#   app.include_router(create_webhook_router(...), prefix="/webhooks")
```

### Agent 2 — `linq_client.py`

```python
@dataclass
class InboundMessage: ...

@dataclass
class OutboundReply: ...

class LinqClient:
    def __init__(self, api_key: str, base_url: str = "https://api.linqapp.com/api/partner/v3"): ...
    async def send_reply(self, reply: OutboundReply) -> None: ...
```

If `api_key` is empty, log the outbound reply and return (dry-run) instead of HTTP posting.

### Agent 2 — `webhook.py`

```python
def create_webhook_router(
    handle_message: Callable[[InboundMessage], Awaitable[str]],
    linq_client: LinqClient,
) -> APIRouter: ...
# POST /linq  (becomes /webhooks/linq when mounted with prefix="/webhooks")
```

Do not import `llm` or `tools` from this module.

### Agent 3 — `llm.py`

```python
async def interpret_and_call_tools(text: str) -> tuple[str, list[dict]]:
    """
    Send operator text to Runware GPT-5.6 Luna with the move_robot tool.
    Execute any requested tool calls via demo.tools.execute_tool.
    Return (final_assistant_text, tool_results).
    """
```

- Import tools only from `demo.tools` (`TOOLS`, `execute_tool`) — do not redefine the schema.
- Tool loop max 3 rounds.
- Log each tool name + arguments at INFO under logger `demo.llm`.

### Agent 4 — `tools/move_robot.py`

```python
MOVE_ROBOT_SCHEMA: dict  # OpenAI-compatible function tool schema below

def move_robot(
    direction: str,
    distance_meters: float | None = None,
    angle_degrees: float | None = None,
) -> dict:
    """Print the command and return the Tool result dict above."""
```

`MOVE_ROBOT_SCHEMA` must match:

```python
{
  "type": "function",
  "function": {
    "name": "move_robot",
    "description": "Move or stop the robot. Use for forward/backward distance moves, left/right turns, or stop.",
    "parameters": {
      "type": "object",
      "properties": {
        "direction": {
          "type": "string",
          "enum": ["forward", "backward", "left", "right", "stop"],
        },
        "distance_meters": {"type": "number"},
        "angle_degrees": {"type": "number"},
      },
      "required": ["direction"],
      "additionalProperties": False,
    },
  },
}
```

Validation rules:

| `direction` | Required args | Default |
|---|---|---|
| `forward` / `backward` | `distance_meters` > 0 | — |
| `left` / `right` | optional `angle_degrees` | `90` |
| `stop` | none | — |

Invalid input → return `ok=False` with explanatory `message`; do not raise.

### Agent 4 — `tools/__init__.py`

```python
TOOLS: list[dict] = [MOVE_ROBOT_SCHEMA]

def execute_tool(name: str, arguments: dict | str) -> dict:
    # Normalize JSON string → dict if needed
    ...
```

### Agent 5 — `handler.py`

```python
async def handle_message(msg: InboundMessage) -> str:
    """LLM → tools → confirmation string. Does not talk to Linq itself."""
```

Prefer the LLM's final assistant text. If tools succeeded with empty assistant text, join tool `message` fields. On expected failures, return a short operator-facing error string — never raise into the webhook.

### Agent 5 — `main.py`

- Run uvicorn on `0.0.0.0:8000` serving `demo.app:app` (or `create_app()`).
- Log that Linq should point at `{PUBLIC_BASE_URL}/webhooks/linq`.

## End-to-end example

```text
Operator iMessage: Move forward 2 meters
  → Linq POST /webhooks/linq  (message.received)
  → InboundMessage(text="Move forward 2 meters", conversation_id=<chat id>, ...)
  → interpret_and_call_tools(...)
  → execute_tool("move_robot", {"direction": "forward", "distance_meters": 2})
  → stdout/log: ROBOT: move forward 2m
  → reply text ≈ "Moving forward 2 meters"
  → POST /v3/chats/{chatId}/messages
```

## Stack (allowed)

- Linq for receiving and sending iMessages
- FastAPI and Uvicorn
- Runware's OpenAI-compatible API
- GPT-5.6 Luna for command interpretation and tool selection
- Pydantic for command validation
- HTTPX for Linq and future robot API calls
- ngrok or another tunnel for local webhook exposure

**Not allowed for this demo:** LangGraph, LangChain, database, job queue.

## Initial scope

Supported requests:

- Move forward or backward by a requested distance
- Turn left or right
- Stop
- Report an unknown or unsupported request (LLM refuses; no tool call / no `ROBOT:` print)

The temporary `move_robot` tool only prints the intended command and returns a simulated successful result. Keep its interface stable so it can later be replaced with the robot team's Python function or HTTP API without changing Linq or LLM code.

## Conflict rules

1. Only edit files listed in your brief's **Owns** section (plus creating empty `__init__.py` if needed). Agent 5 may lightly edit `app.py` only to mount the webhook router.
2. If you need a symbol another agent owns, import it — do not reimplement it in your file.
3. Prefer async HTTP (`httpx.AsyncClient`) and async FastAPI handlers.
4. Log clearly with a `demo.` logger namespace (`demo.webhook`, `demo.llm`, `demo.tools`, `demo.handler`, …).
5. When temporarily developing against a missing sibling module, use a stub or clear ImportError — remove stubs before merge.

# 00 — Shared Contracts

**Read this before coding.** Every parallel agent implements against these contracts. Do not invent alternate names, paths, or schemas.

## Package layout

All demo code lives under `agent/src/demo/`. Do not modify `agent/src/linq/` (existing LangGraph arm agent).

```text
agent/
  requirements.txt
  .env.example
  src/
    demo/
      __init__.py
      config.py          # Agent 1
      app.py             # Agent 1 — FastAPI instance + router mount
      main.py            # Agent 5 — uvicorn entry
      handler.py         # Agent 5 — one inbound message → reply
      linq_client.py     # Agent 2
      webhook.py         # Agent 2 — FastAPI routes
      llm.py             # Agent 3
      prompts.py         # Agent 3
      tools/
        __init__.py      # Agent 4
        move_robot.py    # Agent 4
```

## Environment variables

| Name | Used by | Purpose |
|---|---|---|
| `LINQ_API_KEY` | Agent 2 | Linq API auth |
| `LINQ_WEBHOOK_SECRET` | Agent 2 | Optional webhook verification |
| `RUNWARE_API_KEY` | Agent 3 | Runware / OpenAI-compatible auth |
| `RUNWARE_BASE_URL` | Agent 3 | OpenAI-compatible base URL |
| `RUNWARE_MODEL` | Agent 3 | Default `gpt-5.6-luna` or whatever Runware documents |
| `PUBLIC_BASE_URL` | Agent 5 | Public tunnel URL for Linq webhook registration notes |

## Core types

Agents may import these from each other once files exist. Until then, copy the signatures exactly.

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
  "printed": str,   # e.g. "ROBOT: move forward 2m"
  "message": str,   # human-readable confirmation for the operator reply
}
```

### Inbound operator message (handler input)

```python
@dataclass
class InboundMessage:
    text: str
    conversation_id: str
    sender: str
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

## Public function contracts

### Agent 2 — `linq_client.py`

```python
class LinqClient:
    def __init__(self, api_key: str, ...): ...
    async def send_reply(self, reply: OutboundReply) -> None: ...
```

### Agent 2 — `webhook.py`

```python
router = APIRouter()

# POST endpoint that:
# 1. Parses Linq webhook payload into InboundMessage
# 2. Calls the injected handler: await handle_message(msg) -> str
# 3. Sends the reply via LinqClient (or returns 200 and lets handler send — pick one; prefer handler sends)
```

Expose:

```python
def create_webhook_router(handle_message, linq_client) -> APIRouter: ...
```

### Agent 3 — `llm.py`

```python
async def interpret_and_call_tools(text: str) -> tuple[str, list[dict]]:
    """
    Send operator text to Runware GPT-5.6 Luna with the move_robot tool.
    Execute any requested tool calls via the registered tool functions.
    Return (final_assistant_text, tool_results).
    """
```

Register tools by importing `TOOLS` / `execute_tool` from `demo.tools`.

### Agent 4 — `tools/move_robot.py`

```python
MOVE_ROBOT_SCHEMA: dict  # OpenAI-compatible function tool schema

def move_robot(
    direction: str,
    distance_meters: float | None = None,
    angle_degrees: float | None = None,
) -> dict:
    """Print the command and return the Tool result dict above."""
```

### Agent 4 — `tools/__init__.py`

```python
TOOLS: list[dict]           # schemas for the LLM
def execute_tool(name: str, arguments: dict) -> dict: ...
```

### Agent 5 — `handler.py`

```python
async def handle_message(msg: InboundMessage) -> str:
    """LLM → tools → confirmation string. Does not talk to Linq itself."""
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
- Report an unknown or unsupported request

The temporary `move_robot` tool only prints the intended command and returns a simulated successful result. Keep its interface stable so it can later be replaced with the robot team's Python function or HTTP API.

## Conflict rules

1. Only edit files listed in your brief's **Owns** section (plus creating empty `__init__.py` if needed).
2. If you need a symbol another agent owns, import it — do not reimplement it in your file.
3. Prefer async HTTP (httpx.AsyncClient) and async FastAPI handlers.
4. Log clearly with a `demo.` logger namespace.

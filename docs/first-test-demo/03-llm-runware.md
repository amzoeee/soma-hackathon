# 03 — Runware LLM (GPT-5.6 Luna)

**Agent role:** Turn operator natural language into `move_robot` tool calls via Runware's OpenAI-compatible API.

**Parallel:** Yes — run alongside Agents 1, 2, and 4.

**Depends on:** [00-shared-contracts.md](./00-shared-contracts.md)

## Owns (only these)

- `agent/src/demo/llm.py`
- `agent/src/demo/prompts.py`

## Must not touch

- `agent/src/linq/**`
- `config.py`, `app.py`, `linq_client.py`, `webhook.py`, `handler.py`, `main.py`, `tools/**`, `requirements.txt`

## Goal

Implement one async function that: sends the operator text to the model with the `move_robot` tool schema, executes any tool calls through `demo.tools.execute_tool`, and returns a final natural-language confirmation plus tool results.

## Requirements

### `prompts.py`

- System prompt that:
  - Restricts the agent to movement commands in scope (forward, backward, left, right, stop).
  - Instructs the model to call `move_robot` when appropriate.
  - Instructs a short plain-language confirmation after tools run.
  - Tells the model to say it cannot help for unsupported requests (no tool call).

### `llm.py`

```python
async def interpret_and_call_tools(text: str) -> tuple[str, list[dict]]:
    ...
```

- Use Runware OpenAI-compatible chat completions (official `openai` client pointed at `RUNWARE_BASE_URL` is fine).
- Read `RUNWARE_API_KEY`, `RUNWARE_BASE_URL`, `RUNWARE_MODEL` from env or accept an optional settings object — do not edit `config.py`; importing `get_settings` from `demo.config` is allowed once Agent 1 lands. Until then, `os.environ` is fine.
- Pass tools from `from demo.tools import TOOLS, execute_tool`.
- Run a simple tool loop (max 3 rounds): if the model returns `tool_calls`, execute each, append tool results, call again until a normal text response.
- Return `(assistant_text, tool_results)` where `tool_results` is the list of dicts returned by `execute_tool`.
- Log each tool call name + arguments at INFO.

### Tool schema source of truth

Do **not** redefine the `move_robot` JSON schema in `llm.py`. Always use `TOOLS` from Agent 4's package so the schema stays single-sourced.

If `demo.tools` is not importable yet while you develop, create a temporary local fallback schema identical to the contracts and leave a `# TODO: remove fallback when tools package lands` comment — prefer failing import with a clear error if you want strictness.

## Acceptance

- Calling `interpret_and_call_tools("Move forward 2 meters")` with a real API key produces a `move_robot` call with `direction="forward"` and `distance_meters=2` (manual check ok).
- Unsupported text like `"What's the weather?"` returns a polite refusal and empty / no successful movement tool results.
- No FastAPI or Linq imports.

## Out of scope

Webhook routes, printing robot commands (Agent 4), sending iMessage replies, `handler.py`.

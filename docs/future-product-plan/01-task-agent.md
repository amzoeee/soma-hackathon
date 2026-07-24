# 01 — Task Agent (Goal → Tools)

**Agent role:** Turn high-level iMessage goals into multi-step tool sequences and track task status through success, failure, or escalation.

**Parallel:** Yes — run alongside Agents 2, 3, and 4.

**Depends on:** [00-shared-contracts.md](./00-shared-contracts.md)

## Owns (only these)

- `agent/src/demo/task_agent.py`
- `agent/src/demo/prompts.py` (extend system prompt for multi-step pick-and-deliver; keep movement rules from first demo)

## Must not touch

- `agent/src/linq/**`
- `tools/**`, `control/**`, `recovery/**`, `linq_client.py`, `webhook.py`, `app.py`, `main.py`, `config.py`
- Prefer not editing `handler.py` / `llm.py` — Agent 5 wires `run_task` into the handler. You may lightly extend `llm.py` only if a new public helper is required and you document it for Agent 5; avoid conflicting with first-demo `interpret_and_call_tools`.

## Goal

Given a natural-language goal such as “Pick up the red box and deliver it to station B,” Luna selects and sequences autonomy tools until the task completes, fails, or needs a human.

## Requirements

### `prompts.py`

Extend the system prompt so the model:

- Understands multi-step object delivery (find → navigate/approach → pick → navigate → drop).
- Prefers the shared tool set: `navigate_to`, `find_object`, `pick_object`, `drop_object`, `get_robot_status`, `move_robot`, `stop_robot`, `request_human_assistance`.
- Calls `request_human_assistance` when a tool result has `needs_human=True` or when stuck.
- Keeps replies short and operator-facing for iMessage.
- Refuses unrelated requests without fake tool calls.

### `task_agent.py`

```python
@dataclass
class TaskResult:
    ok: bool
    status: Literal["completed", "escalated", "failed", "stopped"]
    message: str
    steps: list[dict]

async def run_task(goal: str) -> TaskResult:
    ...
```

Behavior:

1. Read `get_arbiter().mode()`; if not `AUTONOMOUS` / `RESUMING`, return `failed` or wait policy documented in code comments (do not fight `HUMAN_CONTROL`).
2. Run an LLM tool loop (reuse patterns from `llm.py` / Runware) with max rounds high enough for a pick-and-deliver (e.g. 8–12).
3. Execute tools only via `demo.tools.execute_tool`.
4. Append each tool name, args, and result summary to `steps`.
5. If any result has `needs_human=True`, ensure assistance is requested (tool call or direct import of the assistance tool), then return `status="escalated"`.
6. On clean completion, return `status="completed"` with a short success message.
7. Never raise into the webhook on expected failures — encode them in `TaskResult`.

## Acceptance

- `run_task("Pick up the red box and deliver it to station B")` produces a plausible tool sequence against simulated tools.
- Escalation path returns `status="escalated"` when a tool sets `needs_human=True`.
- No direct robot serial/camera I/O from this module.

## Out of scope

Implementing tool bodies, control arbiter internals, teleop, Linq webhook wiring, failure-injection flags.

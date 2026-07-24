# 03 — Human Recovery (Escalate + Teleop)

**Agent role:** When autonomy fails, notify a remote operator, put robot video on AR glasses, and hand arm/gripper control to the existing hand-tracking teleop pipeline.

**Parallel:** Yes — run alongside Agents 1, 2, and 4.

**Depends on:** [00-shared-contracts.md](./00-shared-contracts.md)

## Owns (only these)

- `agent/src/demo/tools/request_human_assistance.py`
- `agent/src/demo/recovery/__init__.py`
- `agent/src/demo/recovery/notify.py`
- `agent/src/demo/recovery/teleop_bridge.py`
- `agent/src/demo/recovery/camera_stream.py`
- Optional thin adapters under `robot/` **only** if needed to expose start/stop/stream hooks without rewriting the teleop main loop — keep changes minimal and documented

## Must not touch

- Autonomy tool bodies (`navigate.py`, `pick_object.py`, etc.)
- `control/**` internals (import arbiter only)
- `task_agent.py`, `llm.py`, `prompts.py`, `handler.py` (except what Agent 5 owns)
- `agent/src/linq/**` LangGraph pipeline
- Large refactors of `robot/src/main.py` teleop architecture

## Goal

Implement the recovery half of the product differentiator:

```text
failure → notify operator → AR video → hand-tracking control → resume signal
```

## Requirements

### `request_human_assistance.py`

```python
REQUEST_HUMAN_ASSISTANCE_SCHEMA: dict

def request_human_assistance(reason: str, task_summary: str | None = None) -> dict:
    ...
```

- Schema name: `request_human_assistance`.
- Call into `recovery.escalate_to_human` (sync wrapper around async is ok if you document it; prefer async end-to-end if the tool executor can await — match `execute_tool` style used by Agent 2; if tools are sync, run a small async helper safely).
- Return common tool result with `ok=True` when escalation started, `needs_human=True`.

### `recovery/notify.py`

- Send an iMessage (or dry-run log) via existing `LinqClient` patterns: include reason, task summary, and that teleop is requested.
- Use `OPERATOR_IMESSAGE_HANDLE` / conversation id from settings if present; otherwise log clearly.
- Do not own webhook receiving — outbound notify only.

### `recovery/camera_stream.py`

- Ensure the operator-facing camera path is ready (Xreal Eye / overlay path used by `robot/`).
- In dry-run / missing hardware, log `CAMERA_STREAM: ready (simulated)` and return success.
- Do not block forever waiting for hardware in unit-testable paths.

### `recovery/teleop_bridge.py`

```python
async def start_teleop() -> None: ...
async def stop_teleop_and_resume() -> None: ...
```

- `start_teleop`: after arbiter is in `HUMAN_CONTROL`, enable the existing hand-tracking → arm command path. If `TELEOP_ENABLED` is false, log dry-run steps only.
- While teleop is active, autonomy tools must be rejected by the arbiter (Agent 4) — you call `enter_human_control()` via the escalation flow.
- `stop_teleop_and_resume`: stop sending teleop commands, then `begin_resume()` / coordinate return to autonomous (exact arbiter calls per contracts).
- Provide a simple way for Agent 5 / operator to signal “human done” (function call, env flag, or stdin/CLI hook — document the chosen trigger).

### Escalation flow helper

```python
async def escalate_to_human(reason: str, task_summary: str | None = None) -> dict:
    # 1. arbiter.begin_escalation(reason)
    # 2. notify operator via Linq
    # 3. camera_stream ready
    # 4. arbiter.enter_human_control()
    # 5. start_teleop()
    # 6. return ok result
```

## Acceptance

- `request_human_assistance(reason="grasp failed")` notifies (or dry-runs), transitions toward human control when arbiter is present, and returns `needs_human=True`.
- Teleop bridge does not send arm commands when mode is `AUTONOMOUS`.
- Missing hardware still yields a deterministic simulated success path for demos.

## Out of scope

Implementing `pick_object` failure injection, LLM prompt text, mode enum definition, multi-step task planning, full E2E handler.

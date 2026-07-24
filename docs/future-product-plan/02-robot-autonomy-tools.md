# 02 — Robot Autonomy Tools

**Agent role:** Provide the stable high-level robot tool surface (simulated first) that the task agent calls for navigation, perception, and manipulation.

**Parallel:** Yes — run alongside Agents 1, 3, and 4.

**Depends on:** [00-shared-contracts.md](./00-shared-contracts.md)

## Owns (only these)

- `agent/src/demo/tools/navigate.py`
- `agent/src/demo/tools/find_object.py`
- `agent/src/demo/tools/pick_object.py`
- `agent/src/demo/tools/drop_object.py`
- `agent/src/demo/tools/robot_status.py`
- `agent/src/demo/tools/stop_robot.py`
- `agent/src/demo/tools/move_robot.py` (keep existing schema; may add arbiter guard)
- `agent/src/demo/tools/__init__.py` (registry + `execute_tool`)

## Must not touch

- `request_human_assistance.py` (Agent 3) — import and register only
- `control/**` internals (import `get_arbiter` / `assert_can_command` only)
- `recovery/**`, `task_agent.py`, `handler.py`, `llm.py`, `agent/src/linq/**`
- Do not rewrite the teleop pipeline under `robot/`

## Goal

Ship tool schemas and simulated implementations whose **names and return shapes stay stable** so robot-team APIs can replace the bodies later without changing Linq or the LLM.

## Requirements

### Every autonomy tool

1. Export `*_SCHEMA` (OpenAI-compatible function tool).
2. Implement a function returning the common result shape:

```python
{"ok": bool, "message": str, "data": dict | None, "needs_human": bool}
```

3. Before any simulated or real motion, call `get_arbiter().assert_can_command("agent")`. If control is missing during parallel work, guard behind a try/import and document the dependency.
4. Log under `demo.tools` with the tool name and args.
5. Leave a short `# FUTURE: call robot team API` comment at the swap point.

### Tool behavior (simulation defaults)

| Tool | Success simulation | Failure / notes |
|---|---|---|
| `navigate_to` | Accept `location` or `x,y[,theta]`; log destination; `ok=True` | Invalid args → `ok=False`, `needs_human=False` |
| `find_object` | Return `data={"object_id": "...", "description": ...}` | Unknown/empty description → soft fail |
| `pick_object` | Mark holding object in an in-memory module-level state | If `DEMO_SIMULATE_PICK_FAILURE` is truthy on **first** call in-process, return `ok=False`, `needs_human=True`, message about grasp failure |
| `drop_object` | Clear holding state | Fail if not holding |
| `get_robot_status` | Include mode (from arbiter if available), holding, last location | Always `ok=True` unless arbiter missing |
| `stop_robot` | Log stop; `ok=True` | — |
| `move_robot` | Keep first-demo print format; add `needs_human=False` to result for consistency (adapt carefully so first demo still works — prefer additive fields) |

### In-memory robot state

Keep a tiny private state object in `tools/` (e.g. `_state.py` owned by Agent 2) for: last pose/location, holding object id/description, failure-injection counter. Do not put this in `control/`.

### `__init__.py`

```python
TOOLS: list[dict] = [
    # move_robot, navigate_to, find_object, pick_object,
    # drop_object, get_robot_status, stop_robot,
    # request_human_assistance (imported from Agent 3 module)
]

def execute_tool(name: str, arguments: dict | str) -> dict:
    ...
```

If `request_human_assistance` is not importable yet, omit it from `TOOLS` or register a temporary stub — remove stub before merge.

## Acceptance

```python
from demo.tools import execute_tool
execute_tool("find_object", {"description": "red box"})
# ok=True, data contains object_id

execute_tool("pick_object", {"description": "red box"})
# ok=True normally; with DEMO_SIMULATE_PICK_FAILURE=1 → needs_human=True
```

- All schemas importable via `TOOLS`.
- No network I/O required for simulation path.

## Out of scope

LLM prompts, Linq escalation copy, teleop start/stop, mode state machine implementation, end-to-end handler wiring.

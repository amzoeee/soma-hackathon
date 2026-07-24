# 00 — Shared Contracts

**Read this before coding.** Every parallel agent implements against these contracts. Do not invent alternate names, paths, schemas, or ownership.

Agents **1–4** may run in parallel. Agent **5** starts after 1–4 land.

## Ownership matrix

| Agent | Brief | Owns (only these) |
|---|---|---|
| 1 | [01-task-agent.md](./01-task-agent.md) | `agent/src/demo/task_agent.py`, `agent/src/demo/prompts.py` (extend), task-loop pieces of `handler.py` only if Agent 5 has not landed yet — prefer leaving `handler.py` to Agent 5 |
| 2 | [02-robot-autonomy-tools.md](./02-robot-autonomy-tools.md) | `agent/src/demo/tools/**` except `request_human_assistance.py`; tool registry updates in `tools/__init__.py` |
| 3 | [03-human-recovery.md](./03-human-recovery.md) | `agent/src/demo/tools/request_human_assistance.py`, `agent/src/demo/recovery/**`, thin bridge into `robot/` teleop start/stop + camera stream hooks |
| 4 | [04-control-modes.md](./04-control-modes.md) | `agent/src/demo/control/**` (mode enum, arbiter, guards) |
| 5 | [05-wire-and-demo.md](./05-wire-and-demo.md) | `handler.py` / `main.py` wiring, failure-injection flag, demo README section, end-to-end verification |

**Do not modify** `agent/src/linq/` (existing LangGraph arm agent) unless a brief explicitly requires it.

Reuse the first-test-demo package under `agent/src/demo/` (Linq webhook, Runware LLM, config, app). Extend it; do not fork a second FastAPI service.

## Package layout

```text
agent/src/demo/
  config.py                 # existing (Agent 1 from first demo) — extend env only via Agent 5 if needed
  app.py / main.py          # Agent 5 wiring
  handler.py                # Agent 5
  linq_client.py / webhook.py
  llm.py / prompts.py       # Agent 1 extends prompts + task loop API
  task_agent.py             # Agent 1 — high-level goal → tool sequence
  control/
    __init__.py             # Agent 4
    modes.py                # Agent 4 — ControlMode enum + Arbiter
    guards.py               # Agent 4 — require_mode / claim_controller helpers
  recovery/
    __init__.py             # Agent 3
    notify.py               # Agent 3 — Linq escalation message
    teleop_bridge.py        # Agent 3 — start/stop teleop + stream readiness
    camera_stream.py        # Agent 3 — expose robot camera to AR glasses path
  tools/
    __init__.py             # Agent 2 owns registry; Agent 3 registers assistance tool via agreed export
    move_robot.py           # existing — keep schema; Agent 2 may extend
    navigate.py             # Agent 2
    find_object.py          # Agent 2
    pick_object.py          # Agent 2
    drop_object.py          # Agent 2
    robot_status.py         # Agent 2
    stop_robot.py           # Agent 2
    request_human_assistance.py  # Agent 3
```

## Import direction

```text
handler / task_agent  →  llm, tools, control, recovery
tools (autonomy)      →  control.guards   (check mode before commanding)
tools (assistance)    →  recovery, control
recovery              →  linq_client types, control, robot teleop hooks
control               →  (no imports from tools / recovery / task_agent)
llm                   →  tools, prompts
```

Never create circular imports. Control is the leaf dependency.

## Control modes

```text
Autonomous → Escalating → Human Control → Resuming → Autonomous
```

```python
class ControlMode(str, Enum):
    AUTONOMOUS = "autonomous"
    ESCALATING = "escalating"
    HUMAN_CONTROL = "human_control"
    RESUMING = "resuming"
```

Rules:

1. Only the **active controller** may send base/arm/gripper commands.
2. Autonomy tools require `AUTONOMOUS` or `RESUMING`.
3. Teleop bridge requires `HUMAN_CONTROL`.
4. `request_human_assistance` may run from `AUTONOMOUS` and transitions → `ESCALATING` → `HUMAN_CONTROL`.
5. Operator "done" / resume signal transitions `HUMAN_CONTROL` → `RESUMING` → `AUTONOMOUS`.

### Arbiter public API (Agent 4)

```python
class ControlArbiter:
    def mode(self) -> ControlMode: ...
    def active_controller(self) -> Literal["agent", "human", "none"]: ...
    def begin_escalation(self, reason: str) -> None: ...
    def enter_human_control(self) -> None: ...
    def begin_resume(self) -> None: ...
    def return_to_autonomous(self) -> None: ...
    def assert_can_command(self, controller: Literal["agent", "human"]) -> None:
        """Raise ControlConflictError if controller is not active."""
```

Singleton access: `get_arbiter() -> ControlArbiter`.

## Planned agent tools

Stable OpenAI-compatible function schemas. Simulated implementations are fine; swap bodies later without changing names or args.

| Tool | Owner | Purpose |
|---|---|---|
| `move_robot` | Agent 2 (existing) | Relative move / turn / stop |
| `navigate_to` | Agent 2 | Coordinates or named location |
| `find_object` | Agent 2 | Find object from description |
| `pick_object` | Agent 2 | Approach + grasp |
| `drop_object` | Agent 2 | Release at destination |
| `get_robot_status` | Agent 2 | Pose / task / mode / holding |
| `stop_robot` | Agent 2 | Immediate stop |
| `request_human_assistance` | Agent 3 | Escalate + pause autonomy |

### Common tool result shape

```python
{
  "ok": bool,
  "message": str,           # operator-facing status
  "data": dict | None,      # tool-specific payload
  "needs_human": bool,      # True when autonomy should escalate
}
```

Autonomy tools that fail recoverably set `ok=False` and `needs_human=True` when a human could unblock (e.g. grasp failure). Soft validation errors use `ok=False`, `needs_human=False`.

### Tool argument sketches

```python
# navigate_to
{"location": str | None, "x": float | None, "y": float | None, "theta": float | None}

# find_object
{"description": str}  # e.g. "red box"

# pick_object
{"description": str | None, "object_id": str | None}

# drop_object
{"location": str | None}  # default: current pose

# get_robot_status
{}  # no args

# stop_robot
{}

# request_human_assistance
{"reason": str, "task_summary": str | None}
```

Exact JSON schemas live in each tool module as `*_SCHEMA` and are aggregated in `tools/__init__.py` as `TOOLS`.

### `tools/__init__.py` registry contract

```python
TOOLS: list[dict]  # all schemas

def execute_tool(name: str, arguments: dict | str) -> dict:
    """Normalize JSON → dict, dispatch, return common result shape."""
```

Agent 2 owns the file but must call into Agent 3's `request_human_assistance` by importing it — do not reimplement. If the assistance module is missing during parallel work, register a stub that returns `ok=False` with a clear message and remove the stub before merge.

## Task agent contract (Agent 1)

```python
async def run_task(goal: str) -> TaskResult:
    """
    Interpret a high-level goal with Luna, call tools until done or escalation.
    Respect ControlArbiter modes. On tool needs_human, call request_human_assistance
    (or rely on Agent 5 wiring) and pause the autonomous loop.
    """

@dataclass
class TaskResult:
    ok: bool
    status: Literal["completed", "escalated", "failed", "stopped"]
    message: str
    steps: list[dict]
```

## Human recovery contract (Agent 3)

```python
async def escalate_to_human(reason: str, task_summary: str | None = None) -> dict:
    """Notify via Linq, ensure camera stream ready, enter human control."""

async def start_teleop() -> None:
    """Enable existing hand-tracking pipeline for arm + gripper."""

async def stop_teleop_and_resume() -> None:
    """Stop teleop command source; signal arbiter to resume autonomy."""
```

Camera path: reuse / hook `robot/` Eye camera + overlay so the operator sees the live feed on AR glasses. Prefer a bridge module over rewriting the teleop pipeline.

## Environment variables (additions)

| Name | Used by | Purpose |
|---|---|---|
| `DEMO_SIMULATE_PICK_FAILURE` | Agent 5 / Agent 2 | When `1`/`true`, first `pick_object` returns `needs_human=True` |
| `OPERATOR_IMESSAGE_HANDLE` | Agent 3 | Optional handle/chat for escalation notify |
| `TELEOP_ENABLED` | Agent 3 | Allow starting real teleop vs dry-run log |

Existing Linq / Runware vars from first-test-demo contracts remain unchanged.

## Stack

- Linq — iMessage task entry, progress, escalation
- FastAPI — webhook + orchestration
- Runware + GPT-5.6 Luna — intent + tool selection
- `agent/src/demo/tools` — stable high-level robot interface
- `robot/` — hand-tracking teleop, camera, arm controller (consumed by recovery bridge)
- Control arbiter — exclusive command ownership

Persistence / job queues are optional and **out of scope** for the first demonstration.

## Conflict rules

1. Only edit files listed in your brief's **Owns** section.
2. If you need a symbol another agent owns, import it — do not reimplement.
3. Autonomy tools and teleop must call `assert_can_command` before sending motion.
4. Keep tool **names and schemas** stable; swap simulation for real robot APIs later.
5. Prefer async APIs; log under `demo.` namespaces (`demo.task`, `demo.tools`, `demo.control`, `demo.recovery`).
6. When a sibling module is missing, stub with a clear ImportError path — remove stubs before merge.

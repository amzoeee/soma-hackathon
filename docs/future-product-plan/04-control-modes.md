# 04 — Control Modes Arbiter

**Agent role:** Own the control-mode state machine so only one controller (agent or human) can send robot motion commands at a time.

**Parallel:** Yes — run alongside Agents 1, 2, and 3.

**Depends on:** [00-shared-contracts.md](./00-shared-contracts.md)

## Owns (only these)

- `agent/src/demo/control/__init__.py`
- `agent/src/demo/control/modes.py`
- `agent/src/demo/control/guards.py`

## Must not touch

- `tools/**`, `recovery/**`, `task_agent.py`, `handler.py`, `llm.py`, `robot/**`
- Linq / FastAPI wiring

## Goal

Implement:

```text
Autonomous → Escalating → Human Control → Resuming → Autonomous
```

with exclusive command ownership.

## Requirements

### `modes.py`

```python
class ControlMode(str, Enum):
    AUTONOMOUS = "autonomous"
    ESCALATING = "escalating"
    HUMAN_CONTROL = "human_control"
    RESUMING = "resuming"

class ControlConflictError(RuntimeError):
    ...

class ControlArbiter:
    def mode(self) -> ControlMode: ...
    def active_controller(self) -> Literal["agent", "human", "none"]: ...
    def begin_escalation(self, reason: str) -> None: ...
    def enter_human_control(self) -> None: ...
    def begin_resume(self) -> None: ...
    def return_to_autonomous(self) -> None: ...
    def assert_can_command(self, controller: Literal["agent", "human"]) -> None: ...

def get_arbiter() -> ControlArbiter: ...
```

Transition rules:

| Call | From | To | `active_controller` |
|---|---|---|---|
| (initial) | — | `AUTONOMOUS` | `agent` |
| `begin_escalation` | `AUTONOMOUS` or `RESUMING` | `ESCALATING` | `none` |
| `enter_human_control` | `ESCALATING` | `HUMAN_CONTROL` | `human` |
| `begin_resume` | `HUMAN_CONTROL` | `RESUMING` | `agent` |
| `return_to_autonomous` | `RESUMING` | `AUTONOMOUS` | `agent` |

- Invalid transitions raise `ControlConflictError` (or a dedicated `InvalidTransitionError`); log the attempt.
- Store last escalation `reason` for status/debug (`last_escalation_reason` property is fine).
- Thread-safe enough for single-process asyncio (a `threading.Lock` or asyncio lock is enough; document choice).

### `assert_can_command`

- `controller="agent"` allowed in `AUTONOMOUS` and `RESUMING`.
- `controller="human"` allowed only in `HUMAN_CONTROL`.
- Otherwise raise `ControlConflictError` with current mode in the message.

### `guards.py`

Optional helpers for tools:

```python
def require_agent_control() -> None:
    get_arbiter().assert_can_command("agent")

def require_human_control() -> None:
    get_arbiter().assert_can_command("human")
```

### `__init__.py`

Re-export `ControlMode`, `ControlArbiter`, `ControlConflictError`, `get_arbiter`, and guard helpers.

## Acceptance

```python
from demo.control import get_arbiter, ControlMode
a = get_arbiter()
assert a.mode() == ControlMode.AUTONOMOUS
a.assert_can_command("agent")  # ok
a.begin_escalation("grasp failed")
a.enter_human_control()
a.assert_can_command("human")  # ok
# a.assert_can_command("agent")  # raises
a.begin_resume()
a.return_to_autonomous()
```

- No imports from tools/recovery (keep control a leaf).
- Unit-testable without hardware.

## Out of scope

Linq messages, teleop process management, tool schemas, task planning, demo failure flags.

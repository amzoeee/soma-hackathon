# 04 — Temporary `move_robot` Tool

**Agent role:** Provide the stable tool interface that prints simulated movement commands.

**Parallel:** Yes — run alongside Agents 1, 2, and 3.

**Depends on:** [00-shared-contracts.md](./00-shared-contracts.md)

## Owns (only these)

- `agent/src/demo/tools/__init__.py`
- `agent/src/demo/tools/move_robot.py`

## Must not touch

- Everything outside `agent/src/demo/tools/`

## Goal

Implement a temporary robot adapter whose **schema and return shape stay stable** so it can later be swapped for the robot team's real Python function or HTTP API without changing Linq or LLM code.

## Requirements

### Supported operations

| Operator intent | `direction` | Other args |
|---|---|---|
| Move forward N meters | `forward` | `distance_meters=N` |
| Move backward N meters | `backward` | `distance_meters=N` |
| Turn left | `left` | optional `angle_degrees` (default 90) |
| Turn right | `right` | optional `angle_degrees` (default 90) |
| Stop | `stop` | no distance/angle |

### `move_robot.py`

```python
MOVE_ROBOT_SCHEMA: dict

def move_robot(
    direction: str,
    distance_meters: float | None = None,
    angle_degrees: float | None = None,
) -> dict:
    ...
```

- Validate inputs with Pydantic (recommended) or explicit checks.
- On success, **print** a single clear line to stdout / logging, matching the demo style:

```text
ROBOT: move forward 2m
ROBOT: move backward 1m
ROBOT: turn left 90deg
ROBOT: turn right 45deg
ROBOT: stop
```

- Return:

```python
{
  "ok": True,
  "printed": "<same string as printed>",
  "message": "<operator-facing confirmation, e.g. 'Moving forward 2 meters'>",
}
```

- On invalid direction or missing required distance, return `ok=False` with an explanatory `message` — do not raise unless something is truly unexpected.
- Do **not** call any robot HTTP API yet. Leave a short comment marking the future swap point.

### `MOVE_ROBOT_SCHEMA`

OpenAI-compatible function tool object, e.g.:

```python
{
  "type": "function",
  "function": {
    "name": "move_robot",
    "description": "...",
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

### `tools/__init__.py`

```python
TOOLS = [MOVE_ROBOT_SCHEMA]

def execute_tool(name: str, arguments: dict) -> dict:
    if name == "move_robot":
        return move_robot(**arguments)
    return {"ok": False, "printed": "", "message": f"Unknown tool: {name}"}
```

Accept `arguments` as a dict (already parsed) or JSON string — normalize inside `execute_tool`.

## Acceptance

```python
from demo.tools import execute_tool
execute_tool("move_robot", {"direction": "forward", "distance_meters": 2})
# prints: ROBOT: move forward 2m
# returns ok=True with message suitable for iMessage
```

- Schema is importable as `TOOLS` for Agent 3.
- No network I/O.

## Out of scope

LLM client, Linq, FastAPI, handler wiring.

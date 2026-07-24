# Linq Robot Agent Demo

An operator sends a robot request through iMessage. Linq delivers it to the
service, Runware GPT-5.6 Luna converts the complete request into an ordered
list of explicit robot tool calls, the service executes those calls
sequentially, and Linq returns a deterministic result list.

```text
iMessage
  → Linq webhook
  → FastAPI service
  → one Runware planning call
  → ordered robot tool calls
  → deterministic result formatter
  → iMessage reply
```

The model never authors the outbound iMessage text.

## Tool contract

| Tool | Purpose |
|---|---|
| `move_cartesian` | Differential XYZ movement through IK (`+x` right, `+y` forward, `+z` up) |
| `move_wrist` | Differential wrist pitch and roll from `-160°` through `+160°` |
| `set_gripper` | Fully open or close the calibrated gripper |
| `hold_position` | Stop and hold the current pose |

One user message can produce multiple ordered calls. If a step fails, later
steps are not executed.

For retracing, the planner appends inverse Cartesian and wrist calls in reverse
order. Gripper state changes are only performed when explicitly requested.

## Example

```text
Operator:
Move up 100 cm, roll wrist right 90 degrees, open the gripper, move forward
20 cm, close the gripper, retrace to the original position, then open it.

Plan:
1. move_cartesian(0, 0, +1.0)
2. move_wrist(0, +90)
3. set_gripper(open)
4. move_cartesian(0, +0.2, 0)
5. set_gripper(closed)
6. move_cartesian(0, -0.2, 0)
7. move_wrist(0, -90)
8. move_cartesian(0, 0, -1.0)
9. set_gripper(open)
```

The hardware adapter applies safety and workspace limits. The deterministic
reply reports requested and applied values whenever they differ.

See [the setup runbook](./first-test-demo/setup-runbook.md) for environment,
service, LocalTunnel, and Linq webhook setup.

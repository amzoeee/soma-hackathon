# First Test Demo

Prove the complete messaging and AI tool-call stack before the robot team's movement API is ready.

An operator sends a basic movement request through iMessage. Linq delivers the message to our service, Runware-hosted GPT-5.6 Luna translates it into a robot tool call, and a temporary robot adapter prints the requested movement. The service then replies in the same iMessage conversation.

```text
iMessage
  → Linq webhook
  → FastAPI service
  → Runware GPT-5.6 Luna
  → Temporary move_robot tool
  → Printed movement command
  → Confirmation sent through Linq
```

Example:

```text
Operator: Move forward 2 meters
Tool call: move_robot(direction="forward", distance_meters=2)
Terminal: ROBOT: move forward 2m
Reply: Moving forward 2 meters
```

## Parallel agent briefs

Hand each brief to a different coding agent. Agents **1–4 can run at the same time**. Agent 5 starts after those land (or stubs the imports and merges last).

| Order | Brief | Owns | Parallel? |
|---|---|---|---|
| Shared | [00-shared-contracts.md](./first-test-demo/00-shared-contracts.md) | Interfaces only — read first | All agents read this |
| 1 | [01-fastapi-skeleton.md](./first-test-demo/01-fastapi-skeleton.md) | App shell, config, deps | Yes |
| 2 | [02-linq-channel.md](./first-test-demo/02-linq-channel.md) | Linq receive + send | Yes |
| 3 | [03-llm-runware.md](./first-test-demo/03-llm-runware.md) | GPT-5.6 Luna tool calling | Yes |
| 4 | [04-move-robot-tool.md](./first-test-demo/04-move-robot-tool.md) | Temporary `move_robot` printer | Yes |
| 5 | [05-wire-and-verify.md](./first-test-demo/05-wire-and-verify.md) | Handler, main, end-to-end DoD | After 1–4 |

## Setup and operation

Use the [setup runbook](./first-test-demo/setup-runbook.md) to initialize the
project from a fresh clone or resume an existing environment without repeating
completed steps. It covers credentials, the local service, LocalTunnel, Linq
webhook configuration, verification, and troubleshooting.

## Definition of Done

The test is complete when:

1. A real iMessage reaches the FastAPI webhook through Linq.
2. GPT-5.6 Luna selects the correct movement tool and arguments.
3. The simulated movement appears in the application logs.
4. A confirmation is returned to the same iMessage conversation.
5. Forward, backward, left, right, and stop all work.

## Next Integration Step

When the movement API becomes available, replace the temporary tool's printed response with a call to the robot API. The Linq webhook, LLM integration, and tool schema should remain unchanged.

LangGraph, LangChain, a database, and a job queue are not required for this test. Do not reuse or modify the existing LangGraph arm pipeline under `agent/src/linq/` for this demo.

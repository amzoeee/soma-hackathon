# Future Product Plan

In this architecture, **Terac** is the operator-facing task workflow built on
the existing Linq iMessage transport.

Build an autonomous factory robot that can receive high-level tasks, propose a
concrete execution plan for human approval, navigate through a workspace,
locate and manipulate objects, and ask a remote human operator for help when
autonomy fails.

The robot combines a mobile base, robotic arm, gripper, camera, AI agent, and remote AR teleoperation.

## Intended Experience

An operator assigns a task through iMessage, such as:

> Pick up the red box and deliver it to station B.

The AI agent interprets the goal and sends a step-by-step plan back through
Linq. An authorized human reviews the target, destination, route, actions, and
safety limits and explicitly approves or rejects that plan. Before approval,
the agent cannot call any motion or manipulation tool. After approval, the
robot navigates to the target, identifies it, attempts to pick it up, travels
to the destination, and releases it within the approved plan.

If navigation or manipulation fails, the robot pauses and notifies a remote operator. The operator uses AR glasses to see the robot's live camera feed and controls the robotic arm and gripper with their own hand movements. After resolving the problem, the operator returns control to the autonomous system so it can resume or complete the task.

## System Overview

```text
iMessage task
  → Linq
  → AI agent creates a bounded plan
  → Linq sends plan + approval ID
  → Human reviews and approves
  → Approval gate unlocks the exact plan
  → Autonomous robot tools
  → Mobile base, arm, and gripper

On failure:

Robot failure
  → AI agent pauses the task
  → Linq notifies a remote operator
  → Robot video appears on AR glasses
  → Hand tracking controls the arm and gripper
  → Operator resolves the problem
  → Control returns to the autonomous agent
```

## Parallel agent briefs

Hand each brief to a different coding agent. Agents **1–4 can run at the same time**. Agent 5 starts after those land (or stubs the imports and merges last).

| Order | Brief | Owns | Parallel? |
|---|---|---|---|
| Shared | [00-shared-contracts.md](./future-product-plan/00-shared-contracts.md) | Interfaces only — read first | All agents read this |
| 1 | [01-task-agent.md](./future-product-plan/01-task-agent.md) | Goal interpretation, task loop, tool selection | Yes |
| 2 | [02-robot-autonomy-tools.md](./future-product-plan/02-robot-autonomy-tools.md) | High-level robot tools (sim → real swap) | Yes |
| 3 | [03-human-recovery.md](./future-product-plan/03-human-recovery.md) | Escalation notify, AR stream, teleop handoff | Yes |
| 4 | [04-control-modes.md](./future-product-plan/04-control-modes.md) | Mode arbiter; exclusive command ownership | Yes |
| 5 | [05-wire-and-demo.md](./future-product-plan/05-wire-and-demo.md) | Failure-injection demo + end-to-end DoD | After 1–4 |

The existing briefs above remain unchanged. Pre-execution approval is a
separate feature layered onto the completed messaging and agent path:
[Terac human approval before robot execution](./features/terac-human-approval.md).

## Target End-to-End Demonstration

1. A user sends a request to move an object to a destination.
2. The agent returns a bounded plan and approval ID without calling the robot.
3. An authorized human reviews and approves that exact plan.
4. The approval gate unlocks autonomous navigation and manipulation.
5. The robot attempts the task and encounters a pickup failure.
6. The agent pauses and contacts a remote operator.
7. The operator sees the live robot video through AR glasses.
8. The operator uses hand tracking to control the arm and complete the pickup.
9. Control returns to the autonomous system under the original approved plan.
10. The robot completes the delivery and reports success.

This autonomous-to-human recovery loop is the central product differentiator.

## Definition of Done

The future product slice is complete when:

1. An iMessage goal produces a reviewable multi-step plan without robot calls.
2. Only an authorized, conversation-bound, unexpired approval unlocks that
   exact plan, once.
3. Rejection, expiry, replay, or material plan changes never reach robot tools.
4. Simulated (or real) robot tools cover move, navigate, find, pick, drop,
   status, and stop.
5. A forced pickup failure escalates to a remote operator via Linq.
6. Control mode transitions `Planning → Awaiting Approval → Autonomous →
   Escalating → Human Control → Resuming → Autonomous`.
7. Only the active controller can send arm/base commands during each mode.
8. After human recovery, autonomy resumes and reports delivery success.

## Relationship to First Test Demo

[First test demo](./first-test-demo.md) proves Linq → FastAPI → Luna →
`move_robot` print. The separate [Terac human-approval
feature](./features/terac-human-approval.md) inserts planning and approval
between Luna and robot execution without rewriting the completed demo plan.

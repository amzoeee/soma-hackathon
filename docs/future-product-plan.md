# Future Product Plan

## Product Vision

Build an autonomous factory robot that can receive high-level tasks, navigate through a workspace, locate and manipulate objects, and ask a remote human operator for help when autonomy fails.

The robot combines a mobile base, robotic arm, gripper, camera, AI agent, and remote AR teleoperation.

## Intended Experience

An operator assigns a task through iMessage, such as:

> Pick up the red box and deliver it to station B.

The AI agent interprets the goal and coordinates the robot's autonomous capabilities. The robot navigates to the target, identifies it, attempts to pick it up, travels to the destination, and releases it.

If navigation or manipulation fails, the robot pauses and notifies a remote operator. The operator uses AR glasses to see the robot's live camera feed and controls the robotic arm and gripper with their own hand movements. After resolving the problem, the operator returns control to the autonomous system so it can resume or complete the task.

## System Overview

```text
iMessage task
  → Linq
  → AI agent
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

## Major Capabilities

### Task Interface and Agent

- Receive goals and send status updates through iMessage and Linq
- Use Runware-hosted GPT-5.6 Luna to interpret goals and select high-level tools
- Track the current task and react to tool results
- Escalate failures to a human operator

### Autonomous Robot Operation

- Move relative to the robot's current position
- Navigate to coordinates or named locations
- Use the camera to find requested objects
- Approach and pick up objects with the arm and gripper
- Carry objects to a destination and release them
- Report success, failure, and current status

The robot team will implement the underlying navigation, perception, coordinate handling, and physical movement APIs. The AI agent will call these capabilities through stable, high-level tool interfaces.

### Human Recovery

- Notify an available operator when the robot cannot complete a task
- Stream the robot's live camera feed to the operator's AR glasses
- Transfer arm and gripper control to the hand-tracking teleoperation system
- Allow the operator to complete or recover the failed manipulation
- Return control to autonomous operation afterward

### Control Modes

The system will transition between:

```text
Autonomous → Escalating → Human Control → Resuming → Autonomous
```

Only the active controller should send movement commands during each mode.

## Planned Agent Tools

The eventual tool surface should cover capabilities such as:

- Move in a direction
- Navigate to coordinates or a named location
- Find an object from its description
- Approach and pick up an object
- Drop an object at a destination
- Read robot and task status
- Stop the robot
- Request human assistance

During early development, these tools can return simulated results. Each simulated implementation will later be replaced by the corresponding robot capability without changing the agent-facing interface.

## Core Stack

- Linq for iMessage task entry, progress messages, and escalation notifications
- FastAPI for webhook handling and orchestration
- Runware for LLM inference
- GPT-5.6 Luna for intent interpretation and high-level tool selection
- Robot-team APIs for navigation, perception, arm movement, and gripping
- Camera streaming to the AR glasses
- Existing hand-tracking teleoperation pipeline for manual arm and gripper control

Additional persistence or workflow infrastructure can be introduced when task duration and reliability requirements justify it; it is not required for the first demonstration.

## Target End-to-End Demonstration

The target demonstration is:

1. A user sends a request to move an object to a destination.
2. The agent invokes the robot's autonomous navigation and manipulation capabilities.
3. The robot attempts the task and encounters a pickup failure.
4. The agent pauses and contacts a remote operator.
5. The operator sees the live robot video through AR glasses.
6. The operator uses hand tracking to control the arm and complete the pickup.
7. Control returns to the autonomous system.
8. The robot completes the delivery and reports success.

This autonomous-to-human recovery loop is the central product differentiator.

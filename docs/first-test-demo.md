# First Test Demo

## Purpose

Prove the complete messaging and AI tool-call stack before the robot team's movement API is ready.

An operator sends a basic movement request through iMessage. Linq delivers the message to our service, Runware-hosted GPT-5.6 Luna translates it into a robot tool call, and a temporary robot adapter prints the requested movement. The service then replies in the same iMessage conversation.

## Demo Flow

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

## Initial Scope

The demo supports:

- Move forward or backward by a requested distance
- Turn left or right
- Stop
- Report an unknown or unsupported request

The temporary `move_robot` tool only prints the intended command and returns a simulated successful result. Its interface should be kept stable so its implementation can later be replaced with the robot team's Python function or HTTP API.

## Stack

- Linq for receiving and sending iMessages
- FastAPI and Uvicorn for the webhook service
- Runware's OpenAI-compatible API
- GPT-5.6 Luna for command interpretation and tool selection
- Pydantic for command validation
- HTTPX for Linq and future robot API calls
- ngrok or another tunnel to expose the local webhook during development

LangGraph, LangChain, a database, and a job queue are not required for this test.

## Definition of Done

The test is complete when:

1. A real iMessage reaches the FastAPI webhook through Linq.
2. GPT-5.6 Luna selects the correct movement tool and arguments.
3. The simulated movement appears in the application logs.
4. A confirmation is returned to the same iMessage conversation.
5. Forward, backward, left, right, and stop all work.

## Next Integration Step

When the movement API becomes available, replace the temporary tool's printed response with a call to the robot API. The Linq webhook, LLM integration, and tool schema should remain unchanged.

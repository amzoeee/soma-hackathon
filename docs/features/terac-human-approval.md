# Feature — Terac Human Approval Before Robot Execution

## Goal

Add a mandatory human review between agent planning and robot execution.
Terac uses the existing Linq webhook and reply path as its messaging transport.

```text
Operator sends task
  → Linq message.received webhook
  → Terac sends the task to the planning agent
  → Agent returns a reviewable plan without executing tools
  → Terac sends the plan and approval ID through Linq
  → Authorized human approves or rejects
  → Terac validates and consumes the approval
  → Agent executes the stored plan through robot tools
  → Terac sends progress and the final result through Linq
```

This feature changes runtime behavior, but it does not rewrite the completed
first-demo or future-product implementation briefs.

## Non-negotiable behavior

1. Planning cannot call `execute_tool` or any robot adapter.
2. The approval message must show the exact stored tool names, arguments, and
   safety-relevant units. Model-written prose alone is not sufficient.
3. Approval is bound to one plan digest, Linq conversation, authorized reviewer,
   expiration time, and approval ID.
4. The plan is consumed atomically before execution and can execute at most
   once, including when Linq retries a webhook.
5. Rejection, expiry, an unknown ID, a wrong conversation, an unauthorized
   sender, or a replay produces no robot call.
6. Execution uses the stored plan. The approval text is never sent back to the
   model for reinterpretation.
7. A material plan change pauses execution and creates a new approval request.
8. An empty reviewer allowlist fails closed.

## Step 0 — Add feature contracts and configuration

Create `agent/src/demo/approval.py` with immutable plan types:

```python
@dataclass(frozen=True)
class PlannedToolCall:
    name: str
    arguments: dict

@dataclass(frozen=True)
class TaskPlan:
    summary: str
    tool_calls: tuple[PlannedToolCall, ...]

@dataclass
class PendingApproval:
    approval_id: str
    conversation_id: str
    requested_by: str
    plan: TaskPlan
    plan_digest: str
    created_at: datetime
    expires_at: datetime
    status: Literal[
        "pending", "approved", "rejected", "expired", "executed", "failed"
    ]
```

Add settings to `agent/src/demo/config.py` and placeholders to
`agent/.env.example`:

```dotenv
APPROVER_HANDLES=
APPROVAL_TTL_SECONDS=900
```

Contract decisions:

- Normalize reviewer handles before comparison.
- Generate unpredictable, chat-safe approval IDs.
- Compute `plan_digest` from canonical JSON containing tool names and arguments.
- Render the approval action list deterministically from the same canonical
  data.
- Do not include credentials, webhook secrets, or private model reasoning in
  plans or audit logs.

Done when the types, digest function, deterministic renderer, and settings can
be imported without changing current webhook behavior.

## Step 1 — Add a plan-only agent path

Create `agent/src/demo/planning.py` rather than adding approval logic to the
existing tool-execution loop.

Public contract:

```python
async def propose_task_plan(text: str) -> TaskPlan:
    """Return a validated plan without executing any tool."""
```

Implementation requirements:

- Reuse `TOOLS` from `demo.tools` as the schema source of truth.
- Ask Luna for proposed tool calls, then parse and validate their JSON
  arguments.
- Do not import `execute_tool`.
- Do not perform the post-tool model round used by
  `interpret_and_call_tools`.
- Return no tool calls for unsupported or ambiguous requests.
- Phrase the summary as a proposal; never claim the robot moved.
- Reject plans containing unknown tools or invalid arguments.

Done when a request such as `move forward 2 meters` returns a `TaskPlan` for
`move_robot(direction="forward", distance_meters=2)` and produces no
`ROBOT:` output.

## Step 2 — Implement the pending-approval store

Implement an `ApprovalStore` in `approval.py`:

```python
class ApprovalStore:
    def create(
        self, message: InboundMessage, plan: TaskPlan
    ) -> PendingApproval: ...

    def reject(
        self, approval_id: str, message: InboundMessage
    ) -> PendingApproval: ...

    def consume(
        self, approval_id: str, message: InboundMessage
    ) -> PendingApproval: ...

    def mark_executed(self, approval_id: str) -> None: ...
    def mark_failed(self, approval_id: str) -> None: ...
```

For the local demo, a process-local dictionary protected by a lock is enough.
Keep it behind the interface so production can replace it with durable atomic
storage.

`consume` must check, in one critical section:

- pending status;
- expiration;
- normalized sender in `APPROVER_HANDLES`;
- matching `conversation_id`;
- matching stored digest;
- approval not previously consumed.

A new task in the same conversation supersedes any older pending plan. The old
approval ID must become permanently non-executable.

Done when unit tests cover approval, rejection, expiry, unauthorized sender,
wrong conversation, duplicate approval, and two concurrent consumes.

## Step 3 — Wire planning, review, and gated execution

Update `agent/src/demo/handler.py` to recognize three message types:

### New task

1. Call `propose_task_plan(msg.text)`.
2. Store the plan.
3. Return the deterministic action list and:

   ```text
   APPROVE <approval-id>
   REJECT <approval-id>
   ```

4. Do not call `execute_tool`.

### Approval

1. Parse the approval ID without using the model.
2. Call `ApprovalStore.consume`.
3. Execute only `pending.plan.tool_calls` through `demo.tools.execute_tool`.
4. Mark the plan executed or failed.
5. Return a concise result for the same Linq conversation.

### Rejection

1. Parse the rejection ID without using the model.
2. Mark the plan rejected.
3. Confirm cancellation without calling a tool.

Update `agent/src/demo/app.py` to construct and inject one store into the
message handler. Keep `webhook.py` transport-only; it should continue parsing,
deduplicating, invoking the handler, and sending the handler's reply.

If an approved execution needs an action outside the stored plan, stop before
that action and send a replacement plan with a new ID. Approval never transfers
between plans.

Done when there is no reachable normal path from a new task message to
`execute_tool` until `consume` succeeds.

## Step 4 — Verify the complete feature

Automated checks:

- A new task returns a plan and never calls the executor.
- The displayed action list matches the canonical plan used for the digest.
- Authorized approval executes the stored arguments exactly once.
- Approval text is not passed to Luna.
- Rejection, expiry, unknown ID, wrong chat, unauthorized sender, and replay do
  not call the executor.
- Duplicate Linq deliveries do not create duplicate plans or executions.
- A material change creates a new plan and ID.
- Execution failures are recorded and reported without reopening the approval.

Manual Linq test:

```text
Operator: Move forward 2 meters
Terac: Plan <id>: move_robot forward 2m.
       Reply APPROVE <id> or REJECT <id>.

# Confirm there is no ROBOT line yet.

Reviewer: APPROVE <id>
Service: ROBOT: move forward 2m
Terac: Plan <id> completed.
```

Then replay the approval and test a rejection. Neither should produce another
`ROBOT:` line.

## Production follow-up

The local in-memory store is only a demo boundary. Before real unattended robot
use, move pending plans and one-time consumption into durable transactional
storage and add an append-only audit trail containing:

- request and approval message IDs;
- requester and reviewer;
- conversation ID;
- canonical plan and digest;
- creation, approval, execution, and completion timestamps;
- every tool call and result;
- rejection, expiry, failure, and reapproval reasons.

Long-running robot work should execute outside the webhook request while
preserving the same approval record and idempotency key. The webhook should
acknowledge promptly, and Terac should send progress and completion messages
as separate Linq replies.

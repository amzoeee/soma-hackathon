# 05 — Wire Up & Recovery Demo

**Agent role:** Compose Agents 1–4 into one path that proves the autonomous → human recovery → autonomous loop.

**Parallel:** No — start after 1–4 have landed (or stub missing imports briefly, then merge).

**Depends on:** all other briefs + [00-shared-contracts.md](./00-shared-contracts.md)

## Owns (only these)

- `agent/src/demo/handler.py` (extend to call `run_task` for high-level goals; keep simple move path working if present)
- `agent/src/demo/main.py` (entrypoint reminders for demo flags)
- Light edits to `agent/src/demo/app.py` / `config.py` only for new env vars (`DEMO_SIMULATE_PICK_FAILURE`, `OPERATOR_IMESSAGE_HANDLE`, `TELEOP_ENABLED`)
- `agent/README.md` — add a “Future product recovery demo” section (do not rewrite the whole file)

## Must not touch

- Tool schema definitions (wire only)
- Control arbiter internals
- Teleop algorithm code under `robot/src/tracking`, `mapping`, `ik` (call bridge APIs only)
- `agent/src/linq/**` LangGraph agent

## Goal

Prove the target demonstration:

```text
iMessage goal
  → task agent + autonomy tools
  → forced pick failure
  → escalate + AR/teleop
  → human completes grasp
  → resume autonomy
  → drop / deliver + success reply
```

## Requirements

### Handler wiring

- Route operator text into `run_task(goal)` for multi-step goals.
- Map `TaskResult` into an iMessage reply string.
- If status is `escalated`, reply that a human operator has been notified; do not pretend the task finished.
- After human resume (document how: second iMessage “resume”, bridge callback, or demo CLI), allow a follow-up `run_task` or continuation that finishes drop/delivery — pick one approach and document it in README.

### Failure injection

- Document setting `DEMO_SIMULATE_PICK_FAILURE=1` so the first `pick_object` fails with `needs_human=True`.
- Happy-path without the flag should complete without escalation when tools are simulated successes.

### README demo section

Document:

1. Env vars for Linq, Runware, failure injection, teleop dry-run.
2. How to run the service + tunnel.
3. Example iMessage goal for pick-and-deliver.
4. What logs to expect at each mode transition.
5. How the operator finishes teleop and returns control.
6. Note: swap simulated tool bodies for robot-team APIs without changing schemas.

## Manual verification checklist

- [ ] Goal message starts an autonomous tool sequence
- [ ] With pick failure flag, escalation notify fires (or dry-runs)
- [ ] Mode transitions through Escalating → Human Control
- [ ] Autonomy tools cannot command during Human Control
- [ ] Teleop bridge start/stop logs (or real teleop if enabled)
- [ ] Resume returns to Autonomous
- [ ] Delivery completes and iMessage reports success
- [ ] Without failure flag, full simulated delivery works

## Acceptance

- Checklist above passable in dry-run without hardware.
- First-test-demo movement path still documented / not needlessly broken.
- Clear README path for the recovery demo.

## Out of scope

Redesigning tool schemas, replacing Luna, building a new teleop stack, adding databases or job queues.

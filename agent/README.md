# Agent

## First test demo

The first-test path receives a Linq iMessage, asks Runware GPT-5.6 Luna to
interpret supported movement commands, prints a simulated robot command, and
sends the confirmation back to the same Linq chat.

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Copy the environment template and fill in the Linq and Runware keys:

   ```bash
   cp .env.example .env
   ```

   The module entrypoint accepts `.env` in either the repository root or the
   `agent/` directory.

3. Start the service:

   ```bash
   cd agent
   PYTHONPATH=src python -m demo.main
   ```

4. In another terminal, expose it publicly:

   ```bash
   ngrok http 8000
   ```

5. Set `PUBLIC_BASE_URL` to the HTTPS tunnel origin. Configure a Linq
   `message.received` webhook at:

   ```text
   https://<tunnel>/webhooks/linq?version=2026-02-03
   ```

6. Send test messages such as `move forward 2 meters`, `move backward 1
   meter`, `turn left`, `turn right 45 degrees`, and `stop`. An unsupported
   message such as `what's the weather?` should receive a polite refusal
   without printing a robot movement.

Check service health with:

```bash
curl http://localhost:8000/health
```

The current movement adapter only prints commands. To connect the real robot,
replace the execution body in `src/demo/tools/move_robot.py`; keep its schema,
function signature, and result shape unchanged so the webhook and LLM layers
do not need modification.

## Terac confirm-then-act

Before complex or uncertain movements, the agent can pause and ask a verified
professional via [Terac](https://terac.com/mcp). On approval the pending
`move_robot` runs; on rejection the robot does not move. AR glasses hand
teleop recovery is **not** part of this slice — see
`docs/future-product-plan.md` for that path.

### Dry-run demo (no Terac credentials)

```bash
# in agent/.env
TERAC_DRY_RUN=true
TERAC_DRY_RUN_DECISION=approve   # or reject
TERAC_REQUIRE_CONFIRMATION=true
```

1. Start the demo as usual (`PYTHONPATH=src python -m demo.main`).
2. Send `move forward 2 meters` over Linq (or call the LLM path locally).
3. With `approve`, expect a `ROBOT: move forward 2m` print and a confirmation
   reply. With `reject`, expect no robot print and a declined-action reply.

When `TERAC_REQUIRE_CONFIRMATION=false`, simple moves can still call
`move_robot` directly; the LLM may still escalate ambiguous commands via
`request_professional_confirmation`.

### Live Terac

```bash
TERAC_DRY_RUN=false
TERAC_API_KEY=...
TERAC_PROJECT_ID=...          # if required by your org
TERAC_WEBHOOK_SECRET=...      # optional shared secret / HMAC
TERAC_REQUIRE_CONFIRMATION=true
```

Point Terac submission webhooks at:

```text
https://<tunnel>/webhooks/terac
```

Live flow: confirmation launches an opportunity → agent replies that the robot
is paused → Terac webhook (or later poll) resumes → approved actions execute
and Linq gets a follow-up. Exact REST body fields may need a quick check
against Terac’s OpenAPI for your account.

To poll manually during demos (instead of waiting on a webhook):

```bash
curl -X POST http://localhost:8000/webhooks/terac/poll/<opportunity_id>
```


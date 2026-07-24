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

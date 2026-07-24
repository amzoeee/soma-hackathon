# Agent

The demo receives a Linq iMessage, asks Runware GPT-5.6 Luna to translate the
complete request into an ordered robot-tool sequence, executes the tools in
order, and sends a deterministic result summary to the same Linq chat.
Model-authored prose is never returned through iMessage.

## Setup

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Copy the environment template and fill in the Linq and Runware keys:

   ```bash
   cp .env.example .env
   ```

   The entrypoint accepts `.env` in either the repository root or `agent/`.

3. Start the service:

   ```bash
   cd agent
   PYTHONPATH=src python -m demo.main
   ```

4. Start LocalTunnel in another terminal:

   ```bash
   npx --yes localtunnel --port 8000
   ```

5. Set `PUBLIC_BASE_URL` to the HTTPS tunnel origin and configure a Linq
   `message.received` webhook at:

   ```text
   https://<tunnel>/webhooks/linq?version=2026-02-03
   ```

Check service health with:

```bash
curl http://localhost:8000/health
```

## Robot tools

The model can emit multiple calls in one response. Calls execute sequentially
and the sequence stops on the first failure.

- `move_cartesian(delta_x_m, delta_y_m, delta_z_m)` — differential IK motion;
  `+x` right, `+y` forward, `+z` up.
- `move_wrist(pitch_degrees, roll_degrees)` — differential wrist motion; each
  motor accepts `-160` through `+160` degrees.
- `set_gripper(state)` — set the calibrated endpoint to `open` or `closed`.
- `hold_position(hold=true)` — stop motion and hold the current pose.

For a retrace request, the planner emits inverse Cartesian and wrist calls in
reverse order. Gripper operations are changed only when the user explicitly
requests them.

Example:

```text
Move up 100 cm, roll wrist right 90 degrees, open the gripper, move forward
20 cm, close the gripper, retrace to the original position, then open it.
```

This plans nine ordered calls: up, wrist right, open, forward, close, backward,
wrist left, down, open.

## Deterministic Linq replies

The application ignores model-authored response text. It builds the iMessage
from structured tool results:

```text
Executed 2 robot actions:
1. [OK] Cartesian IK applied Δx=+0m, Δy=+0.2m, Δz=+0m.
2. [OK] Gripper set to closed.
```

When hardware safety or workspace limits reduce a requested differential, the
reply reports both the requested and applied XYZ values.

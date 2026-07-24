# First-Test Demo Setup Runbook

Use this runbook to bring the Soma first-test demo up from a fresh clone or
resume an existing setup. Every section starts with a check: if the desired
state already exists, reuse it instead of repeating the action.

The completed flow is:

```text
iMessage
  → Linq
  → public HTTPS tunnel
  → POST /webhooks/linq
  → Runware GPT-5.6 Luna (one ordered planning pass)
  → explicit robot tools
  → deterministic Linq reply
```

## Rules for the setup agent

- Never print, commit, paste into chat, or include in tool output any API key or
  webhook signing secret.
- Never overwrite an existing `.env`. Check it and only fill missing values.
- Never create another Linq API token if the existing token authenticates.
- Never create a duplicate webhook subscription. Update the existing
  subscription when only its tunnel URL changed.
- Never delete or recreate a subscription merely because its signing secret is
  not visible in `linq webhooks list`. Linq only returns that secret when the
  subscription is first created.
- Never discard a dirty Git worktree. Preserve unrelated or concurrent work.
- Do not use `source .env`; parse it with `python-dotenv` so values cannot be
  executed as shell commands.
- LocalTunnel is the tunnel used by this demo. It is not ngrok.

## 1. Locate or clone the repository

First check whether the current directory is already the project:

```bash
git rev-parse --show-toplevel 2>/dev/null
git remote get-url origin 2>/dev/null
```

If the remote is already `amzoeee/soma-hackathon`, do not clone again. Change
to the returned repository root and continue.

Only when no project checkout exists:

```bash
git clone git@github.com:amzoeee/soma-hackathon.git
cd soma-hackathon
```

Before pulling, check for local work:

```bash
git status --short --branch
```

- If the worktree is dirty, do not pull, reset, stash, or switch branches
  without understanding who owns those changes.
- If it is clean, update without creating an unnecessary merge:

  ```bash
  git switch main
  git pull --ff-only origin main
  ```

## 2. Check the required tools

Run:

```bash
python3 --version
node --version
npm --version
linq --version
```

The service uses Python, Node/npm runs LocalTunnel, and the Linq CLI manages the
receiving number and webhook subscription.

If the Linq CLI is missing, and only then:

```bash
npm install -g @linqapp/cli@latest
```

If the CLI is present, do not reinstall it just to obtain a newer version.

## 3. Reuse or create the Python environment

From the repository root, check for the virtual environment:

```bash
test -x .venv/bin/python && echo "virtualenv exists"
```

Only if it does not exist:

```bash
python3 -m venv .venv
```

Check whether the demo dependencies already import:

```bash
PYTHONPATH=agent/src .venv/bin/python -c \
  "import fastapi, httpx, openai, pydantic_settings, uvicorn"
```

If that succeeds, do not reinstall dependencies. If it fails:

```bash
.venv/bin/pip install -r agent/requirements.txt
```

## 4. Reuse or create `.env`

The entrypoint accepts `.env` in either the repository root or `agent/`. Prefer
the repository root.

Check both locations:

```bash
test -f .env && echo "using root .env"
test -f agent/.env && echo "using agent/.env"
```

If either exists, use it and do not copy over it. Only when neither exists:

```bash
cp agent/.env.example .env
chmod 600 .env
```

Required settings:

```dotenv
LINQ_API_KEY=
LINQ_WEBHOOK_SECRET=
RUNWARE_API_KEY=
RUNWARE_BASE_URL=https://api.runware.ai/v1
RUNWARE_MODEL=gpt-5.6-luna
PUBLIC_BASE_URL=
```

Check presence without revealing values:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from dotenv import dotenv_values

path = Path(".env") if Path(".env").exists() else Path("agent/.env")
values = dotenv_values(path)
required_now = [
    "LINQ_API_KEY",
    "RUNWARE_API_KEY",
    "RUNWARE_BASE_URL",
    "RUNWARE_MODEL",
]
missing = [name for name in required_now if not values.get(name)]
print(f"env file: {path}")
print("missing:", ", ".join(missing) if missing else "none")
print("LINQ_WEBHOOK_SECRET:", "set" if values.get("LINQ_WEBHOOK_SECRET") else "not set")
print("PUBLIC_BASE_URL:", "set" if values.get("PUBLIC_BASE_URL") else "not set")
PY
```

At this point `LINQ_WEBHOOK_SECRET` and `PUBLIC_BASE_URL` may legitimately be
empty if the tunnel and subscription have not been created yet.

Ask the user to supply missing API keys. Do not generate, echo, or copy secrets
through assistant-visible command output.

## 5. Verify the Linq account before changing anything

Check the CLI session:

```bash
linq whoami
linq phonenumbers --json
```

If authentication fails, use:

```bash
linq login
```

Do not create a new API token when the existing `.env` token and CLI account
are already the intended account. Confirm that the receiving number shown by
the CLI belongs to the account the user wants to test.

The demo's previously used CLI number was `+12054015445`, but treat
`linq phonenumbers --json` as the source of truth rather than assuming that
number is still assigned.

The `LINQ_API_KEY` in `.env` must authenticate to the same Linq account whose
number will receive the test message. A CLI profile and `.env` can otherwise
silently point at different accounts.

If the user explicitly wants the authenticated CLI account and the `.env`
token is missing or belongs to another account, reuse the CLI's existing token
instead of creating a new one. Capture it without displaying it:

```bash
umask 077
linq tokens show --json > /tmp/soma-linq-token.json

.venv/bin/python - <<'PY'
import json
from pathlib import Path
from dotenv import set_key

token_file = Path("/tmp/soma-linq-token.json")
payload = json.loads(token_file.read_text())

def find_token(value):
    if isinstance(value, dict):
        for key in ("token", "api_key", "apiKey", "secret", "value"):
            candidate = value.get(key)
            if isinstance(candidate, str) and len(candidate) > 20:
                return candidate
        for candidate in value.values():
            found = find_token(candidate)
            if found:
                return found
    return None

token = find_token(payload)
if not token:
    raise SystemExit("Could not find a token in Linq CLI output")

env_path = Path(".env") if Path(".env").exists() else Path("agent/.env")
set_key(str(env_path), "LINQ_API_KEY", token, quote_mode="auto")
token_file.unlink()
print(f"Updated LINQ_API_KEY in {env_path} without displaying it")
PY
```

## 6. Check whether the service is already running

Run:

```bash
curl --fail --silent http://127.0.0.1:8000/health
```

If it returns:

```json
{"ok":true}
```

do not start a second server.

If it fails, start the service in a dedicated terminal from the repository
root:

```bash
PYTHONPATH=agent/src .venv/bin/python -m demo.main
```

Keep that terminal running. Expected local URL:

```text
http://127.0.0.1:8000
```

Verify again with the health request before starting a tunnel.

If port 8000 is occupied but `/health` is not this application, inspect the
owner instead of killing it blindly:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

## 7. Reuse or start the HTTPS tunnel

Read only `PUBLIC_BASE_URL` without exposing the other environment values:

```bash
SOMA_PUBLIC_BASE_URL="$(
  .venv/bin/python - <<'PY'
from pathlib import Path
from dotenv import dotenv_values

path = Path(".env") if Path(".env").exists() else Path("agent/.env")
print(dotenv_values(path).get("PUBLIC_BASE_URL", ""))
PY
)"
printf 'PUBLIC_BASE_URL=%s\n' "$SOMA_PUBLIC_BASE_URL"
```

If a non-empty URL is returned, test it:

```bash
curl --fail --silent "$SOMA_PUBLIC_BASE_URL/health"
```

If it returns `{"ok":true}`, the existing tunnel works. Reuse it and do not
start another tunnel.

If the URL is missing or unhealthy, check whether LocalTunnel is already
running:

```bash
pgrep -af "localtunnel.*8000|lt.*--port 8000"
```

If no working tunnel exists, start one in a second dedicated terminal:

```bash
npx --yes localtunnel --port 8000
```

LocalTunnel prints a temporary URL such as:

```text
https://example-name.loca.lt
```

Set `PUBLIC_BASE_URL` in the selected `.env` to that origin, without the
`/health` or webhook path. Keep the LocalTunnel terminal running.

Verify the new public route:

```bash
curl --fail --silent https://example-name.loca.lt/health
```

Do not continue until both local and public health checks return
`{"ok":true}`.

## 8. Reuse, update, or create the Linq webhook

List existing subscriptions before any mutation:

```bash
linq webhooks list --json
```

The required target is:

```text
${PUBLIC_BASE_URL}/webhooks/linq?version=2026-02-03
```

The required event is:

```text
message.received
```

Choose exactly one path:

### Existing subscription already has the correct target

Do nothing. Confirm `LINQ_WEBHOOK_SECRET` is present in `.env`; do not recreate
the subscription.

### Existing subscription has an old tunnel URL

Update it instead of creating another:

```bash
linq webhooks update SUBSCRIPTION_ID \
  --url "https://example-name.loca.lt/webhooks/linq?version=2026-02-03" \
  --events message.received \
  --activate
```

Updating preserves the subscription's signing secret, so the existing
`LINQ_WEBHOOK_SECRET` remains valid.

### No suitable subscription exists

Create one:

```bash
umask 077
linq webhooks create \
  --url "https://example-name.loca.lt/webhooks/linq?version=2026-02-03" \
  --events message.received \
  --json > /tmp/soma-linq-webhook.json

.venv/bin/python - <<'PY'
import json
from pathlib import Path
from dotenv import set_key

response_file = Path("/tmp/soma-linq-webhook.json")
payload = json.loads(response_file.read_text())
secret = payload.get("signing_secret")
if not secret:
    raise SystemExit("Linq did not return a signing_secret")

env_path = Path(".env") if Path(".env").exists() else Path("agent/.env")
set_key(str(env_path), "LINQ_WEBHOOK_SECRET", secret, quote_mode="auto")
response_file.unlink()
print(f"Saved LINQ_WEBHOOK_SECRET in {env_path} without displaying it")
PY
```

Linq returns the signing secret only at creation time. Save it immediately as
`LINQ_WEBHOOK_SECRET` in `.env` without printing or committing it.

Restart the Python service after changing the signing secret so the process
loads the new value.

### Subscription exists but its secret was lost

Do not delete it automatically. Explain that Linq cannot reveal the secret
again and ask for explicit approval before deleting and recreating that exact
subscription.

## 9. Verify before sending an iMessage

Confirm all of the following:

```bash
curl --fail --silent http://127.0.0.1:8000/health
curl --fail --silent "$SOMA_PUBLIC_BASE_URL/health"
linq webhooks list --json
linq phonenumbers --json
```

The service log should identify the same public webhook URL configured in
Linq. The subscription must be active and subscribed to `message.received`.

## 10. End-to-end test

Send one low-risk test iMessage to the number returned by
`linq phonenumbers --json`, for example:

```text
hold
```

Expected service behavior:

```text
POST /webhooks/linq ... 200 OK
Executing robot step 1/1: hold_position {}
POST .../chats/<chat-id>/messages ... 2xx
```

The sender should receive a short confirmation in the same conversation.

Then verify one unsupported message:

```text
What's the weather?
```

It should return the fixed supported-actions reply and must not execute a robot
tool.

## 11. Troubleshooting

### Local health works, public health fails

The tunnel is absent, stopped, or stale. Restart LocalTunnel and update the
existing Linq subscription's URL. Do not create a duplicate subscription.

### Webhook returns 401

The running process and Linq subscription use different signing secrets.
Confirm the selected `.env`, then restart the service. Do not print the secret.

### Inbound command runs but no reply arrives

Check the Linq response in service logs. Current Linq v3 existing-chat sends
must use:

```json
{
  "message": {
    "parts": [
      {"type": "text", "value": "Done"}
    ]
  }
}
```

### Runware rejects tool calling

GPT-5.6 Luna on Runware Chat Completions requires
`reasoning_effort="none"` when function tools are supplied. This is already
configured in `agent/src/demo/llm.py`.

### Webhook is delivered more than once

Linq delivery is at-least-once. The router keeps an in-process deduplication
cache. Do not restart repeatedly while a failed delivery is retrying; fix the
outbound error first.

## 12. What must remain running

For a local demo, keep two processes alive:

1. `PYTHONPATH=agent/src .venv/bin/python -m demo.main`
2. `npx --yes localtunnel --port 8000`

Stopping either process breaks the public webhook path. LocalTunnel URLs are
ephemeral, so a new tunnel URL must be written to `.env` and applied to the
existing Linq webhook subscription.

# Linq — message the arm, get movement

Text Linq in plain language ("grab the cube and lift it 10cm"); a LangGraph
pipeline turns that into a validated action plan and dispatches it to the
SO-101 arm. This is the backbone — the graph runs end to end today in dry-run
mode with no hardware attached.

## Flow

```
inbound text
     │
     ▼
┌─────────────┐   Claude (structured output) → {reply, actions[]}
│ understand  │   the only LLM call in the graph
└─────┬───────┘
      ▼
┌─────────────┐   envelope bounds, plan length, gripper/wait limits
│  validate   │   fails closed: a bad plan is rejected whole, not truncated
└─────┬───────┘
      ├── rejected ──────────────┐
      ▼                          │
┌─────────────┐                  │
│   execute   │  IK → safety clamp → arm.send_action()
└─────┬───────┘                  │
      ▼                          ▼
┌──────────────────────────────────┐
│            respond               │  deterministic; no second LLM call
└──────────────────────────────────┘
```

## Layout

| File | Role |
|---|---|
| `graph.py` | LangGraph wiring + `run_turn()` |
| `state.py` | `LinqState` (what flows between nodes) |
| `actions.py` | Action vocabulary + the JSON schema Claude fills in |
| `nodes/understand.py` | Claude call: message → `{reply, actions}` |
| `nodes/validate.py` | Deterministic safety gate |
| `nodes/execute.py` | Runs approved actions |
| `nodes/respond.py` | Folds outcome into the reply |
| `executor.py` | Action → IK → safety → `ArmController` |
| `deps.py` | Collaborator bundle injected into nodes |
| `config.py` | Model, effort, dispatch limits, dry-run flag |
| `channels/` | Inbound transports (`cli.py` today) |
| `run.py` | Entry point |

## Action vocabulary

`move_to` · `nudge` · `gripper` · `home` · `wait` · `say` · `send_text`

Add one by defining a dataclass with `NAME`/`SCHEMA` in `actions.py`, appending
it to `ACTION_TYPES`, and adding a branch in `ActionExecutor._dispatch`. The
schema, the system prompt, and validation all read from that list.

## Run it

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # or: ant auth login

python -m src.linq.run                       # dry-run, arm never moves
python -m src.linq.run --live --port /dev/ttyACM0
python -m src.linq.run --effort high         # deeper planning, slower
```

Dry-run is the default and `build_executor` also falls back to it whenever the
arm won't connect or the URDF is missing — so the graph is always runnable.

## Design notes

- **One LLM call per turn.** Planning is the only step that needs a model;
  making `respond` deterministic keeps latency and cost down.
- **Validation is not the model's job.** The schema constrains shape;
  `validate.py` constrains meaning, against `config/settings.py` bounds.
- **`nudge` is tracked through the plan.** Validation walks a cursor so relative
  moves are checked against where the arm *will* be, not where it is now.
- **The system prompt is byte-stable** and cache-marked, so multi-turn
  conversations hit the prompt cache.

## Not built yet

- `channels/http.py` — webhook/SMS ingress (Twilio, Slack)
- Real gripper range mapping in `ActionExecutor._gripper`
- Overlay wiring in `_say` (needs a message slot on `StatusDisplay`)
- Perception grounding: "the cube" currently has no resolver

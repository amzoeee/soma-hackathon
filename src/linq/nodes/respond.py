"""Compose the outbound reply.

Deterministic on purpose -- a second model call here would double latency and
cost to restate what we already know happened.
"""

from typing import Any, Callable, Dict

from ..deps import LinqDeps
from ..state import LinqState


def make_respond(deps: LinqDeps) -> Callable[[LinqState], Dict[str, Any]]:
    """Node: fold execution outcome into the model's draft reply."""

    def respond(state: LinqState) -> Dict[str, Any]:
        draft = state.get("reply_draft", "").strip()
        errors = state.get("errors", [])
        results = state.get("results", [])

        if errors:
            reason = errors[0]
            # Keep the reason in history -- next turn benefits from knowing the
            # last target was rejected.
            core = f"{draft} (stopped: {reason})" if draft else f"I didn't run that: {reason}"
        elif results:
            core = draft or f"Done -- {len(results)} action(s)."
        else:
            core = draft or "Nothing to do."

        # The dry-run tag is an operator display concern, not conversation
        # content, so it stays out of the history the model sees.
        reply = f"{core} [dry-run]" if (results and deps.executor.dry_run) else core

        return {
            "reply": reply,
            "messages": [{"role": "assistant", "content": core}],
        }

    return respond

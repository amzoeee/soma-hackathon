"""Message -> action plan. The only node that talks to Claude."""

import json
import logging
from typing import Any, Callable, Dict

from ..actions import PLAN_SCHEMA, describe_vocabulary
from ..deps import LinqDeps
from ..state import LinqState

logger = logging.getLogger(__name__)


def build_system_prompt(deps: LinqDeps) -> str:
    """Persona + capabilities + the envelope the arm can actually reach.

    Kept byte-stable across turns so the prompt cache holds; anything that
    changes per turn belongs in the user message instead.
    """
    s = deps.settings
    vocabulary = "\n".join(describe_vocabulary())
    return (
        f"{deps.config.persona}\n\n"
        "Available actions:\n"
        f"{vocabulary}\n\n"
        "Robot frame is meters, origin at the arm base. Reachable envelope:\n"
        f"  x: {s.workspace_x_min} to {s.workspace_x_max}\n"
        f"  y: {s.workspace_y_min} to {s.workspace_y_max}\n"
        f"  z: {s.workspace_z_min} to {s.workspace_z_max}\n\n"
        "Rules:\n"
        f"- At most {deps.config.max_actions} actions per turn.\n"
        "- Never emit a target outside the envelope. Clamp, or ask instead.\n"
        "- Prefer `nudge` for relative phrasing ('a bit left'), `move_to` for absolute.\n"
        "- Close the gripper before lifting an object, open it before releasing.\n"
        "- If the request is ambiguous, destructive, or out of reach, return an "
        "empty action list and ask a clarifying question in the reply.\n"
        "- The reply is one short sentence. No preamble, no markdown."
    )


def make_understand(deps: LinqDeps) -> Callable[[LinqState], Dict[str, Any]]:
    """Node: read the inbound message, produce {reply_draft, plan}."""

    system = build_system_prompt(deps)

    def understand(state: LinqState) -> Dict[str, Any]:
        client = deps.anthropic()
        history = state.get("messages", [])

        try:
            response = client.messages.create(
                model=deps.config.model,
                max_tokens=deps.config.max_tokens,
                system=[{
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }],
                thinking={"type": "adaptive"},
                output_config={
                    "effort": deps.config.effort,
                    "format": {"type": "json_schema", "schema": PLAN_SCHEMA},
                },
                messages=history,
            )
        except Exception as e:
            logger.exception("Planner call failed")
            return {
                "plan": [],
                "reply_draft": "",
                "errors": [f"planner unavailable: {e}"],
            }

        if response.stop_reason == "refusal":
            return {"plan": [], "reply_draft": "",
                    "errors": ["planner declined that request"]}
        if response.stop_reason == "max_tokens":
            return {"plan": [], "reply_draft": "",
                    "errors": ["plan was cut off; try a simpler request"]}

        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error("Planner returned non-JSON: %s", text[:200])
            return {"plan": [], "reply_draft": "",
                    "errors": [f"could not parse plan: {e}"]}

        return {
            "plan": payload.get("actions", []),
            "reply_draft": payload.get("reply", ""),
            "errors": [],
        }

    return understand

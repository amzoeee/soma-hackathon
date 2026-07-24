"""Application orchestration for one inbound Linq message."""

from __future__ import annotations

import logging
from typing import Any

from .linq_client import InboundMessage
from .llm import interpret_and_call_tools

logger = logging.getLogger("demo.handler")

SUPPORTED_ACTIONS_REPLY = (
    "No robot action was executed. Supported actions: Cartesian XYZ movement, "
    "wrist pitch/roll, open or close gripper, and hold position."
)
EMPTY_COMMAND_REPLY = (
    "No robot action was executed. Send a Cartesian movement, wrist movement, "
    "gripper command, or hold command."
)


def format_tool_results(tool_results: list[dict[str, Any]]) -> str:
    """Build a deterministic Linq reply solely from structured tool results."""
    if not tool_results:
        return SUPPORTED_ACTIONS_REPLY

    total = max(
        (
            int(result.get("sequence_total", len(tool_results)))
            for result in tool_results
        ),
        default=len(tool_results),
    )
    succeeded = sum(1 for result in tool_results if result.get("ok"))
    failed = next((result for result in tool_results if not result.get("ok")), None)

    if failed is None:
        noun = "action" if succeeded == 1 else "actions"
        heading = f"Executed {succeeded} robot {noun}:"
    else:
        failed_step = int(failed.get("step", succeeded + 1))
        heading = (
            f"Robot sequence stopped at step {failed_step} of {total}; "
            f"{succeeded} action{' was' if succeeded == 1 else 's were'} completed:"
        )

    lines = [heading]
    for fallback_step, result in enumerate(tool_results, start=1):
        step = int(result.get("step", fallback_step))
        status = "OK" if result.get("ok") else "FAILED"
        message = str(result.get("message") or "No result message.").strip()
        lines.append(f"{step}. [{status}] {message}")
    return "\n".join(lines)


async def handle_message(msg: InboundMessage) -> str:
    """Plan and execute one operator message, returning a programmatic reply."""
    if not msg.text or not msg.text.strip():
        return EMPTY_COMMAND_REPLY
    try:
        tool_results = await interpret_and_call_tools(msg.text)
    except RuntimeError as exc:
        logger.error(
            "Could not process Linq message %s: %s",
            msg.message_id or "<unknown>",
            exc,
        )
        return "No robot action was executed. The command planner is unavailable."
    except Exception:
        logger.exception(
            "Unexpected failure processing Linq message %s",
            msg.message_id or "<unknown>",
        )
        return "No robot action was executed. An internal error occurred."
    return format_tool_results(tool_results)

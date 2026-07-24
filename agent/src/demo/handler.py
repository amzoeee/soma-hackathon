"""Application orchestration for one inbound Linq message."""

from __future__ import annotations

import logging

from .linq_client import InboundMessage
from .llm import interpret_and_call_tools

logger = logging.getLogger("demo.handler")


async def handle_message(msg: InboundMessage) -> str:
    """Interpret one operator message and return a Linq-ready reply."""
    try:
        assistant_text, tool_results = await interpret_and_call_tools(msg.text)
    except RuntimeError as exc:
        logger.error(
            "Could not process Linq message %s: %s",
            msg.message_id or "<unknown>",
            exc,
        )
        return "Sorry, I couldn't process that movement command right now."
    except Exception:
        logger.exception(
            "Unexpected failure processing Linq message %s",
            msg.message_id or "<unknown>",
        )
        return "Sorry, something went wrong while processing that command."

    if assistant_text and assistant_text.strip():
        return assistant_text.strip()

    confirmations = [
        str(result.get("message", "")).strip()
        for result in tool_results
        if result.get("ok") and str(result.get("message", "")).strip()
    ]
    if confirmations:
        return "; ".join(confirmations)

    failures = [
        str(result.get("message", "")).strip()
        for result in tool_results
        if not result.get("ok") and str(result.get("message", "")).strip()
    ]
    if failures:
        return failures[0]

    return "I couldn't interpret that as a supported movement command."

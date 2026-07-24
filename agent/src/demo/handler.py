"""Application orchestration for one inbound Linq message."""

from __future__ import annotations

import logging

from .linq_client import InboundMessage
from .llm import interpret_and_call_tools
from .terac.context import set_conversation_id

logger = logging.getLogger("demo.handler")


async def handle_message(msg: InboundMessage) -> str:
    """Interpret one operator message and return a Linq-ready reply."""
    set_conversation_id(msg.conversation_id)
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
    finally:
        set_conversation_id(None)

    pending = [
        result
        for result in tool_results
        if result.get("needs_human")
        or (
            isinstance(result.get("data"), dict)
            and result["data"].get("status") == "pending"
        )
    ]
    if pending:
        for result in pending:
            message = str(result.get("message", "")).strip()
            if message:
                return message
        return "Paused pending professional confirmation. The robot has not moved."

    rejected = [
        result
        for result in tool_results
        if isinstance(result.get("data"), dict)
        and result["data"].get("status") in {"rejected", "dry_run_rejected"}
    ]
    if rejected and not any(r.get("ok") and r.get("printed") for r in tool_results):
        for result in rejected:
            message = str(result.get("message", "")).strip()
            if message:
                return message

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

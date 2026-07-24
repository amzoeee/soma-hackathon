"""Apply Terac expert decisions to pending actions and notify Linq."""

from __future__ import annotations

import logging
from typing import Any

from demo.linq_client import LinqClient, OutboundReply
from demo.terac.pending import PendingAction, get_pending_store

logger = logging.getLogger("demo.terac.resume")


def _execute_pending_tool(action: PendingAction) -> dict[str, Any]:
    from demo.tools import execute_tool

    if not action.tool_name:
        return {
            "ok": False,
            "message": (
                "Approved, but no structured tool call was stored for "
                f"{action.proposed_action!r}."
            ),
            "needs_human": False,
        }
    # Bypass confirmation gate — this path already has professional approval.
    result = execute_tool(
        action.tool_name,
        action.tool_arguments or {},
        bypass_confirmation=True,
    )
    return result if isinstance(result, dict) else {
        "ok": False,
        "message": "Tool execution returned a non-dict result",
        "needs_human": False,
    }


async def apply_decision(
    confirmation_id: str,
    *,
    decision: str,
    guidance: str | None = None,
    linq_client: LinqClient | None = None,
    notify: bool = True,
) -> PendingAction | None:
    """Mark pending confirmation approved/rejected; execute on approve."""
    store = get_pending_store()
    action = store.get(confirmation_id)
    if action is None:
        logger.warning("No pending confirmation %s", confirmation_id)
        return None

    normalized = decision.strip().lower()
    if normalized in {"approve", "approved", "yes", "true"}:
        is_approve = True
    elif normalized in {"reject", "rejected", "no", "false", "decline", "declined"}:
        is_approve = False
    else:
        # Treat unknown as reject for safety
        logger.warning(
            "Unrecognized Terac decision %r for %s; treating as reject",
            decision,
            confirmation_id,
        )
        is_approve = False

    if not is_approve:
        status = (
            "dry_run_rejected"
            if (action.opportunity_id or "").startswith("dry_")
            else "rejected"
        )
        store.set_status(
            confirmation_id,
            status,  # type: ignore[arg-type]
            expert_guidance=guidance,
        )
        note = guidance or "No additional guidance provided."
        await _maybe_notify(
            linq_client,
            conversation_id=action.conversation_id,
            text=(
                "A professional declined the proposed action "
                f"({action.proposed_action}). {note}"
            ),
            notify=notify,
            confirmation_id=confirmation_id,
        )
        return store.get(confirmation_id)

    status = (
        "dry_run_approved"
        if (action.opportunity_id or "").startswith("dry_")
        else "approved"
    )
    store.set_status(
        confirmation_id,
        status,  # type: ignore[arg-type]
        expert_guidance=guidance,
    )
    store.grant_move_approval(confirmation_id)

    tool_result = _execute_pending_tool(action)
    store.set_status(
        confirmation_id,
        "executed",
        expert_guidance=guidance,
        tool_result=tool_result,
    )

    if tool_result.get("ok"):
        text = (
            f"Professional approved. "
            f"{tool_result.get('message') or 'Action executed.'}"
        )
    else:
        text = (
            "Professional approved, but execution failed: "
            f"{tool_result.get('message') or 'unknown error'}"
        )
    if guidance:
        text = f"{text} Expert note: {guidance}"
    await _maybe_notify(
        linq_client,
        conversation_id=action.conversation_id,
        text=text,
        notify=notify,
        confirmation_id=confirmation_id,
    )

    return store.get(confirmation_id)


async def _maybe_notify(
    linq_client: LinqClient | None,
    *,
    conversation_id: str | None,
    text: str,
    notify: bool,
    confirmation_id: str,
) -> None:
    if not notify:
        return
    if not linq_client:
        return
    if not conversation_id:
        logger.warning(
            "Confirmation %s has no conversation_id; skipping Linq notify",
            confirmation_id,
        )
        return
    try:
        await linq_client.send_reply(
            OutboundReply(conversation_id=conversation_id, text=text)
        )
    except Exception:
        logger.exception(
            "Linq notify failed for confirmation %s (action already applied)",
            confirmation_id,
        )

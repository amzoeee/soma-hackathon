"""Request professional confirmation via Terac before acting."""

from __future__ import annotations

import logging
from typing import Any

from demo.config import get_settings
from demo.terac.client import get_terac_client
from demo.terac.context import get_conversation_id
from demo.terac.parse_action import parse_proposed_action
from demo.terac.pending import get_pending_store
from demo.terac.resume import apply_decision

logger = logging.getLogger("demo.tools.request_professional_confirmation")

REQUEST_PROFESSIONAL_CONFIRMATION_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "request_professional_confirmation",
        "description": (
            "Pause and ask a verified professional (via Terac) to approve or "
            "reject a proposed robot action before it runs. Use for ambiguous, "
            "multi-step, long-distance, or otherwise complex commands. Do not "
            "call move_robot for that action until confirmation is approved "
            "(except stop, which never needs confirmation)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "proposed_action": {
                    "type": "string",
                    "description": (
                        "Human-readable proposed action, e.g. "
                        "'move_robot forward 2m' or 'turn left 90 degrees'."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "Why professional judgment is needed.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional scene or task summary for the expert.",
                },
                "urgency": {
                    "type": "string",
                    "enum": ["normal", "high"],
                    "description": "Urgency hint for matching (default normal).",
                },
                "tool_name": {
                    "type": "string",
                    "description": "Optional structured tool to run on approval.",
                },
                "tool_arguments": {
                    "type": "object",
                    "description": "Optional JSON args for tool_name on approval.",
                    "additionalProperties": True,
                },
            },
            "required": ["proposed_action", "reason"],
            "additionalProperties": False,
        },
    },
}


def _result(
    *,
    ok: bool,
    message: str,
    data: dict[str, Any] | None = None,
    needs_human: bool = False,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "message": message,
        "data": data,
        "needs_human": needs_human,
        "printed": "",
    }


async def request_professional_confirmation(
    proposed_action: str,
    reason: str,
    context: str | None = None,
    urgency: str = "normal",
    tool_name: str | None = None,
    tool_arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Launch (or dry-run) a Terac confirmation for a proposed action."""
    if not isinstance(proposed_action, str) or not proposed_action.strip():
        return _result(ok=False, message="proposed_action is required")
    if not isinstance(reason, str) or not reason.strip():
        return _result(ok=False, message="reason is required")

    urgency_norm = (urgency or "normal").strip().lower()
    if urgency_norm not in {"normal", "high"}:
        urgency_norm = "normal"

    parsed_name, parsed_args = parse_proposed_action(proposed_action)
    resolved_name = tool_name or parsed_name
    resolved_args = tool_arguments if isinstance(tool_arguments, dict) else parsed_args

    settings = get_settings()
    store = get_pending_store()
    conversation_id = get_conversation_id()
    action = store.create(
        proposed_action=proposed_action.strip(),
        reason=reason.strip(),
        tool_name=resolved_name,
        tool_arguments=resolved_args,
        context=context.strip() if isinstance(context, str) and context.strip() else None,
        urgency=urgency_norm,
        conversation_id=conversation_id,
    )

    task_parts = [
        "Robot confirm-then-act review.",
        f"Proposed action: {action.proposed_action}",
        f"Reason: {action.reason}",
    ]
    if action.context:
        task_parts.append(f"Context: {action.context}")
    task_parts.append(
        "Reply with a clear decision: approve or reject. "
        "Optionally include short guidance."
    )
    task = "\n".join(task_parts)

    client = get_terac_client()
    try:
        quote = await client.create_quote(
            role=settings.terac_expert_role,
            task=task,
            count=1,
        )
        launch = await client.launch_opportunity(quote.quote_id)
    except Exception as exc:
        logger.exception("Terac launch failed for %s", action.confirmation_id)
        store.set_status(action.confirmation_id, "rejected", expert_guidance=str(exc))
        return _result(
            ok=False,
            message=f"Failed to request professional confirmation: {exc}",
            data={
                "confirmation_id": action.confirmation_id,
                "status": "rejected",
                "opportunity_id": None,
                "expert_guidance": str(exc),
            },
            needs_human=False,
        )

    store.bind_opportunity(
        action.confirmation_id,
        quote_id=quote.quote_id,
        opportunity_id=launch.opportunity_id,
    )

    if client.dry_run:
        decision = settings.terac_dry_run_decision
        updated = await apply_decision(
            action.confirmation_id,
            decision=decision,
            guidance=f"Dry-run {decision}",
            linq_client=None,
            notify=False,
        )
        status = (
            "dry_run_approved" if decision == "approve" else "dry_run_rejected"
        )
        tool_result = updated.tool_result if updated else None
        if decision == "approve":
            message = (
                "Dry-run professional approved; pending action executed."
                if tool_result and tool_result.get("ok")
                else (
                    "Dry-run professional approved, but execution failed: "
                    f"{(tool_result or {}).get('message', 'unknown')}"
                )
            )
            return _result(
                ok=bool(tool_result and tool_result.get("ok")),
                message=message,
                data={
                    "confirmation_id": action.confirmation_id,
                    "status": status,
                    "opportunity_id": launch.opportunity_id,
                    "expert_guidance": "Dry-run approve",
                    "tool_result": tool_result,
                },
                needs_human=False,
            )
        return _result(
            ok=True,
            message="Dry-run professional rejected the proposed action; robot did not move.",
            data={
                "confirmation_id": action.confirmation_id,
                "status": status,
                "opportunity_id": launch.opportunity_id,
                "expert_guidance": "Dry-run reject",
            },
            needs_human=False,
        )

    logger.info(
        "Terac confirmation pending id=%s opportunity=%s",
        action.confirmation_id,
        launch.opportunity_id,
    )
    return _result(
        ok=True,
        message="Confirmation requested; robot paused pending professional review.",
        data={
            "confirmation_id": action.confirmation_id,
            "status": "pending",
            "opportunity_id": launch.opportunity_id,
            "expert_guidance": None,
            "quote_id": quote.quote_id,
            "price_usd": quote.price_usd,
            "eta_hours": quote.eta_hours,
        },
        needs_human=True,
    )

"""Poll Terac submissions and resume a pending confirmation (demo helper)."""

from __future__ import annotations

import logging
from typing import Any

from demo.linq_client import LinqClient
from demo.terac.client import get_terac_client
from demo.terac.pending import get_pending_store
from demo.terac.resume import apply_decision

logger = logging.getLogger("demo.terac.poll")


async def poll_and_resume(
    opportunity_id: str,
    *,
    linq_client: LinqClient | None = None,
    notify: bool = True,
) -> dict[str, Any]:
    """Fetch submissions for an opportunity and apply the first clear decision."""
    store = get_pending_store()
    action = store.get_by_opportunity(opportunity_id)
    if action is None:
        return {"ok": False, "message": f"No pending action for {opportunity_id}"}

    if action.status in {"executed", "rejected", "dry_run_rejected"}:
        return {
            "ok": True,
            "message": f"Already finalized as {action.status}",
            "confirmation_id": action.confirmation_id,
            "status": action.status,
        }

    client = get_terac_client()
    submissions = await client.get_submissions(opportunity_id)
    for submission in submissions:
        decision = submission.decision
        if not decision:
            status = submission.status.upper()
            if status in {"APPROVED", "COMPLETE", "COMPLETED"}:
                decision = "approve"
            elif status in {"REJECTED", "DECLINED"}:
                decision = "reject"
        if not decision:
            continue
        updated = await apply_decision(
            action.confirmation_id,
            decision=decision,
            guidance=submission.guidance,
            linq_client=linq_client,
            notify=notify,
        )
        return {
            "ok": True,
            "message": f"Applied decision {decision}",
            "confirmation_id": action.confirmation_id,
            "status": updated.status if updated else action.status,
            "decision": decision,
        }

    logger.info("No actionable submissions yet for %s", opportunity_id)
    return {
        "ok": True,
        "message": "No actionable submissions yet",
        "confirmation_id": action.confirmation_id,
        "status": action.status,
        "pending": True,
    }

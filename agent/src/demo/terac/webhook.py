"""FastAPI router for Terac submission / decision webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from demo.linq_client import LinqClient
from demo.terac.pending import get_pending_store
from demo.terac.poll import poll_and_resume
from demo.terac.resume import apply_decision

logger = logging.getLogger("demo.terac.webhook")


def _verify_optional_secret(
    secret: str,
    body: bytes,
    headers: Mapping[str, str],
) -> bool:
    """Simple HMAC or shared-secret header check when configured."""
    if not secret:
        return True
    provided = (
        headers.get("x-terac-signature")
        or headers.get("x-webhook-signature")
        or headers.get("authorization")
        or ""
    )
    if provided.startswith("Bearer "):
        token = provided[7:].strip()
        return hmac.compare_digest(token, secret)
    if provided.startswith("sha256="):
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(provided, f"sha256={digest}")
    # Raw shared secret in header
    return hmac.compare_digest(provided.strip(), secret)


def _extract_ids(payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        data = payload

    opportunity_id = data.get("opportunity_id") or payload.get("opportunity_id")
    opp = data.get("opportunity")
    if not opportunity_id and isinstance(opp, Mapping):
        opportunity_id = opp.get("id")
    if not opportunity_id and data.get("id") and "opportunity" in str(
        payload.get("event_type") or payload.get("type") or "opportunity"
    ).lower():
        opportunity_id = data.get("id")

    confirmation_id = (
        data.get("confirmation_id")
        or payload.get("confirmation_id")
        or data.get("external_id")
        or payload.get("external_id")
    )
    return (
        str(opportunity_id) if opportunity_id else None,
        str(confirmation_id) if confirmation_id else None,
    )


def _extract_decision(payload: Mapping[str, Any]) -> tuple[str, str | None]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        data = payload
    submission = data.get("submission")
    if not isinstance(submission, Mapping):
        submission = data

    for key in ("decision", "verdict", "recommendation"):
        value = submission.get(key) or data.get(key) or payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower(), _guidance_from(submission, data)

    status = str(
        submission.get("status") or data.get("status") or payload.get("status") or ""
    ).upper()
    if status in {"APPROVED", "COMPLETE", "COMPLETED"}:
        return "approve", _guidance_from(submission, data)
    if status in {"REJECTED", "DECLINED"}:
        return "reject", _guidance_from(submission, data)

    answers = submission.get("answers") or submission.get("response")
    if isinstance(answers, dict):
        for key in ("decision", "verdict", "approve"):
            value = answers.get(key)
            if isinstance(value, bool):
                return ("approve" if value else "reject"), _guidance_from(
                    submission, data
                )
            if isinstance(value, str) and value.strip():
                return value.strip().lower(), _guidance_from(submission, data)

    event = str(payload.get("event_type") or payload.get("type") or "").lower()
    if "approv" in event:
        return "approve", _guidance_from(submission, data)
    if "reject" in event or "declin" in event:
        return "reject", _guidance_from(submission, data)

    return "reject", _guidance_from(submission, data)


def _guidance_from(*blobs: Mapping[str, Any]) -> str | None:
    for blob in blobs:
        for key in ("guidance", "notes", "comment", "feedback", "message"):
            value = blob.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        answers = blob.get("answers") or blob.get("response")
        if isinstance(answers, dict):
            for key in ("guidance", "notes", "comment", "feedback", "reason"):
                value = answers.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def create_terac_webhook_router(
    linq_client: LinqClient,
    *,
    webhook_secret: str = "",
) -> APIRouter:
    router = APIRouter()

    @router.post("/terac")
    async def receive_terac_webhook(request: Request) -> dict[str, Any]:
        body = await request.body()
        if not _verify_optional_secret(webhook_secret, body, request.headers):
            raise HTTPException(status_code=401, detail="Invalid Terac webhook signature")
        try:
            payload = json.loads(body) if body else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
        if not isinstance(payload, Mapping):
            raise HTTPException(status_code=400, detail="Expected a JSON object")

        opportunity_id, confirmation_id = _extract_ids(payload)
        store = get_pending_store()
        action = None
        if confirmation_id:
            action = store.get(confirmation_id)
        if action is None and opportunity_id:
            action = store.get_by_opportunity(opportunity_id)
        if action is None:
            logger.info(
                "Terac webhook with no matching pending action "
                "(opportunity=%s confirmation=%s)",
                opportunity_id,
                confirmation_id,
            )
            return {"ok": True, "matched": False}

        if action.status in {"executed", "rejected", "dry_run_rejected"}:
            return {
                "ok": True,
                "matched": True,
                "confirmation_id": action.confirmation_id,
                "status": action.status,
                "duplicate": True,
            }

        decision, guidance = _extract_decision(payload)
        updated = await apply_decision(
            action.confirmation_id,
            decision=decision,
            guidance=guidance,
            linq_client=linq_client,
            notify=True,
        )
        return {
            "ok": True,
            "matched": True,
            "confirmation_id": action.confirmation_id,
            "status": updated.status if updated else action.status,
            "decision": decision,
        }

    @router.post("/terac/poll/{opportunity_id}")
    async def poll_terac_opportunity(opportunity_id: str) -> dict[str, Any]:
        """Demo helper: poll Terac submissions and resume if decided."""
        return await poll_and_resume(
            opportunity_id,
            linq_client=linq_client,
            notify=True,
        )

    return router

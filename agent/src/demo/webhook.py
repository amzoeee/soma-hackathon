"""FastAPI router for Linq message webhooks.

The parser targets Linq webhook version ``2026-02-03`` and tolerates the older
nested message shape so existing subscriptions can migrate independently.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .linq_client import InboundMessage, LinqClient, OutboundReply

logger = logging.getLogger("demo.webhook")


def parse_inbound_message(payload: Mapping[str, Any]) -> InboundMessage | None:
    """Convert a Linq message-received envelope into the shared contract.

    Example::

        payload = {
            "event_type": "message.received",
            "data": {
                "id": "msg_123",
                "direction": "inbound",
                "chat": {"id": "chat_123"},
                "sender_handle": {"handle": "+15551234567"},
                "parts": [{"type": "text", "value": "Move forward 2m"}],
            },
        }
        assert parse_inbound_message(payload).conversation_id == "chat_123"
    """
    event_type = str(
        payload.get("event_type") or payload.get("type") or ""
    ).lower()
    if event_type and event_type not in {
        "message.received",
        "message_received",
        "message.received.v2",
    }:
        return None

    data = payload.get("data")
    if not isinstance(data, Mapping):
        data = payload
    message = data.get("message")
    if not isinstance(message, Mapping):
        message = data

    direction = str(
        message.get("direction") or data.get("direction") or ""
    ).lower()
    if direction == "outbound" or message.get("is_from_me") is True:
        return None

    parts = message.get("parts")
    texts: list[str] = []
    if isinstance(parts, list):
        for part in parts:
            if (
                isinstance(part, Mapping)
                and part.get("type") == "text"
                and isinstance(part.get("value"), str)
            ):
                value = part["value"].strip()
                if value:
                    texts.append(value)
    if not texts:
        direct_text = message.get("text") or message.get("body")
        if isinstance(direct_text, str) and direct_text.strip():
            texts.append(direct_text.strip())
    if not texts:
        return None

    chat = message.get("chat") or data.get("chat")
    conversation_id = ""
    if isinstance(chat, Mapping):
        conversation_id = str(chat.get("id") or chat.get("chat_id") or "")
    elif isinstance(chat, str):
        conversation_id = chat
    conversation_id = conversation_id or str(
        message.get("chat_id")
        or data.get("chat_id")
        or message.get("conversation_id")
        or data.get("conversation_id")
        or ""
    )
    if not conversation_id:
        logger.warning("Ignoring Linq text event without a chat id")
        return None

    sender_handle = message.get("sender_handle") or data.get("sender_handle")
    if isinstance(sender_handle, Mapping):
        sender = str(
            sender_handle.get("handle")
            or sender_handle.get("address")
            or sender_handle.get("id")
            or ""
        )
    else:
        sender = str(
            sender_handle
            or message.get("sender")
            or data.get("sender")
            or message.get("from")
            or data.get("from")
            or ""
        )

    message_id = message.get("id") or message.get("message_id")
    return InboundMessage(
        text="\n".join(texts),
        conversation_id=conversation_id,
        sender=sender,
        message_id=str(message_id) if message_id is not None else None,
        raw=dict(payload),
    )


def _verify_signature(
    secret: str,
    body: bytes,
    headers: Mapping[str, str],
    *,
    now: float | None = None,
) -> bool:
    """Verify Linq's Standard Webhooks HMAC and five-minute replay window."""
    webhook_id = headers.get("webhook-id")
    timestamp = headers.get("webhook-timestamp")
    signatures = headers.get("webhook-signature")
    if not webhook_id or not timestamp or not signatures:
        return False
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    if abs((now if now is not None else time.time()) - sent_at) > 300:
        return False

    encoded_secret = secret.removeprefix("whsec_")
    try:
        key = base64.b64decode(encoded_secret, validate=True)
    except (binascii.Error, ValueError):
        logger.error("LINQ_WEBHOOK_SECRET is not valid base64")
        return False
    signed = (
        webhook_id.encode()
        + b"."
        + timestamp.encode()
        + b"."
        + body
    )
    expected = base64.b64encode(
        hmac.new(key, signed, hashlib.sha256).digest()
    ).decode()
    return any(
        candidate.startswith("v1,")
        and hmac.compare_digest(expected, candidate[3:])
        for candidate in signatures.split()
    )


def create_webhook_router(
    handle_message: Callable[[InboundMessage], Awaitable[str]],
    linq_client: LinqClient,
    *,
    webhook_secret: str | None = None,
) -> APIRouter:
    """Build an unmounted router without depending on demo config or app code."""
    router = APIRouter()
    secret = (
        os.environ.get("LINQ_WEBHOOK_SECRET", "")
        if webhook_secret is None
        else webhook_secret
    )

    @router.post("/linq")
    async def receive_linq_webhook(request: Request) -> dict[str, bool]:
        body = await request.body()
        if secret and not _verify_signature(secret, body, request.headers):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
        if not isinstance(payload, Mapping):
            raise HTTPException(status_code=400, detail="Expected a JSON object")

        message = parse_inbound_message(payload)
        if message is None:
            return {"ok": True}

        reply_text = await handle_message(message)
        if reply_text and reply_text.strip():
            await linq_client.send_reply(
                OutboundReply(
                    conversation_id=message.conversation_id,
                    text=reply_text.strip(),
                )
            )
        return {"ok": True}

    return router


# Kept for compatibility with code that imports ``demo.webhook.router``.
# The application should mount the configured router returned above.
router = APIRouter()


"""Small async client for Linq Partner API v3.

When ``api_key`` is empty, :meth:`LinqClient.send_reply` runs in local stub
mode: it logs the reply and performs no network request.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger("demo.linq_client")


@dataclass(slots=True)
class InboundMessage:
    text: str
    conversation_id: str
    sender: str
    message_id: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class OutboundReply:
    conversation_id: str
    text: str


class LinqClient:
    """Send replies to an existing Linq chat."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.linqapp.com/api/partner/v3",
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self._http_client = http_client
        self.timeout = timeout

    async def send_reply(self, reply: OutboundReply) -> None:
        """Send a text part to ``reply.conversation_id``.

        Linq v3 calls conversations "chats"; the public demo contract retains
        ``conversation_id`` so the rest of the application stays transport
        agnostic.
        """
        if not reply.conversation_id:
            raise ValueError("A Linq conversation_id is required")
        if not reply.text.strip():
            raise ValueError("A non-empty reply text is required")
        if not self.api_key:
            logger.info(
                "[stub] reply to Linq conversation %s: %s",
                reply.conversation_id,
                reply.text,
            )
            return

        url = (
            f"{self.base_url}/chats/"
            f"{quote(reply.conversation_id, safe='')}/messages"
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"parts": [{"type": "text", "value": reply.text}]}

        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Linq rejected reply for conversation %s with HTTP %s: %s",
                reply.conversation_id,
                exc.response.status_code,
                exc.response.text[:500],
            )
            raise RuntimeError(
                "Linq send failed with HTTP "
                f"{exc.response.status_code}: {exc.response.text[:500]}"
            ) from exc
        except httpx.RequestError:
            logger.exception(
                "Linq request failed for conversation %s",
                reply.conversation_id,
            )
            raise
        finally:
            if owns_client:
                await client.aclose()


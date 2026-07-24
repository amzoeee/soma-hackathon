"""Thin async Terac External API client with dry-run mode.

Live endpoints mirror the MCP surface (quote → launch → submissions). Request
bodies are kept minimal and response parsing is schema-tolerant so small API
shape changes do not break the demo.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from demo.config import Settings, get_settings

logger = logging.getLogger("demo.terac.client")


@dataclass
class QuoteResult:
    quote_id: str
    price_usd: float | None = None
    eta_hours: float | None = None
    raw: dict[str, Any] | None = None


@dataclass
class LaunchResult:
    opportunity_id: str
    raw: dict[str, Any] | None = None


@dataclass
class SubmissionSummary:
    status: str
    decision: str | None = None
    guidance: str | None = None
    raw: dict[str, Any] | None = None


class TeracClient:
    """REST client for Terac confirm-then-act opportunities."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.settings = settings or get_settings()
        self._http_client = http_client
        self.timeout = timeout

    @property
    def dry_run(self) -> bool:
        return bool(self.settings.terac_dry_run)

    def _headers(self) -> dict[str, str]:
        key = self.settings.terac_api_key.strip()
        if not key:
            raise RuntimeError("TERAC_API_KEY is required when TERAC_DRY_RUN is false")
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        base = self.settings.terac_base_url.rstrip("/")
        return f"{base}/{path.lstrip('/')}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.request(
                method,
                self._url(path),
                headers=self._headers(),
                json=json_body,
            )
            response.raise_for_status()
            if not response.content:
                return {}
            data = response.json()
            if isinstance(data, dict):
                return data
            return {"data": data}
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Terac %s %s failed with HTTP %s: %s",
                method,
                path,
                exc.response.status_code,
                exc.response.text[:500],
            )
            raise RuntimeError(
                f"Terac request failed with HTTP {exc.response.status_code}: "
                f"{exc.response.text[:500]}"
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

    async def create_quote(
        self,
        *,
        role: str,
        task: str,
        count: int = 1,
    ) -> QuoteResult:
        if self.dry_run:
            quote_id = f"dry_qt_{uuid.uuid4().hex[:10]}"
            logger.info(
                "TERAC_DRY_RUN create_quote role=%r task=%r → %s",
                role,
                task[:120],
                quote_id,
            )
            return QuoteResult(quote_id=quote_id, price_usd=0.0, eta_hours=0.0)

        body: dict[str, Any] = {
            "role": role,
            "task": task,
            "count": count,
        }
        if self.settings.terac_project_id.strip():
            body["project_id"] = self.settings.terac_project_id.strip()

        data = await self._request("POST", "/quotes", json_body=body)
        quote_id = str(
            data.get("quote_id")
            or data.get("id")
            or (data.get("quote") or {}).get("id")
            or ""
        )
        if not quote_id:
            raise RuntimeError(f"Terac quote response missing id: {data!r}")
        price = data.get("price_usd")
        if price is None and isinstance(data.get("pricing"), dict):
            cents = data["pricing"].get("cost_per_participant_cents")
            if cents is not None:
                try:
                    price = float(cents) / 100.0
                except (TypeError, ValueError):
                    price = None
        eta = data.get("eta_hours")
        return QuoteResult(
            quote_id=quote_id,
            price_usd=float(price) if price is not None else None,
            eta_hours=float(eta) if eta is not None else None,
            raw=data,
        )

    async def launch_opportunity(self, quote_id: str) -> LaunchResult:
        if self.dry_run:
            opportunity_id = f"dry_opp_{uuid.uuid4().hex[:10]}"
            logger.info(
                "TERAC_DRY_RUN launch_opportunity quote=%s → %s",
                quote_id,
                opportunity_id,
            )
            return LaunchResult(opportunity_id=opportunity_id)

        data = await self._request(
            "POST",
            "/opportunities/launch",
            json_body={"quote_id": quote_id},
        )
        opportunity_id = str(
            data.get("opportunity_id")
            or data.get("id")
            or (data.get("opportunity") or {}).get("id")
            or ""
        )
        if not opportunity_id:
            raise RuntimeError(
                f"Terac launch response missing opportunity id: {data!r}"
            )
        return LaunchResult(opportunity_id=opportunity_id, raw=data)

    async def get_submissions(self, opportunity_id: str) -> list[SubmissionSummary]:
        if self.dry_run:
            decision = self.settings.terac_dry_run_decision
            status = "APPROVED" if decision == "approve" else "REJECTED"
            return [
                SubmissionSummary(
                    status=status,
                    decision=decision,
                    guidance=f"Dry-run {decision}",
                )
            ]

        data = await self._request(
            "GET",
            f"/opportunities/{opportunity_id}/submissions",
        )
        items: list[Any]
        if isinstance(data.get("submissions"), list):
            items = data["submissions"]
        elif isinstance(data.get("data"), list):
            items = data["data"]
        elif isinstance(data, list):
            items = data
        else:
            items = [data]

        summaries: list[SubmissionSummary] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").upper()
            decision = _extract_decision(item)
            guidance = _extract_guidance(item)
            summaries.append(
                SubmissionSummary(
                    status=status,
                    decision=decision,
                    guidance=guidance,
                    raw=item,
                )
            )
        return summaries


def _extract_decision(item: dict[str, Any]) -> str | None:
    for key in ("decision", "verdict", "recommendation"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    answers = item.get("answers") or item.get("response") or item.get("payload")
    if isinstance(answers, dict):
        for key in ("decision", "verdict", "approve", "approved"):
            value = answers.get(key)
            if isinstance(value, bool):
                return "approve" if value else "reject"
            if isinstance(value, str) and value.strip():
                lowered = value.strip().lower()
                if lowered in {"approve", "approved", "yes", "true"}:
                    return "approve"
                if lowered in {"reject", "rejected", "no", "false"}:
                    return "reject"
                return lowered
    status = str(item.get("status") or "").upper()
    if status in {"APPROVED", "COMPLETE", "COMPLETED"}:
        return "approve"
    if status in {"REJECTED", "DECLINED"}:
        return "reject"
    return None


def _extract_guidance(item: dict[str, Any]) -> str | None:
    for key in ("guidance", "notes", "comment", "feedback", "text"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    answers = item.get("answers") or item.get("response") or item.get("payload")
    if isinstance(answers, dict):
        for key in ("guidance", "notes", "comment", "feedback", "reason"):
            value = answers.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


_client: TeracClient | None = None


def get_terac_client() -> TeracClient:
    global _client
    if _client is None:
        _client = TeracClient()
    return _client

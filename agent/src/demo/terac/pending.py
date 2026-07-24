"""In-memory pending professional confirmations."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

ConfirmationStatus = Literal[
    "pending",
    "approved",
    "rejected",
    "dry_run_approved",
    "dry_run_rejected",
    "executed",
]


@dataclass
class PendingAction:
    confirmation_id: str
    proposed_action: str
    reason: str
    tool_name: str | None = None
    tool_arguments: dict[str, Any] | None = None
    context: str | None = None
    urgency: str = "normal"
    conversation_id: str | None = None
    opportunity_id: str | None = None
    quote_id: str | None = None
    status: ConfirmationStatus = "pending"
    expert_guidance: str | None = None
    approval_consumed: bool = False
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    tool_result: dict[str, Any] | None = None


class PendingStore:
    """Process-local store keyed by confirmation_id and opportunity_id."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, PendingAction] = {}
        self._by_opportunity: dict[str, str] = {}

    def create(
        self,
        *,
        proposed_action: str,
        reason: str,
        tool_name: str | None = None,
        tool_arguments: dict[str, Any] | None = None,
        context: str | None = None,
        urgency: str = "normal",
        conversation_id: str | None = None,
    ) -> PendingAction:
        confirmation_id = f"conf_{uuid.uuid4().hex[:12]}"
        action = PendingAction(
            confirmation_id=confirmation_id,
            proposed_action=proposed_action,
            reason=reason,
            tool_name=tool_name,
            tool_arguments=dict(tool_arguments) if tool_arguments else None,
            context=context,
            urgency=urgency,
            conversation_id=conversation_id,
        )
        with self._lock:
            self._by_id[confirmation_id] = action
        return action

    def get(self, confirmation_id: str) -> PendingAction | None:
        with self._lock:
            return self._by_id.get(confirmation_id)

    def get_by_opportunity(self, opportunity_id: str) -> PendingAction | None:
        with self._lock:
            confirmation_id = self._by_opportunity.get(opportunity_id)
            if not confirmation_id:
                return None
            return self._by_id.get(confirmation_id)

    def bind_opportunity(
        self,
        confirmation_id: str,
        *,
        quote_id: str | None,
        opportunity_id: str,
    ) -> PendingAction | None:
        with self._lock:
            action = self._by_id.get(confirmation_id)
            if action is None:
                return None
            action.quote_id = quote_id
            action.opportunity_id = opportunity_id
            self._by_opportunity[opportunity_id] = confirmation_id
            return action

    def set_status(
        self,
        confirmation_id: str,
        status: ConfirmationStatus,
        *,
        expert_guidance: str | None = None,
        tool_result: dict[str, Any] | None = None,
    ) -> PendingAction | None:
        with self._lock:
            action = self._by_id.get(confirmation_id)
            if action is None:
                return None
            action.status = status
            if expert_guidance is not None:
                action.expert_guidance = expert_guidance
            if tool_result is not None:
                action.tool_result = tool_result
            return action

    def grant_move_approval(self, confirmation_id: str) -> bool:
        """Mark approval usable once by the move_robot gate."""
        with self._lock:
            action = self._by_id.get(confirmation_id)
            if action is None:
                return False
            if action.status not in {"approved", "dry_run_approved"}:
                return False
            action.approval_consumed = False
            return True

    def consume_move_approval(
        self,
        *,
        direction: str,
        distance_meters: float | None = None,
        angle_degrees: float | None = None,
    ) -> PendingAction | None:
        """Consume one unused approval that matches this move (or any move)."""
        with self._lock:
            for action in reversed(list(self._by_id.values())):
                if action.status not in {"approved", "dry_run_approved"}:
                    continue
                if action.approval_consumed:
                    continue
                if action.tool_name and action.tool_name != "move_robot":
                    continue
                if action.tool_arguments:
                    args = action.tool_arguments
                    if args.get("direction") != direction:
                        continue
                    if distance_meters is not None and args.get("distance_meters") is not None:
                        try:
                            if float(args["distance_meters"]) != float(distance_meters):
                                continue
                        except (TypeError, ValueError):
                            continue
                    if angle_degrees is not None and args.get("angle_degrees") is not None:
                        try:
                            if float(args["angle_degrees"]) != float(angle_degrees):
                                continue
                        except (TypeError, ValueError):
                            continue
                action.approval_consumed = True
                return action
            return None

    def clear(self) -> None:
        with self._lock:
            self._by_id.clear()
            self._by_opportunity.clear()


_store: PendingStore | None = None


def get_pending_store() -> PendingStore:
    global _store
    if _store is None:
        _store = PendingStore()
    return _store

"""Request-scoped context for confirm-then-act (Linq chat id, etc.)."""

from __future__ import annotations

from contextvars import ContextVar

current_conversation_id: ContextVar[str | None] = ContextVar(
    "demo_terac_conversation_id",
    default=None,
)


def set_conversation_id(conversation_id: str | None) -> None:
    current_conversation_id.set(conversation_id or None)


def get_conversation_id() -> str | None:
    return current_conversation_id.get()

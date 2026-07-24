"""Demo tool registry for LLM function calling."""

from __future__ import annotations

import inspect
import json
from typing import Any

from demo.config import get_settings
from demo.tools.move_robot import MOVE_ROBOT_SCHEMA, move_robot
from demo.tools.request_professional_confirmation import (
    REQUEST_PROFESSIONAL_CONFIRMATION_SCHEMA,
    request_professional_confirmation,
)

TOOLS: list[dict[str, Any]] = [
    MOVE_ROBOT_SCHEMA,
    REQUEST_PROFESSIONAL_CONFIRMATION_SCHEMA,
]

# Short nudges that may run without Terac when require-confirmation is on.
_NUDGE_METERS = 0.25


def _normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    """Ensure common confirm-then-act fields exist without breaking move_robot."""
    out = dict(result)
    out.setdefault("needs_human", False)
    if "data" not in out:
        out["data"] = None
    return out


def _move_requires_confirmation(
    direction: str,
    distance_meters: float | None,
) -> bool:
    settings = get_settings()
    if not settings.terac_require_confirmation:
        return False
    if direction in {"stop", "open", "close"}:
        return False
    if direction in {"forward", "backward", "up", "down"} and distance_meters is not None:
        try:
            if float(distance_meters) <= _NUDGE_METERS:
                return False
        except (TypeError, ValueError):
            pass
    if direction in {
        "left",
        "right",
        "tilt_up",
        "tilt_down",
        "roll_left",
        "roll_right",
    }:
        return False
    return True


def execute_tool(
    name: str,
    arguments: dict | str,
    *,
    bypass_confirmation: bool = False,
) -> dict[str, Any] | Any:
    """Run a registered tool by name. Accepts a dict or JSON string for arguments.

    May return an awaitable for async tools (e.g. Terac confirmation).
    """
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return {
                "ok": False,
                "printed": "",
                "message": f"Invalid tool arguments JSON: {arguments!r}",
                "needs_human": False,
                "data": None,
            }

    if not isinstance(arguments, dict):
        return {
            "ok": False,
            "printed": "",
            "message": (
                f"Tool arguments must be a dict or JSON string, "
                f"got {type(arguments).__name__}"
            ),
            "needs_human": False,
            "data": None,
        }

    if name == "move_robot":
        direction = arguments.get("direction")
        distance = arguments.get("distance_meters")
        angle = arguments.get("angle_degrees")
        if (
            not bypass_confirmation
            and isinstance(direction, str)
            and _move_requires_confirmation(direction, distance)
        ):
            from demo.terac.pending import get_pending_store

            approved = get_pending_store().consume_move_approval(
                direction=direction,
                distance_meters=float(distance) if distance is not None else None,
                angle_degrees=float(angle) if angle is not None else None,
            )
            if approved is None:
                return {
                    "ok": False,
                    "printed": "",
                    "message": (
                        "This movement requires professional confirmation. "
                        "Call request_professional_confirmation with the "
                        "proposed action first; do not claim the robot moved."
                    ),
                    "needs_human": True,
                    "data": {"requires_confirmation": True},
                }
        return _normalize_result(move_robot(**arguments))

    if name == "request_professional_confirmation":
        return request_professional_confirmation(**arguments)

    return {
        "ok": False,
        "printed": "",
        "message": f"Unknown tool: {name}",
        "needs_human": False,
        "data": None,
    }


async def execute_tool_async(
    name: str,
    arguments: dict | str,
    *,
    bypass_confirmation: bool = False,
) -> dict[str, Any]:
    """Async wrapper that awaits async tools."""
    result = execute_tool(
        name,
        arguments,
        bypass_confirmation=bypass_confirmation,
    )
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, dict):
        return {
            "ok": False,
            "printed": "",
            "message": "Tool execution returned a non-dict result",
            "needs_human": False,
            "data": None,
        }
    return _normalize_result(result)

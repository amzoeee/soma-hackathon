"""Parse free-text proposed actions into tool name + arguments."""

from __future__ import annotations

import re
from typing import Any


def parse_proposed_action(proposed_action: str) -> tuple[str | None, dict[str, Any] | None]:
    """Best-effort parse of strings like ``move_robot forward 2m``."""
    text = (proposed_action or "").strip()
    if not text:
        return None, None

    lowered = text.lower()
    # Explicit tool prefix
    if lowered.startswith("move_robot"):
        rest = text[len("move_robot") :].strip(" :,-")
        return "move_robot", _parse_move_args(rest)

    if re.search(r"\bstop\b", lowered):
        return "move_robot", {"direction": "stop"}

    move = re.search(
        r"\b(?:move\s+)?(forward|backward)\b(?:\s+(?:by\s+)?)?(\d+(?:\.\d+)?)\s*(m|meters?|metres?)?",
        lowered,
    )
    if move:
        return "move_robot", {
            "direction": move.group(1),
            "distance_meters": float(move.group(2)),
        }

    turn = re.search(
        r"\b(?:turn\s+)?(left|right)\b(?:\s+(?:by\s+)?)?(\d+(?:\.\d+)?)?\s*(deg|degrees?)?",
        lowered,
    )
    if turn:
        args: dict[str, Any] = {"direction": turn.group(1)}
        if turn.group(2):
            args["angle_degrees"] = float(turn.group(2))
        return "move_robot", args

    return None, None


def _parse_move_args(rest: str) -> dict[str, Any] | None:
    if not rest:
        return None
    lowered = rest.lower().strip()
    if lowered == "stop" or lowered.startswith("stop "):
        return {"direction": "stop"}

    parts = lowered.replace(",", " ").split()
    if not parts:
        return None
    direction = parts[0]
    if direction not in {"forward", "backward", "left", "right", "stop"}:
        return None
    args: dict[str, Any] = {"direction": direction}
    if direction in {"forward", "backward"} and len(parts) >= 2:
        num = re.match(r"(\d+(?:\.\d+)?)", parts[1])
        if num:
            args["distance_meters"] = float(num.group(1))
    if direction in {"left", "right"} and len(parts) >= 2:
        num = re.match(r"(\d+(?:\.\d+)?)", parts[1])
        if num:
            args["angle_degrees"] = float(num.group(1))
    return args

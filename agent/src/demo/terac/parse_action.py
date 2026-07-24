"""Parse free-text proposed actions into tool name + arguments."""

from __future__ import annotations

import re
from typing import Any

_ALL_DIRS = {
    "forward",
    "backward",
    "up",
    "down",
    "left",
    "right",
    "tilt_up",
    "tilt_down",
    "roll_left",
    "roll_right",
    "open",
    "close",
    "stop",
}
_TRANSLATION = {"forward", "backward", "up", "down"}
_ANGLE = {"left", "right", "tilt_up", "tilt_down", "roll_left", "roll_right"}


def parse_proposed_action(proposed_action: str) -> tuple[str | None, dict[str, Any] | None]:
    """Best-effort parse of strings like ``move_robot forward 2m``."""
    text = (proposed_action or "").strip()
    if not text:
        return None, None

    lowered = text.lower()
    if lowered.startswith("move_robot"):
        rest = text[len("move_robot") :].strip(" :,-")
        return "move_robot", _parse_move_args(rest)

    if re.search(r"\bstop\b", lowered):
        return "move_robot", {"direction": "stop"}

    if re.search(r"\b(open|close)\b", lowered) and re.search(
        r"\b(gripper|claw|hand|grip)\b", lowered
    ):
        return "move_robot", {"direction": "open" if "open" in lowered else "close"}

    move = re.search(
        r"\b(?:move\s+)?(forward|backward|up|down)\b(?:\s+(?:by\s+)?)?(\d+(?:\.\d+)?)\s*(m|meters?|metres?)?",
        lowered,
    )
    if move:
        return "move_robot", {
            "direction": move.group(1),
            "distance_meters": float(move.group(2)),
        }

    if re.search(r"\b(raise|lift|arm\s+up|move\s+up)\b", lowered):
        return "move_robot", {"direction": "up", "distance_meters": 0.2}
    if re.search(r"\b(lower|arm\s+down|move\s+down)\b", lowered):
        return "move_robot", {"direction": "down", "distance_meters": 0.2}

    wrist = re.search(
        r"\b(?:wrist\s+)?(tilt_up|tilt_down|roll_left|roll_right|tilt\s+up|tilt\s+down|roll\s+left|roll\s+right)\b"
        r"(?:\s+(?:by\s+)?)?(\d+(?:\.\d+)?)?\s*(deg|degrees?)?",
        lowered,
    )
    if wrist:
        raw = wrist.group(1).replace(" ", "_")
        args: dict[str, Any] = {"direction": raw}
        if wrist.group(2):
            args["angle_degrees"] = float(wrist.group(2))
        return "move_robot", args

    turn = re.search(
        r"\b(?:turn\s+)?(left|right)\b(?:\s+(?:by\s+)?)?(\d+(?:\.\d+)?)?\s*(deg|degrees?)?",
        lowered,
    )
    if turn:
        args = {"direction": turn.group(1)}
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

    lowered = (
        lowered.replace("tilt up", "tilt_up")
        .replace("tilt down", "tilt_down")
        .replace("roll left", "roll_left")
        .replace("roll right", "roll_right")
    )

    parts = lowered.replace(",", " ").split()
    if not parts:
        return None
    direction = parts[0]
    if direction not in _ALL_DIRS:
        return None
    args: dict[str, Any] = {"direction": direction}
    if direction in _TRANSLATION and len(parts) >= 2:
        num = re.match(r"(\d+(?:\.\d+)?)", parts[1])
        if num:
            args["distance_meters"] = float(num.group(1))
        else:
            args["distance_meters"] = 0.2
    elif direction in _TRANSLATION:
        args["distance_meters"] = 0.2
    if direction in _ANGLE and len(parts) >= 2:
        num = re.match(r"(\d+(?:\.\d+)?)", parts[1])
        if num:
            args["angle_degrees"] = float(num.group(1))
    return args

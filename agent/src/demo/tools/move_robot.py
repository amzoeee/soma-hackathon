"""Temporary move_robot tool — prints simulated movement; swap for real robot later."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("demo.tools.move_robot")

VALID_DIRECTIONS = frozenset({"forward", "backward", "left", "right", "stop"})
DEFAULT_TURN_DEGREES = 90.0

MOVE_ROBOT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "move_robot",
        "description": (
            "Command the robot to move forward/backward, turn left/right, or stop. "
            "Use distance_meters for forward/backward; angle_degrees is optional for turns "
            f"(defaults to {int(DEFAULT_TURN_DEGREES)})."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["forward", "backward", "left", "right", "stop"],
                    "description": "Movement direction or stop.",
                },
                "distance_meters": {
                    "type": "number",
                    "description": "Distance in meters; required for forward and backward.",
                },
                "angle_degrees": {
                    "type": "number",
                    "description": "Turn angle in degrees; optional for left/right.",
                },
            },
            "required": ["direction"],
            "additionalProperties": False,
        },
    },
}


def _fail(message: str) -> dict[str, Any]:
    return {"ok": False, "printed": "", "message": message}


def move_robot(
    direction: str,
    distance_meters: float | None = None,
    angle_degrees: float | None = None,
) -> dict[str, Any]:
    """Print the intended movement and return a stable tool-result dict.

    Future swap point: replace the print below with a call to the robot team's
    Python function or HTTP API. Keep this signature and return shape unchanged.
    """
    if not isinstance(direction, str) or direction not in VALID_DIRECTIONS:
        return _fail(
            f"Unknown direction {direction!r}. "
            f"Use one of: {', '.join(sorted(VALID_DIRECTIONS))}."
        )

    if direction in ("forward", "backward"):
        if distance_meters is None:
            return _fail(f"distance_meters is required for direction={direction!r}.")
        try:
            distance = float(distance_meters)
        except (TypeError, ValueError):
            return _fail(f"distance_meters must be a number, got {distance_meters!r}.")
        if distance <= 0:
            return _fail("distance_meters must be greater than 0.")

        printed = f"ROBOT: move {direction} {distance:g}m"
        message = f"Moving {direction} {distance:g} meters"
    elif direction in ("left", "right"):
        if angle_degrees is None:
            angle = DEFAULT_TURN_DEGREES
        else:
            try:
                angle = float(angle_degrees)
            except (TypeError, ValueError):
                return _fail(f"angle_degrees must be a number, got {angle_degrees!r}.")
        printed = f"ROBOT: turn {direction} {angle:g}deg"
        message = f"Turning {direction} {angle:g} degrees"
    else:  # stop
        printed = "ROBOT: stop"
        message = "Stopping"

    # Future swap point: call robot HTTP API / Python SDK here instead of print.
    print(printed)
    logger.info(printed)
    return {"ok": True, "printed": printed, "message": message}

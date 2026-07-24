"""move_robot tool — prints intended motion; drives calibrated SO-101 when enabled."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("demo.tools.move_robot")

TRANSLATION_DIRECTIONS = frozenset({"forward", "backward", "up", "down"})
TURN_DIRECTIONS = frozenset({"left", "right"})
WRIST_DIRECTIONS = frozenset({"tilt_up", "tilt_down", "roll_left", "roll_right"})
GRIPPER_DIRECTIONS = frozenset({"open", "close"})
VALID_DIRECTIONS = (
    TRANSLATION_DIRECTIONS
    | TURN_DIRECTIONS
    | WRIST_DIRECTIONS
    | GRIPPER_DIRECTIONS
    | frozenset({"stop"})
)

DEFAULT_TURN_DEGREES = 30.0
DEFAULT_WRIST_DEGREES = 20.0

MOVE_ROBOT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "move_robot",
        "description": (
            "Command the calibrated SO-101 robot arm. "
            "Translations need distance_meters: forward/backward (elbow reach), "
            "up/down (shoulder lift). "
            f"Turns use optional angle_degrees (default {int(DEFAULT_TURN_DEGREES)}): left/right. "
            f"Wrist uses optional angle_degrees (default {int(DEFAULT_WRIST_DEGREES)}): "
            "tilt_up/tilt_down/roll_left/roll_right. "
            "Gripper: open/close. stop holds the current pose."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": sorted(VALID_DIRECTIONS),
                    "description": (
                        "forward/backward/up/down/left/right/"
                        "tilt_up/tilt_down/roll_left/roll_right/open/close/stop"
                    ),
                },
                "distance_meters": {
                    "type": "number",
                    "description": "Required for forward, backward, up, down.",
                },
                "angle_degrees": {
                    "type": "number",
                    "description": "Optional for left/right and wrist tilt/roll.",
                },
            },
            "required": ["direction"],
            "additionalProperties": False,
        },
    },
}


def _fail(message: str) -> dict[str, Any]:
    return {"ok": False, "printed": "", "message": message}


def _drive_hardware(
    direction: str,
    distance_meters: float | None,
    angle_degrees: float | None,
) -> tuple[bool, str]:
    from demo.config import get_settings
    from demo.hardware.so101 import apply_move

    settings = get_settings()
    if not settings.robot_enabled:
        return True, "hardware disabled (print-only)"

    try:
        result = apply_move(
            port=settings.robot_port,
            direction=direction,
            distance_meters=distance_meters,
            angle_degrees=angle_degrees,
            calibration_path=settings.robot_calibration_path or None,
            urdf_path=settings.robot_urdf_path or None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("SO-101 move failed")
        return False, f"hardware error: {exc}"

    if not result.get("ok"):
        return False, str(result.get("detail") or "hardware rejected command")
    return True, str(result.get("detail") or "ok")


def _parse_positive_distance(distance_meters: object, direction: str) -> float | dict[str, Any]:
    if distance_meters is None:
        return _fail(f"distance_meters is required for direction={direction!r}.")
    try:
        distance = float(distance_meters)
    except (TypeError, ValueError):
        return _fail(f"distance_meters must be a number, got {distance_meters!r}.")
    if distance <= 0:
        return _fail("distance_meters must be greater than 0.")
    return distance


def _parse_angle(angle_degrees: object, default: float) -> float | dict[str, Any]:
    if angle_degrees is None:
        return default
    try:
        return float(angle_degrees)
    except (TypeError, ValueError):
        return _fail(f"angle_degrees must be a number, got {angle_degrees!r}.")


def move_robot(
    direction: str,
    distance_meters: float | None = None,
    angle_degrees: float | None = None,
) -> dict[str, Any]:
    if not isinstance(direction, str) or direction not in VALID_DIRECTIONS:
        return _fail(
            f"Unknown direction {direction!r}. "
            f"Use one of: {', '.join(sorted(VALID_DIRECTIONS))}."
        )

    hw_distance: float | None = None
    hw_angle: float | None = None

    if direction in TRANSLATION_DIRECTIONS:
        parsed = _parse_positive_distance(distance_meters, direction)
        if isinstance(parsed, dict):
            return parsed
        distance = parsed
        printed = f"ROBOT: move {direction} {distance:g}m"
        message = f"Moving {direction} {distance:g} meters"
        hw_distance = distance
    elif direction in TURN_DIRECTIONS:
        parsed = _parse_angle(angle_degrees, DEFAULT_TURN_DEGREES)
        if isinstance(parsed, dict):
            return parsed
        angle = parsed
        printed = f"ROBOT: turn {direction} {angle:g}deg"
        message = f"Turning {direction} {angle:g} degrees"
        hw_angle = angle
    elif direction in WRIST_DIRECTIONS:
        parsed = _parse_angle(angle_degrees, DEFAULT_WRIST_DEGREES)
        if isinstance(parsed, dict):
            return parsed
        angle = parsed
        printed = f"ROBOT: wrist {direction} {angle:g}deg"
        message = f"Wrist {direction.replace('_', ' ')} {angle:g} degrees"
        hw_angle = angle
    elif direction in GRIPPER_DIRECTIONS:
        printed = f"ROBOT: gripper {direction}"
        message = f"Gripper {direction}"
    else:
        printed = "ROBOT: stop"
        message = "Stopping"

    print(printed)
    logger.info(printed)

    ok, detail = _drive_hardware(direction, hw_distance, hw_angle)
    if not ok:
        return {
            "ok": False,
            "printed": printed,
            "message": f"{message} — but hardware failed: {detail}",
        }

    if detail and detail != "hardware disabled (print-only)":
        logger.info("SO-101 applied: %s", detail)
        message = f"{message} (real arm)"

    return {"ok": True, "printed": printed, "message": message}

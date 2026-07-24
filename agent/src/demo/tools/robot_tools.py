"""Explicit, deterministic tools for the calibrated SO-101 robot arm."""

from __future__ import annotations

import logging
import math
from typing import Any

from demo.config import get_settings

logger = logging.getLogger("demo.tools.robot")

MIN_WRIST_DEGREES = -160.0
MAX_WRIST_DEGREES = 160.0

MOVE_CARTESIAN_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "move_cartesian",
        "description": (
            "Move the end effector by an XYZ differential using inverse kinematics. "
            "Coordinates are meters: +x right, -x left, +y forward, -y backward, "
            "+z up, -z down. Supply all three axes, using 0 for unchanged axes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "delta_x_m": {
                    "type": "number",
                    "description": "Right/left differential in meters.",
                },
                "delta_y_m": {
                    "type": "number",
                    "description": "Forward/backward differential in meters.",
                },
                "delta_z_m": {
                    "type": "number",
                    "description": "Up/down differential in meters.",
                },
            },
            "required": ["delta_x_m", "delta_y_m", "delta_z_m"],
            "additionalProperties": False,
        },
    },
}

MOVE_WRIST_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "move_wrist",
        "description": (
            "Move both wrist motors by differential angles. Positive pitch tilts "
            "up; negative pitch tilts down. Positive roll rotates right; negative "
            "roll rotates left. Each differential must be from -160 to +160 degrees. "
            "Supply both values, using 0 for an unchanged motor."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pitch_degrees": {
                    "type": "number",
                    "minimum": MIN_WRIST_DEGREES,
                    "maximum": MAX_WRIST_DEGREES,
                },
                "roll_degrees": {
                    "type": "number",
                    "minimum": MIN_WRIST_DEGREES,
                    "maximum": MAX_WRIST_DEGREES,
                },
            },
            "required": ["pitch_degrees", "roll_degrees"],
            "additionalProperties": False,
        },
    },
}

SET_GRIPPER_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "set_gripper",
        "description": "Set the gripper to its calibrated fully open or fully closed position.",
        "parameters": {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "enum": ["open", "closed"],
                }
            },
            "required": ["state"],
            "additionalProperties": False,
        },
    },
}

HOLD_POSITION_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "hold_position",
        "description": "Stop motion and hold the robot's current pose.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
}


def _result(
    *,
    ok: bool,
    tool: str,
    message: str,
    arguments: dict[str, Any],
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "tool": tool,
        "arguments": arguments,
        "message": message,
        "data": data,
    }


def _finite_number(value: object, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _format_signed(value: float, unit: str) -> str:
    return f"{value:+g}{unit}"


def _format_xyz(values: tuple[float, float, float]) -> str:
    x, y, z = values
    return (
        f"Δx={_format_signed(x, 'm')}, "
        f"Δy={_format_signed(y, 'm')}, "
        f"Δz={_format_signed(z, 'm')}"
    )


def _hardware_enabled() -> bool:
    return get_settings().robot_enabled


def move_cartesian(
    delta_x_m: float,
    delta_y_m: float,
    delta_z_m: float,
) -> dict[str, Any]:
    """Apply one XYZ differential through IK."""
    tool = "move_cartesian"
    try:
        requested = (
            _finite_number(delta_x_m, "delta_x_m"),
            _finite_number(delta_y_m, "delta_y_m"),
            _finite_number(delta_z_m, "delta_z_m"),
        )
    except ValueError as exc:
        return _result(
            ok=False,
            tool=tool,
            arguments={
                "delta_x_m": delta_x_m,
                "delta_y_m": delta_y_m,
                "delta_z_m": delta_z_m,
            },
            message=str(exc),
        )

    arguments = {
        "delta_x_m": requested[0],
        "delta_y_m": requested[1],
        "delta_z_m": requested[2],
    }
    if all(abs(value) < 1e-9 for value in requested):
        return _result(
            ok=False,
            tool=tool,
            arguments=arguments,
            message="Cartesian differential must change at least one axis.",
        )

    print(f"ROBOT: cartesian {_format_xyz(requested)}")
    logger.info("ROBOT: cartesian %s", _format_xyz(requested))

    if not _hardware_enabled():
        return _result(
            ok=True,
            tool=tool,
            arguments=arguments,
            message=f"Cartesian IK requested {_format_xyz(requested)} (simulation).",
            data={"requested_delta_xyz": requested, "applied_delta_xyz": None},
        )

    from demo.hardware.so101 import apply_cartesian_delta

    settings = get_settings()
    try:
        result = apply_cartesian_delta(
            port=settings.robot_port,
            delta_x_m=requested[0],
            delta_y_m=requested[1],
            delta_z_m=requested[2],
            calibration_path=settings.robot_calibration_path or None,
            urdf_path=settings.robot_urdf_path or None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("SO-101 Cartesian move failed")
        return _result(
            ok=False,
            tool=tool,
            arguments=arguments,
            message=f"Cartesian IK failed: {exc}",
        )

    detail = result.get("detail") if isinstance(result, dict) else None
    if not isinstance(detail, dict):
        detail = {}
    if not result.get("ok"):
        return _result(
            ok=False,
            tool=tool,
            arguments=arguments,
            message=f"Cartesian IK failed: {detail.get('error', 'hardware rejected command')}",
            data=detail,
        )

    applied_raw = detail.get("applied_delta_xyz")
    applied = (
        tuple(float(value) for value in applied_raw)
        if isinstance(applied_raw, (list, tuple)) and len(applied_raw) == 3
        else requested
    )
    limited = any(abs(applied[index] - requested[index]) > 1e-4 for index in range(3))
    message = f"Cartesian IK applied {_format_xyz(applied)}."
    if limited:
        message = (
            f"Cartesian IK requested {_format_xyz(requested)}; "
            f"applied {_format_xyz(applied)} (safety/workspace limited)."
        )
    return _result(
        ok=True,
        tool=tool,
        arguments=arguments,
        message=message,
        data=detail,
    )


def move_wrist(
    pitch_degrees: float,
    roll_degrees: float,
) -> dict[str, Any]:
    """Move wrist pitch and roll by bounded differential angles."""
    tool = "move_wrist"
    try:
        pitch = _finite_number(pitch_degrees, "pitch_degrees")
        roll = _finite_number(roll_degrees, "roll_degrees")
    except ValueError as exc:
        return _result(
            ok=False,
            tool=tool,
            arguments={
                "pitch_degrees": pitch_degrees,
                "roll_degrees": roll_degrees,
            },
            message=str(exc),
        )
    arguments = {"pitch_degrees": pitch, "roll_degrees": roll}
    for name, value in arguments.items():
        if value < MIN_WRIST_DEGREES or value > MAX_WRIST_DEGREES:
            return _result(
                ok=False,
                tool=tool,
                arguments=arguments,
                message=f"{name} must be between -160 and +160 degrees.",
            )
    if abs(pitch) < 1e-9 and abs(roll) < 1e-9:
        return _result(
            ok=False,
            tool=tool,
            arguments=arguments,
            message="Wrist differential must move pitch, roll, or both.",
        )

    requested_text = (
        f"pitch={_format_signed(pitch, '°')}, "
        f"roll={_format_signed(roll, '°')}"
    )
    print(f"ROBOT: wrist {requested_text}")
    logger.info("ROBOT: wrist %s", requested_text)

    if not _hardware_enabled():
        return _result(
            ok=True,
            tool=tool,
            arguments=arguments,
            message=f"Wrist differential applied {requested_text} (simulation).",
            data={"requested": arguments, "applied": None},
        )

    from demo.hardware.so101 import apply_wrist_delta

    settings = get_settings()
    try:
        result = apply_wrist_delta(
            port=settings.robot_port,
            pitch_degrees=pitch,
            roll_degrees=roll,
            calibration_path=settings.robot_calibration_path or None,
            urdf_path=settings.robot_urdf_path or None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("SO-101 wrist move failed")
        return _result(
            ok=False,
            tool=tool,
            arguments=arguments,
            message=f"Wrist move failed: {exc}",
        )

    detail = result.get("detail") if isinstance(result, dict) else None
    if not result.get("ok"):
        return _result(
            ok=False,
            tool=tool,
            arguments=arguments,
            message=f"Wrist move failed: {detail or 'hardware rejected command'}",
            data=detail if isinstance(detail, dict) else None,
        )
    applied = detail.get("applied", {}) if isinstance(detail, dict) else {}
    applied_pitch = float(applied.get("pitch_degrees", pitch))
    applied_roll = float(applied.get("roll_degrees", roll))
    applied_text = (
        f"pitch={_format_signed(applied_pitch, '°')}, "
        f"roll={_format_signed(applied_roll, '°')}"
    )
    limited = (
        abs(applied_pitch - pitch) > 1.0
        or abs(applied_roll - roll) > 1.0
    )
    message = f"Wrist differential applied {applied_text}."
    if limited:
        message = (
            f"Wrist differential requested {requested_text}; "
            f"applied {applied_text} (calibration limited)."
        )
    return _result(
        ok=True,
        tool=tool,
        arguments=arguments,
        message=message,
        data=detail if isinstance(detail, dict) else None,
    )


def set_gripper(state: str) -> dict[str, Any]:
    """Set the gripper to a calibrated endpoint."""
    tool = "set_gripper"
    normalized = str(state).strip().lower()
    arguments = {"state": normalized}
    if normalized not in {"open", "closed"}:
        return _result(
            ok=False,
            tool=tool,
            arguments=arguments,
            message="Gripper state must be 'open' or 'closed'.",
        )

    print(f"ROBOT: gripper {normalized}")
    logger.info("ROBOT: gripper %s", normalized)
    if not _hardware_enabled():
        return _result(
            ok=True,
            tool=tool,
            arguments=arguments,
            message=f"Gripper set to {normalized} (simulation).",
        )

    from demo.hardware.so101 import apply_gripper_state

    settings = get_settings()
    try:
        result = apply_gripper_state(
            port=settings.robot_port,
            state=normalized,
            calibration_path=settings.robot_calibration_path or None,
            urdf_path=settings.robot_urdf_path or None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("SO-101 gripper command failed")
        return _result(
            ok=False,
            tool=tool,
            arguments=arguments,
            message=f"Gripper command failed: {exc}",
        )
    detail = result.get("detail") if isinstance(result, dict) else None
    if not result.get("ok"):
        return _result(
            ok=False,
            tool=tool,
            arguments=arguments,
            message=f"Gripper command failed: {detail or 'hardware rejected command'}",
            data=detail if isinstance(detail, dict) else None,
        )
    return _result(
        ok=True,
        tool=tool,
        arguments=arguments,
        message=f"Gripper set to {normalized}.",
        data=detail if isinstance(detail, dict) else None,
    )


def hold_position() -> dict[str, Any]:
    """Hold the current pose."""
    tool = "hold_position"
    if not _hardware_enabled():
        return _result(
            ok=True,
            tool=tool,
            arguments={},
            message="Robot hold requested (simulation).",
        )

    from demo.hardware.so101 import apply_hold_position

    settings = get_settings()
    try:
        result = apply_hold_position(
            port=settings.robot_port,
            calibration_path=settings.robot_calibration_path or None,
            urdf_path=settings.robot_urdf_path or None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("SO-101 hold failed")
        return _result(
            ok=False,
            tool=tool,
            arguments={},
            message=f"Robot hold failed: {exc}",
        )
    detail = result.get("detail") if isinstance(result, dict) else None
    if not result.get("ok"):
        return _result(
            ok=False,
            tool=tool,
            arguments={},
            message=f"Robot hold failed: {detail or 'hardware rejected command'}",
            data=detail if isinstance(detail, dict) else None,
        )
    return _result(
        ok=True,
        tool=tool,
        arguments={},
        message="Robot is holding its current pose.",
        data=detail if isinstance(detail, dict) else None,
    )

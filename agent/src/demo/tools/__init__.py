"""Deterministic robot tool registry."""

from __future__ import annotations

import json
from typing import Any, Callable

from demo.tools.robot_tools import (
    HOLD_POSITION_SCHEMA,
    MOVE_CARTESIAN_SCHEMA,
    MOVE_WRIST_SCHEMA,
    SET_GRIPPER_SCHEMA,
    hold_position,
    move_cartesian,
    move_wrist,
    set_gripper,
)

TOOLS: list[dict[str, Any]] = [
    MOVE_CARTESIAN_SCHEMA,
    MOVE_WRIST_SCHEMA,
    SET_GRIPPER_SCHEMA,
    HOLD_POSITION_SCHEMA,
]

TOOL_FUNCTIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "move_cartesian": move_cartesian,
    "move_wrist": move_wrist,
    "set_gripper": set_gripper,
    "hold_position": hold_position,
}


def _failure(
    name: str,
    arguments: object,
    message: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": name,
        "arguments": arguments if isinstance(arguments, dict) else {},
        "message": message,
        "data": None,
    }


def execute_tool(name: str, arguments: dict | str) -> dict[str, Any]:
    """Execute one registered tool and return a uniform result."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return _failure(name, {}, "Tool arguments were not valid JSON.")
    if not isinstance(arguments, dict):
        return _failure(name, {}, "Tool arguments must be a JSON object.")

    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        return _failure(name, arguments, f"Unknown robot tool: {name}.")
    try:
        return function(**arguments)
    except TypeError as exc:
        return _failure(name, arguments, f"Invalid arguments for {name}: {exc}")

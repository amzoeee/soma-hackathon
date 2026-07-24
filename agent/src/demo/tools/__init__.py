"""Demo tool registry for LLM function calling."""

from __future__ import annotations

import json
from typing import Any

from demo.tools.move_robot import MOVE_ROBOT_SCHEMA, move_robot

TOOLS: list[dict[str, Any]] = [MOVE_ROBOT_SCHEMA]


def execute_tool(name: str, arguments: dict | str) -> dict[str, Any]:
    """Run a registered tool by name. Accepts a dict or JSON string for arguments."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return {
                "ok": False,
                "printed": "",
                "message": f"Invalid tool arguments JSON: {arguments!r}",
            }

    if not isinstance(arguments, dict):
        return {
            "ok": False,
            "printed": "",
            "message": f"Tool arguments must be a dict or JSON string, got {type(arguments).__name__}",
        }

    if name == "move_robot":
        return move_robot(**arguments)

    return {"ok": False, "printed": "", "message": f"Unknown tool: {name}"}

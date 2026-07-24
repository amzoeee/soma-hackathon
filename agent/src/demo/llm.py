"""Plan and execute an ordered robot-tool sequence with Runware."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .prompts import SYSTEM_PROMPT

logger = logging.getLogger("demo.llm")

DEFAULT_BASE_URL = "https://api.runware.ai/v1"
DEFAULT_MODEL = "gpt-5.6-luna"
MAX_TOOL_CALLS = 32


def _load_openai_client() -> type:
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise RuntimeError("The 'openai' package is required to call Runware") from exc
    return AsyncOpenAI


def _load_tool_registry() -> tuple[list[dict[str, Any]], Any]:
    try:
        from demo.tools import TOOLS, execute_tool
    except ImportError as exc:
        raise RuntimeError("demo.tools is not available") from exc
    return TOOLS, execute_tool


def _planning_failure(message: str, *, tool: str = "planner") -> dict[str, Any]:
    return {
        "ok": False,
        "tool": tool,
        "arguments": {},
        "message": message,
        "data": None,
    }


async def interpret_and_call_tools(text: str) -> list[dict[str, Any]]:
    """Plan once, then execute every returned tool call sequentially.

    Model-authored prose is intentionally ignored. The caller formats replies
    exclusively from these structured tool results.
    """
    if not text or not text.strip():
        return []

    api_key = os.environ.get("RUNWARE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("RUNWARE_API_KEY is required")
    base_url = os.environ.get("RUNWARE_BASE_URL", DEFAULT_BASE_URL).strip()
    model = os.environ.get("RUNWARE_MODEL", DEFAULT_MODEL).strip()

    tools, execute_tool = _load_tool_registry()
    client_type = _load_openai_client()
    client = client_type(api_key=api_key, base_url=base_url)
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text.strip()},
        ],
        tools=tools,
        tool_choice="auto",
        reasoning_effort="none",
    )
    if not response.choices:
        raise RuntimeError("Runware returned no completion choices")

    calls = list(response.choices[0].message.tool_calls or [])
    if len(calls) > MAX_TOOL_CALLS:
        return [
            _planning_failure(
                f"Sequence has {len(calls)} actions; maximum is {MAX_TOOL_CALLS}."
            )
        ]

    results: list[dict[str, Any]] = []
    for index, call in enumerate(calls, start=1):
        name = str(call.function.name or "")
        raw_arguments = call.function.arguments or "{}"
        arguments: dict[str, Any] = {}
        try:
            arguments = json.loads(raw_arguments)
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be a JSON object")
        except (json.JSONDecodeError, ValueError) as exc:
            arguments = {}
            result = _planning_failure(
                f"Step {index} has invalid arguments: {exc}",
                tool=name or "unknown",
            )
        else:
            logger.info(
                "Executing robot step %d/%d: %s %s",
                index,
                len(calls),
                name,
                arguments,
            )
            result = execute_tool(name, arguments)
            if not isinstance(result, dict):
                result = _planning_failure(
                    f"Step {index} returned an invalid result.",
                    tool=name or "unknown",
                )

        normalized = dict(result)
        normalized.setdefault("tool", name or "unknown")
        normalized.setdefault("arguments", arguments)
        normalized.setdefault("message", "No result message.")
        normalized.setdefault("data", None)
        normalized["step"] = index
        normalized["sequence_total"] = len(calls)
        results.append(normalized)
        if not normalized.get("ok"):
            logger.warning("Robot sequence stopped at failed step %d", index)
            break

    return results

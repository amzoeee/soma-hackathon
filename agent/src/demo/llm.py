"""Runware/OpenAI-compatible movement interpretation and tool execution."""

from __future__ import annotations

import inspect
import json
import logging
import os
from typing import Any

from .prompts import SYSTEM_PROMPT

logger = logging.getLogger("demo.llm")

DEFAULT_BASE_URL = "https://api.runware.ai/v1"
DEFAULT_MODEL = "gpt-5.6-luna"
MAX_TOOL_ROUNDS = 3


def _load_openai_client() -> type:
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise RuntimeError(
            "The 'openai' package is required to call Runware"
        ) from exc
    return AsyncOpenAI


def _load_tool_registry() -> tuple[list[dict[str, Any]], Any]:
    try:
        from demo.tools import TOOLS, execute_tool
    except ImportError as exc:
        raise RuntimeError(
            "demo.tools is not available yet; task 4 must provide TOOLS and "
            "execute_tool before LLM tool execution can run"
        ) from exc
    return TOOLS, execute_tool


def _message_to_dict(message: Any) -> dict[str, Any]:
    """Keep only fields accepted when replaying an assistant tool-call turn."""
    tool_calls = []
    for call in message.tool_calls or []:
        tool_calls.append(
            {
                "id": call.id,
                "type": call.type or "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
        )
    result: dict[str, Any] = {
        "role": "assistant",
        "content": message.content,
    }
    if tool_calls:
        result["tool_calls"] = tool_calls
    return result


async def interpret_and_call_tools(text: str) -> tuple[str, list[dict]]:
    """Interpret operator text, execute movement tools, and return confirmation."""
    if not text or not text.strip():
        return "Please provide a robot movement command.", []

    api_key = os.environ.get("RUNWARE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("RUNWARE_API_KEY is required")
    base_url = os.environ.get("RUNWARE_BASE_URL", DEFAULT_BASE_URL).strip()
    model = os.environ.get("RUNWARE_MODEL", DEFAULT_MODEL).strip()

    tools, execute_tool = _load_tool_registry()
    client_type = _load_openai_client()
    client = client_type(api_key=api_key, base_url=base_url)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text.strip()},
    ]
    tool_results: list[dict] = []

    for _round in range(MAX_TOOL_ROUNDS + 1):
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            reasoning_effort="none",
        )
        if not response.choices:
            raise RuntimeError("Runware returned no completion choices")
        message = response.choices[0].message
        calls = message.tool_calls or []
        if not calls:
            assistant_text = (message.content or "").strip()
            if not assistant_text:
                assistant_text = (
                    "The robot command completed."
                    if tool_results
                    else "I couldn't interpret that as a supported movement."
                )
            return assistant_text, tool_results

        if _round >= MAX_TOOL_ROUNDS:
            logger.warning("Stopped after %d tool rounds", MAX_TOOL_ROUNDS)
            return (
                "I stopped because the command required too many tool steps.",
                tool_results,
            )

        messages.append(_message_to_dict(message))
        for call in calls:
            name = call.function.name
            raw_arguments = call.function.arguments or "{}"
            try:
                arguments = json.loads(raw_arguments)
                if not isinstance(arguments, dict):
                    raise ValueError("tool arguments must be a JSON object")
                logger.info("Calling tool %s with arguments %s", name, arguments)
                result = execute_tool(name, arguments)
                if inspect.isawaitable(result):
                    result = await result
                if not isinstance(result, dict):
                    raise TypeError("execute_tool must return a dict")
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.warning("Tool call %s failed validation: %s", name, exc)
                result = {
                    "ok": False,
                    "printed": "",
                    "message": f"Tool call {name!r} failed: {exc}",
                }
            tool_results.append(result)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result),
                }
            )

    raise AssertionError("unreachable")

from __future__ import annotations

import json
import math
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from demo.handler import SUPPORTED_ACTIONS_REPLY, format_tool_results, handle_message
from demo.hardware.so101 import MAX_CARTESIAN_STEP_M, apply_cartesian_delta
from demo.linq_client import InboundMessage
from demo.llm import interpret_and_call_tools
from demo.prompts import SYSTEM_PROMPT
from demo.tools import TOOLS, execute_tool


def _tool_call(name: str, arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments),
        )
    )


class _FakeCompletions:
    def __init__(self, calls: list[SimpleNamespace]) -> None:
        self.calls = calls
        self.request_count = 0

    async def create(self, **kwargs):
        self.request_count += 1
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Model prose must never reach Linq.",
                        tool_calls=self.calls,
                    )
                )
            ]
        )


class _FakeClient:
    calls: list[SimpleNamespace] = []
    last_completions: _FakeCompletions | None = None

    def __init__(self, **kwargs) -> None:
        completions = _FakeCompletions(self.calls)
        type(self).last_completions = completions
        self.chat = SimpleNamespace(completions=completions)


class ToolContractTests(unittest.TestCase):
    def test_registry_contains_only_explicit_robot_tools(self) -> None:
        names = [tool["function"]["name"] for tool in TOOLS]
        self.assertEqual(
            names,
            [
                "move_cartesian",
                "move_wrist",
                "set_gripper",
                "hold_position",
            ],
        )
        self.assertNotIn("move_robot", names)
        self.assertNotIn("request_professional_confirmation", names)

    def test_wrist_accepts_boundaries_and_rejects_out_of_range(self) -> None:
        with patch("demo.tools.robot_tools._hardware_enabled", return_value=False):
            accepted = execute_tool(
                "move_wrist",
                {"pitch_degrees": -160, "roll_degrees": 160},
            )
            rejected = execute_tool(
                "move_wrist",
                {"pitch_degrees": 160.01, "roll_degrees": 0},
            )
        self.assertTrue(accepted["ok"])
        self.assertFalse(rejected["ok"])
        self.assertIn("between -160 and +160", rejected["message"])

    def test_wrist_reply_reports_calibration_limited_result(self) -> None:
        hardware_result = {
            "ok": True,
            "detail": {
                "applied": {
                    "pitch_degrees": 0,
                    "roll_degrees": 72.5,
                }
            },
        }
        with patch(
            "demo.tools.robot_tools._hardware_enabled", return_value=True
        ), patch(
            "demo.hardware.so101.apply_wrist_delta",
            return_value=hardware_result,
        ):
            result = execute_tool(
                "move_wrist",
                {"pitch_degrees": 0, "roll_degrees": 90},
            )
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["message"],
            "Wrist differential requested pitch=+0°, roll=+90°; "
            "applied pitch=+0°, roll=+72.5° (calibration limited).",
        )

    def test_programmatic_reply_contains_only_tool_messages(self) -> None:
        results = [
            {
                "ok": True,
                "tool": "move_cartesian",
                "message": "Cartesian result from tool.",
                "step": 1,
                "sequence_total": 2,
            },
            {
                "ok": True,
                "tool": "set_gripper",
                "message": "Gripper result from tool.",
                "step": 2,
                "sequence_total": 2,
            },
        ]
        self.assertEqual(
            format_tool_results(results),
            "Executed 2 robot actions:\n"
            "1. [OK] Cartesian result from tool.\n"
            "2. [OK] Gripper result from tool.",
        )
        self.assertEqual(format_tool_results([]), SUPPORTED_ACTIONS_REPLY)

    def test_failure_stops_summary_at_failed_step(self) -> None:
        results = [
            {
                "ok": True,
                "message": "First completed.",
                "step": 1,
                "sequence_total": 3,
            },
            {
                "ok": False,
                "message": "Second failed.",
                "step": 2,
                "sequence_total": 3,
            },
        ]
        reply = format_tool_results(results)
        self.assertIn("stopped at step 2 of 3", reply)
        self.assertIn("2. [FAILED] Second failed.", reply)


class PlannerSequenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_handler_returns_only_programmatic_result_text(self) -> None:
        tool_results = [
            {
                "ok": True,
                "tool": "hold_position",
                "arguments": {},
                "message": "Robot is holding its current pose.",
                "step": 1,
                "sequence_total": 1,
            }
        ]
        with patch(
            "demo.handler.interpret_and_call_tools",
            new=AsyncMock(return_value=tool_results),
        ):
            reply = await handle_message(
                InboundMessage(
                    text="stop",
                    conversation_id="chat-1",
                    sender="sender",
                )
            )
        self.assertEqual(
            reply,
            "Executed 1 robot action:\n"
            "1. [OK] Robot is holding its current pose.",
        )

    async def test_example_executes_nine_calls_in_order_with_one_model_pass(self) -> None:
        calls = [
            _tool_call(
                "move_cartesian",
                {"delta_x_m": 0, "delta_y_m": 0, "delta_z_m": 1.0},
            ),
            _tool_call(
                "move_wrist",
                {"pitch_degrees": 0, "roll_degrees": 90},
            ),
            _tool_call("set_gripper", {"state": "open"}),
            _tool_call(
                "move_cartesian",
                {"delta_x_m": 0, "delta_y_m": 0.2, "delta_z_m": 0},
            ),
            _tool_call("set_gripper", {"state": "closed"}),
            _tool_call(
                "move_cartesian",
                {"delta_x_m": 0, "delta_y_m": -0.2, "delta_z_m": 0},
            ),
            _tool_call(
                "move_wrist",
                {"pitch_degrees": 0, "roll_degrees": -90},
            ),
            _tool_call(
                "move_cartesian",
                {"delta_x_m": 0, "delta_y_m": 0, "delta_z_m": -1.0},
            ),
            _tool_call("set_gripper", {"state": "open"}),
        ]
        _FakeClient.calls = calls
        executed: list[tuple[str, dict]] = []

        def fake_execute(name: str, arguments: dict) -> dict:
            executed.append((name, arguments))
            return {
                "ok": True,
                "tool": name,
                "arguments": arguments,
                "message": f"programmatic {name}",
                "data": None,
            }

        with patch.dict(
            os.environ, {"RUNWARE_API_KEY": "test-key"}
        ), patch(
            "demo.llm._load_openai_client", return_value=_FakeClient
        ), patch(
            "demo.llm._load_tool_registry", return_value=(TOOLS, fake_execute)
        ):
            results = await interpret_and_call_tools(
                "Move up 100 cm, roll right 90, open, forward 20 cm, close, "
                "retrace, then open."
            )

        self.assertEqual(
            executed,
            [
                (call.function.name, json.loads(call.function.arguments))
                for call in calls
            ],
        )
        self.assertEqual(len(results), 9)
        self.assertEqual([result["step"] for result in results], list(range(1, 10)))
        self.assertEqual(_FakeClient.last_completions.request_count, 1)

    async def test_execution_stops_after_first_tool_failure(self) -> None:
        _FakeClient.calls = [
            _tool_call("set_gripper", {"state": "open"}),
            _tool_call("set_gripper", {"state": "closed"}),
            _tool_call("hold_position", {}),
        ]
        executed: list[str] = []

        def fake_execute(name: str, arguments: dict) -> dict:
            executed.append(name)
            return {
                "ok": len(executed) == 1,
                "tool": name,
                "arguments": arguments,
                "message": "done" if len(executed) == 1 else "failed",
            }

        with patch.dict(
            os.environ, {"RUNWARE_API_KEY": "test-key"}
        ), patch(
            "demo.llm._load_openai_client", return_value=_FakeClient
        ), patch(
            "demo.llm._load_tool_registry", return_value=(TOOLS, fake_execute)
        ):
            results = await interpret_and_call_tools("open, close, then hold")

        self.assertEqual(executed, ["set_gripper", "set_gripper"])
        self.assertEqual(len(results), 2)
        self.assertFalse(results[-1]["ok"])
        self.assertEqual(results[-1]["sequence_total"], 3)

    def test_prompt_defines_xyz_and_programmatic_retrace(self) -> None:
        self.assertIn("+x = right; -x = left", SYSTEM_PROMPT)
        self.assertIn("+y = forward; -y = backward", SYSTEM_PROMPT)
        self.assertIn("+z = up; -z = down", SYSTEM_PROMPT)
        self.assertIn("inverse Cartesian and wrist calls in REVERSE order", SYSTEM_PROMPT)
        self.assertIn("move_cartesian(delta_x_m=0, delta_y_m=0, delta_z_m=1.0)", SYSTEM_PROMPT)


class HardwareAdapterTests(unittest.TestCase):
    def test_xyz_vector_preserves_direction_and_is_safety_limited(self) -> None:
        class FakeArm:
            def connect(self) -> None:
                return None

            def move_cartesian(self, dx: float, dy: float, dz: float) -> dict:
                self.commanded = (dx, dy, dz)
                return {
                    "from_xyz": (0.0, 0.0, 0.0),
                    "to_xyz": (dx, dy, dz),
                    "command": {
                        "applied": {
                            "shoulder_pan": {
                                "before_ticks": 100,
                                "goal_ticks": 110,
                            }
                        }
                    },
                }

        arm = FakeArm()
        with patch("demo.hardware.so101.get_arm", return_value=arm):
            result = apply_cartesian_delta(
                port="test",
                delta_x_m=1.0,
                delta_y_m=-2.0,
                delta_z_m=3.0,
            )

        commanded = arm.commanded
        self.assertAlmostEqual(
            math.sqrt(sum(value * value for value in commanded)),
            MAX_CARTESIAN_STEP_M,
        )
        self.assertGreater(commanded[0], 0)
        self.assertLess(commanded[1], 0)
        self.assertGreater(commanded[2], 0)
        self.assertEqual(result["detail"]["requested_delta_xyz"], (1.0, -2.0, 3.0))
        self.assertEqual(result["detail"]["applied_delta_xyz"], commanded)


if __name__ == "__main__":
    unittest.main()

"""Turns validated actions into robot commands (or log lines, in dry-run)."""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from .actions import (
    Action, Gripper, Home, MoveTo, Nudge, Say, SendText, Wait, parse_action,
)

logger = logging.getLogger(__name__)

# IKSolver returns bare joint names; ArmController wants the '.pos' keys.
_IK_TO_ARM = {
    "shoulder_pan": "shoulder_pan.pos",
    "shoulder_lift": "shoulder_lift.pos",
    "elbow_flex": "elbow_flex.pos",
    "wrist_flex": "wrist_flex.pos",
}

HOME_POSE = (0.0, 0.15, 0.20)


class ActionExecutor:
    """Dispatches actions to the arm, the overlay, and messaging sinks.

    Any collaborator can be None -- that path degrades to a log line, so the
    graph runs end to end without hardware attached.
    """

    def __init__(
        self,
        arm=None,
        ik=None,
        safety=None,
        overlay=None,
        messenger=None,
        dry_run: bool = True,
    ):
        self.arm = arm
        self.ik = ik
        self.safety = safety
        self.overlay = overlay
        self.messenger = messenger
        self.dry_run = dry_run

        # Last commanded end-effector target; `nudge` is relative to this.
        self.ee_target: Tuple[float, float, float] = HOME_POSE

    def run(self, plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Execute a plan in order, stopping at the first failure."""
        results: List[Dict[str, Any]] = []
        for payload in plan:
            action = parse_action(payload)
            if action is None:
                results.append({"action": payload, "ok": False,
                                "detail": f"unknown action type {payload.get('type')!r}"})
                break

            ok, detail = self._dispatch(action)
            results.append({"action": payload, "ok": ok, "detail": detail})
            if not ok:
                logger.warning("Halting plan after failed action: %s", detail)
                break
        return results

    def _dispatch(self, action: Action) -> Tuple[bool, str]:
        if isinstance(action, MoveTo):
            return self._move(action.x, action.y, action.z)
        if isinstance(action, Nudge):
            x, y, z = self.ee_target
            return self._move(x + action.dx, y + action.dy, z + action.dz)
        if isinstance(action, Home):
            return self._move(*HOME_POSE)
        if isinstance(action, Gripper):
            return self._gripper(action.position)
        if isinstance(action, Wait):
            time.sleep(action.seconds)
            return True, f"waited {action.seconds:.1f}s"
        if isinstance(action, Say):
            return self._say(action.text)
        if isinstance(action, SendText):
            return self._send_text(action.to, action.body)
        return False, f"no handler for {type(action).__name__}"

    def _move(self, x: float, y: float, z: float) -> Tuple[bool, str]:
        target = (x, y, z)
        if self.dry_run or self.ik is None or self.arm is None:
            self.ee_target = target
            logger.info("[dry-run] move_to (%.3f, %.3f, %.3f)", x, y, z)
            return True, f"move_to ({x:.3f}, {y:.3f}, {z:.3f})"

        try:
            angles = self.ik.solve(target, self.arm.get_joint_angles())
        except Exception as e:
            return False, f"IK failed for ({x:.3f}, {y:.3f}, {z:.3f}): {e}"

        command = {_IK_TO_ARM[name]: value
                   for name, value in angles.items() if name in _IK_TO_ARM}

        observation = self.arm.get_observation()
        if self.safety is not None:
            command = self.safety.clamp_action(command, observation)
            if self.safety.is_any_stall():
                return False, "arm reports a stalled joint; refusing to move"

        if not self.arm.send_action(command):
            return False, "arm rejected the command"

        self.ee_target = target
        return True, f"move_to ({x:.3f}, {y:.3f}, {z:.3f})"

    def _gripper(self, position: float) -> Tuple[bool, str]:
        if self.dry_run or self.arm is None:
            logger.info("[dry-run] gripper -> %.2f", position)
            return True, f"gripper -> {position:.2f}"

        # TODO: map normalized 0-1 aperture onto the STS3215 gripper range.
        if not self.arm.send_action({"gripper.pos": position}):
            return False, "arm rejected the gripper command"
        return True, f"gripper -> {position:.2f}"

    def _say(self, text: str) -> Tuple[bool, str]:
        if self.overlay is not None:
            # TODO: route through StatusDisplay once it exposes a message slot.
            logger.info("overlay: %s", text)
        else:
            logger.info("[no overlay] say: %s", text)
        return True, f"said {text!r}"

    def _send_text(self, to: str, body: str) -> Tuple[bool, str]:
        if self.messenger is None:
            logger.info("[no messenger] text to %s: %s", to, body)
            return True, f"logged text to {to}"
        try:
            self.messenger.send(to, body)
        except Exception as e:
            return False, f"failed to text {to}: {e}"
        return True, f"texted {to}"


def build_executor(settings, dry_run: bool = True) -> ActionExecutor:
    """Wire up an executor from project Settings, degrading to dry-run.

    Missing hardware or a missing URDF is not an error here -- it just means
    the corresponding path logs instead of moving.
    """
    if dry_run:
        return ActionExecutor(dry_run=True)

    arm = ik = safety = None

    try:
        from ..robot.arm_controller import ArmController
        from ..robot.safety import SafetyController

        arm = ArmController(port=settings.robot_port, robot_id=settings.robot_id)
        if not arm.connect():
            logger.warning("Arm did not connect; falling back to dry-run.")
            return ActionExecutor(dry_run=True)
        safety = SafetyController(
            max_relative_target=settings.max_relative_target,
            stall_threshold=settings.stall_threshold,
            stall_frames=settings.stall_frames,
        )
    except Exception as e:
        logger.warning("Robot layer unavailable (%s); falling back to dry-run.", e)
        return ActionExecutor(dry_run=True)

    try:
        from ..ik.solver import IKSolver

        ik = IKSolver(settings.urdf_path)
    except Exception as e:
        logger.warning("IK unavailable (%s); falling back to dry-run.", e)
        return ActionExecutor(arm=arm, safety=safety, dry_run=True)

    return ActionExecutor(arm=arm, ik=ik, safety=safety, dry_run=False)

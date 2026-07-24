"""Hand pose → arm end-effector target.

Zoe's architecture:
- Fist gesture = clutch: freeze target, reposition hand, resume RELATIVE to the
  current arm target on release (never snaps back to a fixed center).
- Hand image X/Y (accurate) → arm Y/Z, scaled from hand box into workspace box.
- Depth (hand-size proxy, coarse) → arm X reach, heavily scaled-down + clamped.
- Palm roll (relative to angle at engage) → wrist_roll, clamped.
- Pinch distance → gripper 0..100 with hysteresis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hand_tracking import HandPose


@dataclass
class ArmTarget:
    x: float
    y: float
    z: float
    gripper: float           # 0..100 (0=closed, 100=open)
    wrist_roll: float = 0.0  # degrees
    valid: bool = True


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class ClutchState:
    """Debounced fist → clutch. Fist held = disengaged (frozen)."""

    def __init__(self, debounce_frames: int = 3):
        self._n = debounce_frames
        self._streak = 0
        self._fist = False

    def update(self, pose: HandPose) -> bool:
        """Returns True when control is ENGAGED (hand present, not in fist)."""
        if not pose.present:
            self._streak = 0
            return False
        raw = pose.fist
        if raw != self._fist:
            self._streak += 1
            if self._streak >= self._n:
                self._fist = raw
                self._streak = 0
        else:
            self._streak = 0
        return not self._fist


class HandToArmMapper:
    """Relative clutched mapping with resume-from-current-target semantics."""

    def __init__(self, config: dict[str, Any]):
        m = config.get("mapping", config)
        hand = config.get("hand", {})
        self.scale_x = float(m["scale"].get("x", 0.3))
        self.scale_y = float(m["scale"]["y"])
        self.scale_z = float(m["scale"]["z"])
        self.use_depth = bool(m.get("use_depth_axis", True))
        box = m["workspace_box"]
        self.x_lim = tuple(box["x"])
        self.y_lim = tuple(box["y"])
        self.z_lim = tuple(box["z"])
        self.invert_z = bool(m.get("invert", {}).get("robot_z", True))
        self.roll_scale = float(m.get("roll_scale", 1.0))
        self.roll_limit = float(m.get("roll_limit_deg", 60.0))
        self.pinch_close = float(hand.get("pinch_close_threshold", 0.3))
        self.pinch_hyst = float(hand.get("pinch_hysteresis", 0.05))

        center = m.get("center", {})
        start = ArmTarget(
            x=float(center.get("x", m.get("fixed_reach_x", 0.18))),
            y=float(center.get("y", 0.0)),
            z=float(center.get("z", 0.15)),
            gripper=100.0,
            wrist_roll=0.0,
        )
        self._last = start
        self._origin: tuple[float, float, float, float] | None = None  # x, y, size, roll
        self._anchor: ArmTarget = start  # arm target at the moment of engage
        self._was_engaged = False
        self._gripper_open = True

    def map(self, pose: HandPose, *, engaged: bool) -> ArmTarget:
        # Rising edge: capture hand origin AND anchor at the current arm target,
        # so motion resumes relative to wherever the arm actually is.
        if engaged and not self._was_engaged and pose.present:
            self._origin = (pose.x, pose.y, pose.depth_proxy, pose.roll)
            self._anchor = self._last
        self._was_engaged = engaged

        if not engaged or not pose.present or self._origin is None:
            return self._last

        ox, oy, osize, oroll = self._origin

        dy = (pose.x - ox) * self.scale_y
        dz = (pose.y - oy) * self.scale_z
        if self.invert_z:
            dz = -dz
        dx = (pose.depth_proxy - osize) * self.scale_x if self.use_depth else 0.0

        x = _clamp(self._anchor.x + dx, self.x_lim[0], self.x_lim[1])
        y = _clamp(self._anchor.y + dy, self.y_lim[0], self.y_lim[1])
        z = _clamp(self._anchor.z + dz, self.z_lim[0], self.z_lim[1])

        droll = (pose.roll - oroll) * self.roll_scale
        # Wrap to [-180, 180] so a noisy flip doesn't spin the wrist
        droll = (droll + 180.0) % 360.0 - 180.0
        wrist_roll = _clamp(self._anchor.wrist_roll + droll, -self.roll_limit, self.roll_limit)

        # Gripper with hysteresis
        if self._gripper_open and pose.pinch < self.pinch_close - self.pinch_hyst:
            self._gripper_open = False
        elif not self._gripper_open and pose.pinch > self.pinch_close + self.pinch_hyst:
            self._gripper_open = True
        gripper = 100.0 if self._gripper_open else 0.0

        self._last = ArmTarget(x, y, z, gripper, wrist_roll, valid=True)
        return self._last

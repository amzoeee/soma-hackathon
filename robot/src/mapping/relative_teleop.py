"""Relative hand → target position for IK teleop.

Starts at (0, 0, 0). Open hand moves the target by the *delta* of wrist
pose relative to the camera sample captured at engage. Fist = clutch:
target freezes; reopen re-anchors so motion continues from that frozen
pose (never snaps back to zero).

Scale / fudge factors default to 1.0 — tune later against the arm.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from ..tracking.hand_tracker import HandTrackingResult
from .filters import AngleFilter, SignalFilter


@dataclass
class TeleopTarget:
    """What downstream IK / gripper control consume."""

    # Position for the IK solver (relative units until scale is tuned)
    x: float
    y: float
    z: float
    # Gripper: 0 = closed, 1 = open
    gripper: float
    # Palm roll relative to engage (degrees)
    wrist_roll: float = 0.0
    # True when fist is holding the target frozen
    clutched: bool = False
    # False when no hand this frame (target still held)
    valid: bool = True


class RelativeTeleop:
    """Accumulate a consistent target pose from HandTrackingResult + fist.

    Camera sample (normalized MediaPipe):
      hand_x : left→right (0..1)
      hand_y : top→bottom (0..1)
      hand_z : -hand_size  (moving closer makes hand_z more negative)

    Target update while engaged:
      target = anchor + scale * (hand - origin)

    where ``origin`` is the hand sample at engage and ``anchor`` is the
    target pose at engage (starts at 0,0,0; after a clutch it's the frozen
    pose).
    """

    def __init__(
        self,
        *,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        scale_z: float = 1.0,
        roll_scale: float = 1.0,
        pos_filter_alpha: float = 0.25,
        roll_filter_alpha: float = 0.12,
        roll_deadzone_deg: float = 4.0,
        gripper_filter_alpha: float = 0.3,
        clutch_debounce: int = 3,
    ):
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.scale_z = scale_z
        self.roll_scale = roll_scale

        self._fx = SignalFilter(alpha=pos_filter_alpha)
        self._fy = SignalFilter(alpha=pos_filter_alpha)
        self._fz = SignalFilter(alpha=pos_filter_alpha)
        self._fg = SignalFilter(alpha=gripper_filter_alpha)
        self._froll = AngleFilter(
            alpha=roll_filter_alpha, deadzone_deg=roll_deadzone_deg
        )

        self._target = TeleopTarget(x=0.0, y=0.0, z=0.0, gripper=1.0)
        self._anchor = (0.0, 0.0, 0.0, 0.0)  # x,y,z,roll at engage
        self._origin: Optional[tuple[float, float, float, float]] = None
        self._engaged = False
        self._fist = False
        self._fist_streak = 0
        self._debounce = clutch_debounce

    def reset(self) -> None:
        """Back to (0,0,0), open gripper, clear clutch/origin."""
        self._target = TeleopTarget(x=0.0, y=0.0, z=0.0, gripper=1.0)
        self._anchor = (0.0, 0.0, 0.0, 0.0)
        self._origin = None
        self._engaged = False
        self._fist = False
        self._fist_streak = 0
        self._fx.reset()
        self._fy.reset()
        self._fz.reset()
        self._fg.reset()
        self._froll.reset()

    def update(self, tracking: Optional[HandTrackingResult]) -> TeleopTarget:
        """Ingest one tracking frame; return the current TeleopTarget."""
        if tracking is None:
            return TeleopTarget(
                x=self._target.x,
                y=self._target.y,
                z=self._target.z,
                gripper=self._target.gripper,
                wrist_roll=self._target.wrist_roll,
                clutched=self._fist,
                valid=False,
            )

        hx_raw, hy_raw, hz_raw, hroll_raw = self._hand_sample(tracking)
        gripper = self._fg.update(self._pinch01(tracking))
        # Fist freezes immediately (HandTracker already score-thresholds).
        # Debounce only the open/re-engage edge so a 1-frame blip doesn't
        # re-anchor mid-clutch.
        raw_fist = bool(tracking.fist)
        if raw_fist:
            self._fist = True
            self._fist_streak = 0
            fist = True
        else:
            fist = self._debounce_fist(False)

        if fist:
            # Freeze position. Do NOT keep updating pos filters while clutched
            # or the next engage would see a drifted origin and jump the target.
            if self._engaged:
                self._engaged = False
                self._origin = None
            self._target.gripper = gripper
            return TeleopTarget(
                x=self._target.x,
                y=self._target.y,
                z=self._target.z,
                gripper=gripper,
                wrist_roll=self._target.wrist_roll,
                clutched=True,
                valid=True,
            )

        # Rising edge of engage: seed filters to the current sample so origin
        # matches the hand, then lock that as origin and current target as anchor.
        if not self._engaged:
            self._fx.value = hx_raw
            self._fy.value = hy_raw
            self._fz.value = hz_raw
            self._froll.value = hroll_raw
            hx, hy, hz, hroll = hx_raw, hy_raw, hz_raw, hroll_raw
            self._origin = (hx, hy, hz, hroll)
            self._anchor = (
                self._target.x,
                self._target.y,
                self._target.z,
                self._target.wrist_roll,
            )
            self._engaged = True
        else:
            hx = self._fx.update(hx_raw)
            hy = self._fy.update(hy_raw)
            hz = self._fz.update(hz_raw)
            hroll = self._froll.update(hroll_raw)

        assert self._origin is not None
        ox, oy, oz, oroll = self._origin
        ax, ay, az, aroll = self._anchor

        # depth → x, image-x → y, inverted image-y → z (up)
        self._target.x = ax + self.scale_x * (hz - oz)
        self._target.y = ay + self.scale_y * (hx - ox)
        self._target.z = az + self.scale_z * (-(hy - oy))
        self._target.wrist_roll = aroll + self.roll_scale * (hroll - oroll)
        self._target.gripper = gripper

        return TeleopTarget(
            x=self._target.x,
            y=self._target.y,
            z=self._target.z,
            gripper=gripper,
            wrist_roll=self._target.wrist_roll,
            clutched=False,
            valid=True,
        )

    @property
    def target(self) -> TeleopTarget:
        return self._target

    # ---------------------------------------------------------------- helpers
    def _debounce_fist(self, raw: bool) -> bool:
        if raw != self._fist:
            self._fist_streak += 1
            if self._fist_streak >= self._debounce:
                self._fist = raw
                self._fist_streak = 0
        else:
            self._fist_streak = 0
        return self._fist

    @staticmethod
    def _hand_sample(t: HandTrackingResult) -> tuple[float, float, float, float]:
        wx, wy, _ = t.wrist_position
        size = float(t.hand_size or RelativeTeleop._fallback_size(t))
        # Closer hand → larger size → more negative hz → +reach when moving in
        hz = -size
        roll = RelativeTeleop._wrist_roll_deg(t)
        return float(wx), float(wy), hz, roll

    @staticmethod
    def _fallback_size(t: HandTrackingResult) -> float:
        w, m = t.landmarks[0], t.landmarks[9]
        return math.hypot(m[0] - w[0], m[1] - w[1])

    @staticmethod
    def _wrist_roll_deg(t: HandTrackingResult) -> float:
        i, p = t.landmarks[5], t.landmarks[17]
        return math.degrees(math.atan2(p[1] - i[1], p[0] - i[0]))

    @staticmethod
    def _pinch01(t: HandTrackingResult) -> float:
        th, ix = t.thumb_tip, t.index_tip
        pinch = math.hypot(th[0] - ix[0], th[1] - ix[1])
        size = t.hand_size or RelativeTeleop._fallback_size(t)
        return max(0.0, min(1.0, pinch / (size * 2.0 + 1e-6)))

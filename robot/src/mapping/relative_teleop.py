"""Relative hand → absolute EE target for IK teleop.

Call ``seed_pose(x, y, z, ...)`` with the arm's current FK before the loop
so the first command holds still. Open hand moves by hand deltas relative
to engage; fist freezes; reopen re-anchors from that frozen absolute pose.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from ..tracking.hand_tracker import HandTrackingResult
from .filters import AngleFilter, SignalFilter


@dataclass
class TeleopTarget:
    """Absolute end-effector target for IK / gripper (meters, degrees)."""

    x: float
    y: float
    z: float
    # Gripper: 0 = closed, 1 = open
    gripper: float
    # Palm roll (degrees), relative to seed / re-anchor
    wrist_roll: float = 0.0
    # True when fist is holding the target frozen
    clutched: bool = False
    # False when no hand this frame (target still held)
    valid: bool = True


class RelativeTeleop:
    """Accumulate an absolute EE pose from HandTrackingResult + fist.

    Camera sample (normalized MediaPipe):
      hand_x : left→right (0..1)
      hand_y : top→bottom (0..1)
      hand_z : -hand_size  (moving closer makes hand_z more negative)

    Target update while engaged:
      target = anchor + scale * (hand - origin)

    ``anchor`` starts as the seeded FK pose (not zero); after a clutch it is
    the frozen absolute pose.
    """

    def __init__(
        self,
        *,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        scale_z: float = 1.0,
        roll_scale: float = 1.0,
        # Lighter alpha = heavier smoothing. z (depth from hand-size) is the
        # noisiest channel on the grayscale feed, so it gets the most.
        pos_filter_alpha: float = 0.15,
        z_filter_alpha: float = 0.08,
        # Ignore sub-jitter motion so a still hand → still target. Units are
        # normalized image coords (x/y) and hand-size (z).
        xy_deadband: float = 0.006,
        z_deadband: float = 0.010,
        roll_filter_alpha: float = 0.12,
        roll_deadzone_deg: float = 4.0,
        gripper_filter_alpha: float = 0.3,
        # Frames of consecutive fist / open required to flip clutch state.
        # Long ON so accidental Closed_Fist blips don't freeze the arm.
        clutch_on_frames: int = 18,
        clutch_off_frames: int = 6,
        clutch_debounce: int | None = None,  # legacy: applied to both if set
    ):
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.scale_z = scale_z
        self.roll_scale = roll_scale
        self.xy_deadband = xy_deadband
        self.z_deadband = z_deadband
        if clutch_debounce is not None:
            clutch_on_frames = clutch_debounce
            clutch_off_frames = max(clutch_debounce, 8)
        self._on_frames = clutch_on_frames
        self._off_frames = clutch_off_frames

        self._fx = SignalFilter(alpha=pos_filter_alpha)
        self._fy = SignalFilter(alpha=pos_filter_alpha)
        self._fz = SignalFilter(alpha=z_filter_alpha)
        self._fg = SignalFilter(alpha=gripper_filter_alpha)
        self._froll = AngleFilter(
            alpha=roll_filter_alpha, deadzone_deg=roll_deadzone_deg
        )
        # Deadbanded values actually used for the target (post-EMA hysteresis)
        self._dbx: float | None = None
        self._dby: float | None = None
        self._dbz: float | None = None

        # Absolute EE pose (meters). Seed from FK before the control loop.
        self._seed = (0.0, 0.0, 0.0, 0.0)  # x, y, z, roll
        self._seed_gripper = 1.0
        self._target = TeleopTarget(x=0.0, y=0.0, z=0.0, gripper=1.0)
        self._anchor = (0.0, 0.0, 0.0, 0.0)  # x,y,z,roll at engage
        self._origin: Optional[tuple[float, float, float, float]] = None
        self._engaged = False
        self._fist = False
        self._fist_streak = 0
        self._open_streak = 0
        self._debounce = clutch_off_frames  # kept for older helpers

    def seed_pose(
        self,
        x: float,
        y: float,
        z: float,
        *,
        wrist_roll: float = 0.0,
        gripper: float = 1.0,
    ) -> None:
        """Set absolute start pose from arm FK / encoder state.

        Call once after connecting so the first IK command matches the
        physical arm (no snap from a hardcoded zero).
        """
        self._seed = (float(x), float(y), float(z), float(wrist_roll))
        self._seed_gripper = max(0.0, min(1.0, float(gripper)))
        self._target = TeleopTarget(
            x=self._seed[0],
            y=self._seed[1],
            z=self._seed[2],
            gripper=self._seed_gripper,
            wrist_roll=self._seed[3],
        )
        self._anchor = self._seed
        self._origin = None
        self._engaged = False
        self._fist = False
        self._fist_streak = 0
        self._open_streak = 0
        self._fx.reset()
        self._fy.reset()
        self._fz.reset()
        self._fg.reset()
        self._froll.reset()
        self._dbx = None
        self._dby = None
        self._dbz = None
        self._fg.value = self._seed_gripper

    def reset(self) -> None:
        """Back to the last seeded FK pose; clear clutch/origin."""
        sx, sy, sz, sroll = self._seed
        self.seed_pose(sx, sy, sz, wrist_roll=sroll, gripper=self._seed_gripper)

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
        fist = self._debounce_fist(bool(tracking.fist))

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
            self._dbx, self._dby, self._dbz = hx_raw, hy_raw, hz_raw
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
            hx = self._deadband(self._fx.update(hx_raw), "_dbx", self.xy_deadband)
            hy = self._deadband(self._fy.update(hy_raw), "_dby", self.xy_deadband)
            hz = self._deadband(self._fz.update(hz_raw), "_dbz", self.z_deadband)
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
    def _deadband(self, value: float, attr: str, band: float) -> float:
        """Hold the last emitted value until motion exceeds ``band``.

        Kills stationary jitter without adding lag to real motion: once the
        smoothed value moves past the band, we snap to it and track from there.
        """
        held = getattr(self, attr)
        if held is None or abs(value - held) >= band:
            setattr(self, attr, value)
            return value
        return held

    def _debounce_fist(self, raw: bool) -> bool:
        """Require sustained fist to clutch ON, longer open to release.

        Instant on + short off was the main clutch flicker source.
        """
        if raw:
            self._fist_streak += 1
            self._open_streak = 0
            if not self._fist and self._fist_streak >= self._on_frames:
                self._fist = True
        else:
            self._open_streak += 1
            self._fist_streak = 0
            if self._fist and self._open_streak >= self._off_frames:
                self._fist = False
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

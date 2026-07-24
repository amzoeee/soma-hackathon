"""One Euro filter — de-jitter hand pose channels (incl. wrap-aware roll)."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class _LowPass:
    alpha: float = 1.0
    hat: float | None = None

    def filter(self, x: float, alpha: float) -> float:
        self.alpha = alpha
        if self.hat is None:
            self.hat = x
        else:
            self.hat = alpha * x + (1.0 - alpha) * self.hat
        return self.hat


class OneEuroFilter:
    """Per-channel One Euro filter (Casiez et al.)."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.007, dcutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.dcutoff = dcutoff
        self._x = _LowPass()
        self._dx = _LowPass()
        self._t_prev: float | None = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-6))
        return 1.0 / (1.0 + tau / max(dt, 1e-6))

    def __call__(self, x: float, t: float) -> float:
        if self._t_prev is None:
            self._t_prev = t
            self._x.hat = x
            self._dx.hat = 0.0
            return x
        dt = max(t - self._t_prev, 1e-6)
        self._t_prev = t
        dx = (x - (self._x.hat if self._x.hat is not None else x)) / dt
        edx = self._dx.filter(dx, self._alpha(self.dcutoff, dt))
        cutoff = self.min_cutoff + self.beta * abs(edx)
        return self._x.filter(x, self._alpha(cutoff, dt))


class AngleFilter:
    """Wrap-aware EMA for degrees + deadzone (landmark roll is noisy)."""

    def __init__(self, alpha: float = 0.12, deadzone_deg: float = 4.0):
        self.alpha = alpha
        self.deadzone_deg = deadzone_deg
        self.value: float | None = None

    @staticmethod
    def _wrap(deg: float) -> float:
        return ((deg + 180.0) % 360.0) - 180.0

    def update(self, angle_deg: float) -> float:
        a = self._wrap(angle_deg)
        if self.value is None:
            self.value = a
            return a
        delta = self._wrap(a - self.value)
        if abs(delta) < self.deadzone_deg:
            return self.value
        self.value = self._wrap(self.value + self.alpha * delta)
        return self.value

    def reset(self) -> None:
        self.value = None


class HandSmoother:
    """Smooth x, y, depth_proxy, roll; light EMA on pinch."""

    def __init__(
        self,
        min_cutoff: float = 1.0,
        beta: float = 0.007,
        pinch_ema_alpha: float = 0.4,
        roll_alpha: float = 0.12,
        roll_deadzone_deg: float = 4.0,
    ):
        self.fx = OneEuroFilter(min_cutoff, beta)
        self.fy = OneEuroFilter(min_cutoff, beta)
        self.fd = OneEuroFilter(min_cutoff, beta)
        self.roll = AngleFilter(alpha=roll_alpha, deadzone_deg=roll_deadzone_deg)
        self.pinch_alpha = pinch_ema_alpha
        self._pinch: float | None = None

    def filter(self, pose, t: float):
        from hand_tracking import HandPose

        if not pose.present:
            self.roll.reset()
            self._pinch = None
            return pose
        x = self.fx(pose.x, t)
        y = self.fy(pose.y, t)
        d = self.fd(pose.depth_proxy, t)
        roll = self.roll.update(pose.roll)
        if self._pinch is None:
            self._pinch = pose.pinch
        else:
            a = self.pinch_alpha
            self._pinch = a * pose.pinch + (1.0 - a) * self._pinch
        return HandPose(
            present=True,
            x=x,
            y=y,
            depth_proxy=d,
            pinch=float(self._pinch),
            roll=roll,
            fist=pose.fist,
            gesture=pose.gesture,
            landmarks_px=pose.landmarks_px,
        )

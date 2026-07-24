"""Signal filtering utilities for hand tracking and robot control."""


class SignalFilter:
    """Exponential moving average filter."""

    def __init__(self, alpha: float = 0.2):
        self.alpha = alpha
        self.value = None

    def update(self, new_value: float) -> float:
        if self.value is None:
            self.value = new_value
        else:
            self.value = self.alpha * new_value + (1 - self.alpha) * self.value
        return self.value

    def reset(self):
        self.value = None


class AngleFilter:
    """EMA for angles in degrees, with wrap-around and a deadzone.

    Plain EMA on roll is wrong near ±180° (it will lerp the long way around).
    This always blends along the shortest arc, and ignores deltas smaller than
    ``deadzone_deg`` so landmark jitter doesn't twitch the wrist servo.
    """

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

    def reset(self):
        self.value = None


class DeadzoneFilter:
    """Deadzone filter to ignore small changes."""

    def __init__(self, threshold: float = 0.005):
        self.threshold = threshold

    def apply(self, value: float, reference: float) -> float:
        if abs(value - reference) < self.threshold:
            return reference
        return value


class RateLimiter:
    """Limits the rate of change of a signal (stateful version for per-tick use)."""

    def __init__(self, max_delta: float):
        self.max_delta = max_delta
        self._last: float | None = None

    def limit(self, current: float, target: float) -> float:
        delta = target - current
        if delta > self.max_delta:
            return current + self.max_delta
        if delta < -self.max_delta:
            return current - self.max_delta
        return target

    def update(self, target: float) -> float:
        if self._last is None:
            self._last = target
            return target
        self._last = self.limit(self._last, target)
        return self._last

    def reset(self):
        self._last = None

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

class DeadzoneFilter:
    """Deadzone filter to ignore small changes."""
    def __init__(self, threshold: float = 0.005):
        self.threshold = threshold

    def apply(self, value: float, reference: float) -> float:
        if abs(value - reference) < self.threshold:
            return reference
        return value

class RateLimiter:
    """Limits the rate of change of a signal."""
    def __init__(self, max_delta: float):
        self.max_delta = max_delta

    def limit(self, current: float, target: float) -> float:
        delta = target - current
        if delta > self.max_delta:
            return current + self.max_delta
        elif delta < -self.max_delta:
            return current - self.max_delta
        return target

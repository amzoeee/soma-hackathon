"""Demo mode state machine."""

from __future__ import annotations

from enum import Enum, auto
from typing import Any


class Mode(Enum):
    AUTONOMOUS = auto()
    FLAGGED = auto()
    TAKEOVER = auto()
    ESTOP = auto()


class ModeController:
    def __init__(self, config: dict[str, Any]):
        demo = config.get("demo", {})
        self.flag_trigger = demo.get("flag_trigger", "scripted")
        self.load_threshold = config.get("arm", {}).get("load_flag_threshold")
        self.mode = Mode.AUTONOMOUS
        self._prev_keys: set[str] = set()

    def update(self, *, keys_down: set[str], load: dict[str, float] | None = None) -> Mode:
        pressed = keys_down - self._prev_keys
        self._prev_keys = set(keys_down)

        if "esc" in pressed:
            self.mode = Mode.ESTOP
            return self.mode

        if self.mode == Mode.ESTOP:
            # Manual reset: R returns to autonomous after estop cleared physically
            if "r" in pressed:
                self.mode = Mode.AUTONOMOUS
            return self.mode

        if "f" in pressed:
            self.mode = Mode.FLAGGED
        if "t" in pressed:
            self.mode = Mode.TAKEOVER
        if "r" in pressed:
            self.mode = Mode.AUTONOMOUS

        if (
            self.mode == Mode.AUTONOMOUS
            and self.flag_trigger == "load"
            and self.load_threshold is not None
            and load
        ):
            if any(abs(v) >= float(self.load_threshold) for v in load.values()):
                self.mode = Mode.FLAGGED

        # From FLAGGED, clutching SPACE can enter TAKEOVER
        if self.mode == Mode.FLAGGED and "space" in keys_down:
            self.mode = Mode.TAKEOVER

        return self.mode

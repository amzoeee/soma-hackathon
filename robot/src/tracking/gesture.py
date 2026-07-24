"""GestureRecognizer wrapper — prefers HandTracker's built-in fist flag.

Kept for API compatibility with main.py. Prefer HandTracker.process().fist
when both landmarks and clutch are needed (one VIDEO-mode pass).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from .hand_tracker import HandTracker

logger = logging.getLogger(__name__)


@dataclass
class GestureResult:
    gesture_name: str | None
    confidence: float
    is_clutch_active: bool


class GestureRecognizer:
    """Thin wrapper around HandTracker for fist/clutch only.

    Shares the same VIDEO-mode model so landmark + gesture stay consistent.
    If you already call HandTracker.process(), use result.fist instead of
    running this a second time.
    """

    def __init__(
        self,
        model_path: str = "gesture_recognizer.task",
        min_confidence: float = 0.5,
    ):
        self._tracker = HandTracker(
            model_path=model_path,
            fist_score_threshold=min_confidence,
        )

    def recognize(self, grayscale_frame: np.ndarray) -> GestureResult:
        result = self._tracker.process(grayscale_frame)
        if result is None:
            return GestureResult(gesture_name=None, confidence=0.0, is_clutch_active=False)
        return GestureResult(
            gesture_name=result.gesture,
            confidence=result.gesture_confidence,
            is_clutch_active=result.fist,
        )

    def close(self):
        self._tracker.close()

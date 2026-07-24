"""MediaPipe hand tracking on grayscale Eye frames.

Uses GestureRecognizer in VIDEO mode (one model = 21 landmarks + fist).
VIDEO mode keeps temporal state across frames, which is what stops the
skeleton from flickering on the noisy Eye feed. IMAGE mode re-detects
every frame and is the main source of "buggy" tracking.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    GestureRecognizer,
    GestureRecognizerOptions,
    RunningMode,
)

from .enhance import enhance_grayscale

logger = logging.getLogger(__name__)


@dataclass
class HandTrackingResult:
    landmarks: list[tuple[float, float, float]]
    world_landmarks: list[tuple[float, float, float]]
    handedness: str
    wrist_position: tuple[float, float, float]
    thumb_tip: tuple[float, float, float]
    index_tip: tuple[float, float, float]
    fist: bool = False
    gesture: str | None = None
    gesture_confidence: float = 0.0
    # wrist->middle MCP distance in normalized coords; used as a quality gate
    hand_size: float = 0.0


class HandTracker:
    """Tracks hands + fist gesture from grayscale frames (VIDEO mode)."""

    def __init__(
        self,
        model_path: str = "gesture_recognizer.task",
        num_hands: int = 1,
        min_detection_confidence: float = 0.25,
        min_tracking_confidence: float = 0.25,
        fist_score_threshold: float = 0.5,
        # Drop detections that are too small/far — these are usually false
        # positives that make the skeleton jump around the frame.
        min_hand_size: float = 0.06,
        # Keep drawing the last good skeleton for this many missed frames
        # (~250ms at 30Hz) so brief dropouts don't blank the HUD.
        hold_frames: int = 8,
    ):
        self.model_path = model_path
        self.fist_score_threshold = fist_score_threshold
        self.min_hand_size = min_hand_size
        self.hold_frames = hold_frames
        self._missed = 0
        self._last: HandTrackingResult | None = None
        self._ts_ms = 0
        self.recognizer = None

        try:
            options = GestureRecognizerOptions(
                base_options=BaseOptions(model_asset_path=self.model_path),
                running_mode=RunningMode.VIDEO,
                num_hands=num_hands,
                min_hand_detection_confidence=min_detection_confidence,
                min_hand_presence_confidence=min_detection_confidence,
                min_tracking_confidence=min_tracking_confidence,
            )
            self.recognizer = GestureRecognizer.create_from_options(options)
        except Exception as e:
            logger.error("Failed to initialize GestureRecognizer: %s", e)

    def process(self, grayscale_frame: np.ndarray) -> HandTrackingResult | None:
        if self.recognizer is None:
            logger.error("GestureRecognizer not initialized.")
            return None

        rgb_frame = enhance_grayscale(grayscale_frame)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        # Monotonic timestamps required by VIDEO mode
        self._ts_ms += 33

        try:
            result = self.recognizer.recognize_for_video(mp_image, self._ts_ms)
        except Exception as e:
            logger.error("Error during hand tracking: %s", e)
            return self._held()

        if not result.hand_landmarks:
            return self._held()

        hand_landmarks = result.hand_landmarks[0]
        world = result.hand_world_landmarks[0] if result.hand_world_landmarks else hand_landmarks
        handedness = (
            result.handedness[0][0].category_name if result.handedness else "Unknown"
        )

        landmarks = [(lm.x, lm.y, lm.z) for lm in hand_landmarks]
        world_landmarks = [(lm.x, lm.y, lm.z) for lm in world]

        wrist = landmarks[0]
        middle_mcp = landmarks[9]
        hand_size = float(
            ((middle_mcp[0] - wrist[0]) ** 2 + (middle_mcp[1] - wrist[1]) ** 2) ** 0.5
        )
        if hand_size < self.min_hand_size:
            # Too small = far/false — treat as a miss rather than a jump
            return self._held()

        gesture_name = None
        gesture_conf = 0.0
        fist = False
        if result.gestures and result.gestures[0]:
            top = result.gestures[0][0]
            if top.category_name != "None":
                gesture_name = top.category_name
                gesture_conf = float(top.score)
                fist = (
                    top.category_name == "Closed_Fist"
                    and top.score >= self.fist_score_threshold
                )

        tracked = HandTrackingResult(
            landmarks=landmarks,
            world_landmarks=world_landmarks,
            handedness=handedness,
            wrist_position=landmarks[0],
            thumb_tip=landmarks[4],
            index_tip=landmarks[8],
            fist=fist,
            gesture=gesture_name,
            gesture_confidence=gesture_conf,
            hand_size=hand_size,
        )
        self._last = tracked
        self._missed = 0
        return tracked

    def _held(self) -> HandTrackingResult | None:
        """Return last good result for a few frames, then None."""
        self._missed += 1
        if self._last is not None and self._missed <= self.hold_frames:
            return self._last
        if self._missed > self.hold_frames:
            self._last = None
        return None

    def close(self):
        if self.recognizer is not None:
            self.recognizer.close()
            self.recognizer = None

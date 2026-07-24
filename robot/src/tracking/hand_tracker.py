"""MediaPipe hand tracking on grayscale Eye frames.

Uses GestureRecognizer in VIDEO mode (one model = 21 landmarks + fist).
VIDEO mode keeps temporal state across frames, which is what stops the
skeleton from flickering on the noisy Eye feed. IMAGE mode re-detects
every frame and is the main source of "buggy" tracking.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

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
        min_detection_confidence: float = 0.15,
        min_tracking_confidence: float = 0.15,
        # Hysteresis: hard to enter fist (avoid pinch/open false clutch),
        # easier to leave once you're clearly open again.
        fist_enter_score: float = 0.60,
        fist_exit_score: float = 0.35,
        # Back-compat for call sites that still pass fist_score_threshold=
        fist_score_threshold: float | None = None,
        # Drop detections that are too small/far — these are usually false
        # positives that make the skeleton jump around the frame.
        min_hand_size: float = 0.04,
        # Keep last good skeleton longer so brief Eye dropouts don't freeze teleop.
        hold_frames: int = 24,
    ):
        self.model_path = model_path
        if fist_score_threshold is not None:
            fist_enter_score = fist_score_threshold
        self.fist_enter_score = fist_enter_score
        self.fist_exit_score = fist_exit_score
        self.fist_score_threshold = fist_enter_score
        self.min_hand_size = min_hand_size
        self.hold_frames = hold_frames
        self._missed = 0
        self._last: HandTrackingResult | None = None
        self._fist_latched = False
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
        world = (
            result.hand_world_landmarks[0]
            if result.hand_world_landmarks
            else hand_landmarks
        )
        handedness = (
            result.handedness[0][0].category_name if result.handedness else "Unknown"
        )

        landmarks = [(lm.x, lm.y, lm.z) for lm in hand_landmarks]
        world_landmarks = [(lm.x, lm.y, lm.z) for lm in world]

        wrist = landmarks[0]
        middle_mcp = landmarks[9]
        hand_size = float(
            math.hypot(middle_mcp[0] - wrist[0], middle_mcp[1] - wrist[1])
        )
        if hand_size < self.min_hand_size:
            # Too small = far/false — treat as a miss rather than a jump
            return self._held()

        gesture_name = None
        gesture_conf = 0.0
        gesture_fist = False
        if result.gestures and result.gestures[0]:
            top = result.gestures[0][0]
            if top.category_name != "None":
                gesture_name = top.category_name
                gesture_conf = float(top.score)
                gesture_fist = top.category_name == "Closed_Fist"

        geom_fist = self._geometric_fist(landmarks, hand_size)
        fist = self._latch_fist(gesture_fist, gesture_conf, geom_fist, gesture_name)

        tracked = HandTrackingResult(
            landmarks=landmarks,
            world_landmarks=world_landmarks,
            handedness=handedness,
            wrist_position=landmarks[0],
            thumb_tip=landmarks[4],
            index_tip=landmarks[8],
            fist=fist,
            gesture=gesture_name if gesture_name else ("Closed_Fist" if fist else None),
            gesture_confidence=gesture_conf,
            hand_size=hand_size,
        )
        self._last = tracked
        self._missed = 0
        return tracked

    def _latch_fist(
        self,
        gesture_fist: bool,
        gesture_conf: float,
        geom_fist: bool,
        gesture_name: str | None,
    ) -> bool:
        """Strict enter, looser exit — clutch was false-triggering on pinch/open."""
        open_gestures = {"Open_Palm", "Victory", "Thumb_Up", "Pointing_Up"}
        if self._fist_latched:
            # Leave clutch as soon as the hand clearly isn't a fist anymore.
            clear_open = (
                (gesture_name in open_gestures and gesture_conf >= 0.35)
                or (not gesture_fist and not geom_fist)
            )
            if clear_open:
                self._fist_latched = False
        else:
            # ENTER only on a confident Closed_Fist label — geometric alone
            # was too sensitive (pinch / half-open looked "curled").
            if gesture_fist and gesture_conf >= self.fist_enter_score:
                self._fist_latched = True
        return self._fist_latched

    @staticmethod
    def _geometric_fist(
        landmarks: list[tuple[float, float, float]], hand_size: float
    ) -> bool:
        """Strict curled-fist check (hold assist only — not used to enter)."""
        if hand_size < 1e-6:
            return False
        palm = landmarks[9]
        tip_ids = (8, 12, 16, 20)
        curled = 0
        for tip_id in tip_ids:
            tip = landmarks[tip_id]
            dist = math.hypot(tip[0] - palm[0], tip[1] - palm[1])
            if dist < hand_size * 0.55:
                curled += 1
        return curled >= 4

    def _held(self) -> HandTrackingResult | None:
        """Return last good result for a few frames, then None."""
        self._missed += 1
        if self._last is not None and self._missed <= self.hold_frames:
            held = self._last
            if held.fist != self._fist_latched:
                held = HandTrackingResult(
                    landmarks=held.landmarks,
                    world_landmarks=held.world_landmarks,
                    handedness=held.handedness,
                    wrist_position=held.wrist_position,
                    thumb_tip=held.thumb_tip,
                    index_tip=held.index_tip,
                    fist=self._fist_latched,
                    gesture=held.gesture,
                    gesture_confidence=held.gesture_confidence,
                    hand_size=held.hand_size,
                )
            return held
        if self._missed > self.hold_frames:
            self._last = None
        return None

    def close(self):
        if self.recognizer is not None:
            self.recognizer.close()
            self.recognizer = None

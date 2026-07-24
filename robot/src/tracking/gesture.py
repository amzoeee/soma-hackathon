"""MediaPipe GestureRecognizer — Closed_Fist drives the clutch."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import mediapipe as mp
import numpy as np

from .enhance import enhance_grayscale

logger = logging.getLogger(__name__)


@dataclass
class GestureResult:
    gesture_name: str | None
    confidence: float
    is_clutch_active: bool


class GestureRecognizer:
    """Recognizes gestures; Closed_Fist = clutch active."""

    def __init__(
        self,
        model_path: str = "gesture_recognizer.task",
        min_confidence: float = 0.5,
    ):
        self.model_path = model_path
        self.min_confidence = min_confidence

        try:
            BaseOptions = mp.tasks.BaseOptions
            GestureRecognizer_cls = mp.tasks.vision.GestureRecognizer
            GestureRecognizerOptions = mp.tasks.vision.GestureRecognizerOptions
            VisionRunningMode = mp.tasks.vision.RunningMode

            options = GestureRecognizerOptions(
                base_options=BaseOptions(model_asset_path=self.model_path),
                running_mode=VisionRunningMode.IMAGE,
            )
            self.recognizer = GestureRecognizer_cls.create_from_options(options)
        except Exception as e:
            logger.error("Failed to initialize GestureRecognizer: %s", e)
            self.recognizer = None

    def recognize(self, grayscale_frame: np.ndarray) -> GestureResult:
        if self.recognizer is None:
            logger.error("GestureRecognizer not initialized.")
            return GestureResult(gesture_name=None, confidence=0.0, is_clutch_active=False)

        rgb_frame = enhance_grayscale(grayscale_frame)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        try:
            result = self.recognizer.recognize(mp_image)
            if not result.gestures or not result.gestures[0]:
                return GestureResult(gesture_name=None, confidence=0.0, is_clutch_active=False)

            top_gesture = result.gestures[0][0]
            if top_gesture.category_name == "None" or top_gesture.score < self.min_confidence:
                return GestureResult(gesture_name=None, confidence=0.0, is_clutch_active=False)

            gesture_name = top_gesture.category_name
            is_clutch = gesture_name == "Closed_Fist"
            return GestureResult(
                gesture_name=gesture_name,
                confidence=top_gesture.score,
                is_clutch_active=is_clutch,
            )
        except Exception as e:
            logger.error("Error during gesture recognition: %s", e)
            return GestureResult(gesture_name=None, confidence=0.0, is_clutch_active=False)

    def close(self):
        if self.recognizer is not None:
            self.recognizer.close()
            self.recognizer = None

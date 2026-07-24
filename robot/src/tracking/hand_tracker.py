"""MediaPipe HandLandmarker on grayscale Eye frames.

Returns wrist / thumb / index tips plus the full 21-landmark list as (x,y,z)
tuples in normalized image coords. Frames are enhanced before inference —
raw Eye grayscale barely detects without that pass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import mediapipe as mp
import numpy as np

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


class HandTracker:
    """Tracks hands using MediaPipe HandLandmarker on grayscale frames."""

    def __init__(
        self,
        model_path: str = "hand_landmarker.task",
        num_hands: int = 1,
        min_detection_confidence: float = 0.25,
        min_tracking_confidence: float = 0.25,
    ):
        self.model_path = model_path
        self.num_hands = num_hands
        self.min_detection_confidence = min_detection_confidence
        self.min_tracking_confidence = min_tracking_confidence

        try:
            BaseOptions = mp.tasks.BaseOptions
            HandLandmarker = mp.tasks.vision.HandLandmarker
            HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
            VisionRunningMode = mp.tasks.vision.RunningMode

            options = HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=self.model_path),
                running_mode=VisionRunningMode.IMAGE,
                num_hands=self.num_hands,
                min_hand_detection_confidence=self.min_detection_confidence,
                min_tracking_confidence=self.min_tracking_confidence,
            )
            self.landmarker = HandLandmarker.create_from_options(options)
        except Exception as e:
            logger.error("Failed to initialize HandLandmarker: %s", e)
            self.landmarker = None

    def process(self, grayscale_frame: np.ndarray) -> HandTrackingResult | None:
        if self.landmarker is None:
            logger.error("HandLandmarker not initialized.")
            return None

        rgb_frame = enhance_grayscale(grayscale_frame)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        try:
            result = self.landmarker.detect(mp_image)
            if not result.hand_landmarks:
                return None

            hand_landmarks = result.hand_landmarks[0]
            hand_world_landmarks = result.hand_world_landmarks[0]
            handedness_category = result.handedness[0][0]

            landmarks_list = [(lm.x, lm.y, lm.z) for lm in hand_landmarks]
            world_landmarks_list = [(lm.x, lm.y, lm.z) for lm in hand_world_landmarks]

            return HandTrackingResult(
                landmarks=landmarks_list,
                world_landmarks=world_landmarks_list,
                handedness=handedness_category.category_name,
                wrist_position=landmarks_list[0],
                thumb_tip=landmarks_list[4],
                index_tip=landmarks_list[8],
            )
        except Exception as e:
            logger.error("Error during hand tracking process: %s", e)
            return None

    def close(self):
        if self.landmarker is not None:
            self.landmarker.close()
            self.landmarker = None

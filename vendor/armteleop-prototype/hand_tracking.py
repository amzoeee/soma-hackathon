"""MediaPipe hand tracking → HandPose + landmark drawing.

Uses the Gesture Recognizer task (one model = 21 landmarks + canned gestures),
so we get the fist "clutch" gesture for free alongside the landmarks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    GestureRecognizer,
    GestureRecognizerOptions,
    HandLandmarksConnections,
    RunningMode,
)


@dataclass
class HandPose:
    present: bool
    x: float = 0.0
    y: float = 0.0
    depth_proxy: float = 0.0
    pinch: float = 1.0
    roll: float = 0.0          # palm roll angle in degrees (image plane)
    fist: bool = False         # Closed_Fist gesture → clutch disengage
    gesture: str = ""          # raw top gesture name (debug/HUD)
    landmarks_px: np.ndarray | None = None  # (21, 2) pixel coords for drawing


# MediaPipe hand landmark indices
WRIST = 0
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_TIP = 8
MIDDLE_MCP = 9
PINKY_MCP = 17


class HandTracker:
    def __init__(
        self,
        model_path: str | Path,
        min_detection_confidence: float = 0.3,
        min_tracking_confidence: float = 0.3,
        reference_landmark: str = "wrist",
        upscale: float = 2.5,
        fist_score_threshold: float = 0.5,
    ):
        model_path = Path(model_path)
        if not model_path.is_file():
            raise FileNotFoundError(
                f"Gesture recognizer model not found: {model_path}\n"
                "Download gesture_recognizer.task into assets/."
            )
        options = GestureRecognizerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=min_detection_confidence,
            min_hand_presence_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._recognizer = GestureRecognizer.create_from_options(options)
        self._reference = reference_landmark
        self._upscale = upscale
        self._fist_threshold = fist_score_threshold
        self._frame_ts_ms = 0

    @staticmethod
    def _gamma(gray: np.ndarray, gamma: float) -> np.ndarray:
        inv = 1.0 / max(gamma, 1e-3)
        table = np.array([((i / 255.0) ** inv) * 255 for i in range(256)], dtype=np.uint8)
        return cv2.LUT(gray, table)

    def enhance_for_detection(self, frame_bgr: np.ndarray) -> np.ndarray:
        """Aggressive preprocess for noisy grayscale Eye frames."""
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        # Denoise first so CLAHE doesn't amplify grain
        gray = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)
        # Lift shadows (Eye often underexposes hands)
        gray = self._gamma(gray, gamma=0.65)
        clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        # Mild unsharp so hand edges pop for the detector
        blur = cv2.GaussianBlur(gray, (0, 0), 1.2)
        gray = cv2.addWeighted(gray, 1.5, blur, -0.5, 0)
        boosted = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        if self._upscale and self._upscale != 1.0:
            boosted = cv2.resize(
                boosted,
                None,
                fx=self._upscale,
                fy=self._upscale,
                interpolation=cv2.INTER_CUBIC,
            )
        return boosted

    def process(self, frame_bgr: np.ndarray, *, enhance: bool = True) -> HandPose:
        detect = self.enhance_for_detection(frame_bgr) if enhance else frame_bgr
        rgb = cv2.cvtColor(detect, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        self._frame_ts_ms += 33  # ~30 Hz monotonic timestamps for VIDEO mode
        result = self._recognizer.recognize_for_video(mp_image, self._frame_ts_ms)

        if not result.hand_landmarks:
            return HandPose(present=False)

        lm = result.hand_landmarks[0]
        # Map normalized landmarks back onto the display frame size
        h, w = frame_bgr.shape[:2]
        pts = np.array([(p.x * w, p.y * h) for p in lm], dtype=np.float32)
        norm = np.array([(p.x, p.y) for p in lm], dtype=np.float32)

        if self._reference == "palm_center":
            ref = (norm[WRIST] + norm[MIDDLE_MCP]) * 0.5
        else:
            ref = norm[WRIST]

        hand_size = float(np.linalg.norm(norm[WRIST] - norm[MIDDLE_MCP]) + 1e-6)
        pinch_raw = float(np.linalg.norm(norm[THUMB_TIP] - norm[INDEX_TIP]))
        pinch = float(np.clip(pinch_raw / (hand_size * 2.0), 0.0, 1.0))

        # Palm roll from knuckle line (index MCP → pinky MCP) in image plane.
        # Absolute value is arbitrary; the mapper uses it relatively (delta from
        # the angle captured at clutch engage).
        kx = norm[PINKY_MCP][0] - norm[INDEX_MCP][0]
        ky = norm[PINKY_MCP][1] - norm[INDEX_MCP][1]
        roll_deg = math.degrees(math.atan2(ky, kx))

        gesture_name = ""
        fist = False
        if result.gestures and result.gestures[0]:
            top = result.gestures[0][0]
            gesture_name = top.category_name
            fist = top.category_name == "Closed_Fist" and top.score >= self._fist_threshold

        return HandPose(
            present=True,
            x=float(ref[0]),
            y=float(ref[1]),
            depth_proxy=hand_size,
            pinch=pinch,
            roll=roll_deg,
            fist=fist,
            gesture=gesture_name,
            landmarks_px=pts,
        )

    def close(self) -> None:
        self._recognizer.close()


def draw_hand(frame: np.ndarray, pose: HandPose) -> np.ndarray:
    """Draw 21 landmarks + skeleton connections on a BGR frame."""
    out = frame
    if not pose.present or pose.landmarks_px is None:
        return out

    color = (0, 0, 255) if pose.fist else (0, 255, 0)
    pts = pose.landmarks_px.astype(np.int32)
    for connection in HandLandmarksConnections.HAND_CONNECTIONS:
        a, b = connection.start, connection.end
        cv2.line(out, tuple(pts[a]), tuple(pts[b]), color, 2, cv2.LINE_AA)
    for x, y in pts:
        cv2.circle(out, (int(x), int(y)), 3, (0, 128, 255), -1, cv2.LINE_AA)
    return out


def make_hand_tracker(config: dict[str, Any], root: Path | None = None) -> HandTracker:
    hand = config.get("hand", config)
    root = root or Path.cwd()
    model = Path(hand.get("gesture_model_path", hand.get("model_path", "assets/gesture_recognizer.task")))
    if not model.is_absolute():
        model = root / model
    return HandTracker(
        model_path=model,
        min_detection_confidence=float(hand.get("min_detection_confidence", 0.3)),
        min_tracking_confidence=float(hand.get("min_tracking_confidence", 0.3)),
        reference_landmark=str(hand.get("reference_landmark", "wrist")),
        upscale=float(hand.get("upscale", 2.5)),
        fist_score_threshold=float(hand.get("fist_score_threshold", 0.5)),
    )

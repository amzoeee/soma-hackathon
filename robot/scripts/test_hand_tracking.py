#!/usr/bin/env python3
"""M1-style hand tracking test for the hackathon robot package.

Shows Eye (or webcam) feed with landmarks + the four teleop values:
  position (x,y), wrist roll (deg), pinch (0-1), fist/clutch.

Usage (from robot/):
  python scripts/test_hand_tracking.py              # Eye stream
  python scripts/test_hand_tracking.py --webcam     # USB webcam fallback

Keys: q / ESC = quit
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.camera import XrealEyeCamera, WebcamFallback  # noqa: E402
from src.tracking import HandTracker  # noqa: E402
from src.mapping.filters import AngleFilter, SignalFilter  # noqa: E402


# MediaPipe hand skeleton connections (landmark index pairs)
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
    (5, 9), (9, 13), (13, 17),
]


def wrist_roll_deg(landmarks: list[tuple[float, float, float]]) -> float:
    index_mcp, pinky_mcp = landmarks[5], landmarks[17]
    dx = pinky_mcp[0] - index_mcp[0]
    dy = pinky_mcp[1] - index_mcp[1]
    return math.degrees(math.atan2(dy, dx))


def pinch_norm(landmarks: list[tuple[float, float, float]]) -> float:
    thumb, index = landmarks[4], landmarks[8]
    wrist, middle = landmarks[0], landmarks[9]
    pinch = math.hypot(thumb[0] - index[0], thumb[1] - index[1])
    size = math.hypot(middle[0] - wrist[0], middle[1] - wrist[1]) + 1e-6
    return max(0.0, min(1.0, pinch / (size * 2.0)))


def hand_size(landmarks: list[tuple[float, float, float]]) -> float:
    wrist, middle = landmarks[0], landmarks[9]
    return math.hypot(middle[0] - wrist[0], middle[1] - wrist[1])


def draw_hand(vis: np.ndarray, landmarks, fist: bool) -> None:
    h, w = vis.shape[:2]
    pts = [(int(lm[0] * w), int(lm[1] * h)) for lm in landmarks]
    color = (0, 0, 255) if fist else (0, 255, 0)
    for a, b in HAND_CONNECTIONS:
        cv2.line(vis, pts[a], pts[b], color, 2, cv2.LINE_AA)
    for x, y in pts:
        cv2.circle(vis, (x, y), 3, (0, 128, 255), -1, cv2.LINE_AA)


def main() -> None:
    parser = argparse.ArgumentParser(description="Hand tracking test (Eye / webcam)")
    parser.add_argument("--webcam", action="store_true", help="Use USB webcam fallback")
    parser.add_argument("--webcam-index", type=int, default=0)
    args = parser.parse_args()

    hand_model = ROOT / "models" / "gesture_recognizer.task"
    if not hand_model.is_file():
        print(f"Missing model: {hand_model}")
        print("Copy gesture_recognizer.task into robot/models/")
        sys.exit(1)

    if args.webcam:
        cam = WebcamFallback(device_index=args.webcam_index)
        source = "webcam"
    else:
        cam = XrealEyeCamera()
        source = "eye"

    print(f"Opening camera source={source!r} ...")
    opened = cam.open()
    if not opened:
        # Don't hard-exit: the Eye goes silent whenever Spatial Anchor drops.
        # Keep a window up and retry so it recovers without a relaunch.
        print("Camera not streaming yet. For Eye: turn Spatial Anchor ON.")
        print("Waiting for the stream (window stays open; press q to quit) ...")

    tracker = HandTracker(
        model_path=str(hand_model),
        min_detection_confidence=0.25,
        min_tracking_confidence=0.25,
        fist_score_threshold=0.5,
        min_hand_size=0.06,
        hold_frames=8,
    )
    roll_filter = AngleFilter(alpha=0.12, deadzone_deg=4.0)
    pinch_filter = SignalFilter(alpha=0.25)
    missed_frames = 0
    RESET_AFTER_MISSES = 15  # ~0.5s of sustained loss before filters reset
    if opened:
        print("Ready. Palm toward Eye, dark backdrop, fill ~1/4 of frame.")
        print("VIDEO-mode tracking + landmark hold. Press q to quit.")
    print("Roll/pinch shown as SMOOTHED (raw in console).")

    win = "Hand Tracking (hackathon robot/)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 1024, 756)

    fps_t0 = time.perf_counter()
    fps_n = 0
    fps = 0.0
    last_print = 0.0
    waiting_since = None if opened else time.perf_counter()
    next_reopen = 0.0

    try:
        while True:
            ok, frame = cam.read()
            if not ok or frame is None:
                now = time.perf_counter()
                if waiting_since is None:
                    waiting_since = now
                # If open() bailed, the socket is closed — retry periodically.
                if not cam.is_opened() and now >= next_reopen:
                    next_reopen = now + 3.0
                    cam.open()

                placeholder = np.zeros((378, 512, 3), dtype=np.uint8)
                cv2.putText(
                    placeholder,
                    "NO CAMERA FEED",
                    (90, 160),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    placeholder,
                    f"waiting {now - waiting_since:.0f}s - turn Spatial Anchor ON",
                    (40, 200),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 165, 255),
                    1,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    placeholder,
                    "auto-recovers when stream returns   |   q = quit",
                    (40, 230),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (200, 200, 200),
                    1,
                    cv2.LINE_AA,
                )
                cv2.imshow(win, placeholder)
                if (cv2.waitKey(30) & 0xFF) in (ord("q"), 27):
                    break
                continue
            waiting_since = None

            # Display as BGR; tracking/gesture get grayscale (or BGR converted inside)
            if len(frame.shape) == 2:
                vis = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                gray = frame
            else:
                vis = frame.copy()
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            tracking = tracker.process(gray)
            fist = bool(tracking and tracking.fist)
            gesture_name = tracking.gesture if tracking else None

            fps_n += 1
            now = time.perf_counter()
            if now - fps_t0 >= 0.5:
                fps = fps_n / (now - fps_t0)
                fps_t0 = now
                fps_n = 0

            if tracking is not None:
                missed_frames = 0
                draw_hand(vis, tracking.landmarks, fist)
                x, y, _ = tracking.wrist_position
                roll_raw = wrist_roll_deg(tracking.landmarks)
                pinch_raw = pinch_norm(tracking.landmarks)
                roll = roll_filter.update(roll_raw)
                pinch = pinch_filter.update(pinch_raw)
                size = tracking.hand_size or hand_size(tracking.landmarks)

                cv2.putText(
                    vis,
                    f"{source} | HAND | FPS {fps:.1f}",
                    (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    vis,
                    f"pos  x={x:.2f}  y={y:.2f}   (0-1 normalized)",
                    (10, 56),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    vis,
                    f"roll {roll:+.1f} deg (raw {roll_raw:+.0f})   pinch {pinch:.2f}   size {size:.3f}",
                    (10, 80),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
                fist_txt = "FIST (CLUTCH ON)" if fist else f"open ({gesture_name or 'none'})"
                cv2.putText(
                    vis,
                    fist_txt,
                    (10, 108),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 0, 255) if fist else (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )
                if now - last_print > 0.5:
                    print(
                        f"hand x={x:.3f} y={y:.3f} "
                        f"roll={roll:+.1f}deg (raw={roll_raw:+.1f}) "
                        f"pinch={pinch:.3f} size={size:.3f} fist={fist} "
                        f"gesture={gesture_name or '-'}"
                    )
                    last_print = now
            else:
                # Detection flickers frame-to-frame on the grayscale feed;
                # resetting immediately would make smoothing a no-op.
                missed_frames += 1
                if missed_frames >= RESET_AFTER_MISSES:
                    roll_filter.reset()
                    pinch_filter.reset()
                cv2.putText(
                    vis,
                    f"{source} | no hand | FPS {fps:.1f}",
                    (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 165, 255),
                    2,
                    cv2.LINE_AA,
                )

            cv2.imshow(win, vis)
            if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                break
    finally:
        tracker.close()
        cam.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Print relative teleop target position from the Eye (or webcam) feed.

Uses HandTracker (landmarks + fist) → RelativeTeleop → prints:
  target xyz  (starts 0,0,0; fist freezes; open hand moves relative)
  gripper     (0 closed .. 1 open)

Usage (from robot/):
  python scripts/test_target_position.py
  python scripts/test_target_position.py --webcam

Keys:
  q / ESC  quit
  r        reset target back to 0,0,0
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.camera import XrealEyeCamera, WebcamFallback  # noqa: E402
from src.mapping.relative_teleop import RelativeTeleop  # noqa: E402
from src.tracking import HandTracker  # noqa: E402


HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
    (5, 9), (9, 13), (13, 17),
]


def draw_hand(vis, landmarks, fist: bool) -> None:
    h, w = vis.shape[:2]
    pts = [(int(lm[0] * w), int(lm[1] * h)) for lm in landmarks]
    color = (0, 0, 255) if fist else (0, 255, 0)
    for a, b in HAND_CONNECTIONS:
        cv2.line(vis, pts[a], pts[b], color, 2, cv2.LINE_AA)
    for x, y in pts:
        cv2.circle(vis, (x, y), 3, (0, 128, 255), -1, cv2.LINE_AA)


def main() -> None:
    parser = argparse.ArgumentParser(description="Print relative teleop target")
    parser.add_argument("--webcam", action="store_true")
    parser.add_argument("--webcam-index", type=int, default=0)
    args = parser.parse_args()

    model = ROOT / "models" / "gesture_recognizer.task"
    if not model.is_file():
        print(f"Missing {model}")
        sys.exit(1)

    if args.webcam:
        cam = WebcamFallback(device_index=args.webcam_index)
        source = "webcam"
    else:
        cam = XrealEyeCamera()
        source = "eye"

    print(f"Opening camera source={source!r} ...")
    opened = cam.open()
    if not opened and source == "webcam":
        print("Failed to open webcam")
        sys.exit(1)
    if not opened:
        print("Eye not streaming yet — leave Spatial Anchor ON; window will wait.")

    tracker = HandTracker(
        model_path=str(model),
        min_detection_confidence=0.25,
        min_tracking_confidence=0.25,
        fist_score_threshold=0.5,
        min_hand_size=0.06,
        hold_frames=8,
    )
    teleop = RelativeTeleop()

    print("Relative teleop test")
    print("  open hand  = move target from current pose")
    print("  fist       = freeze target (clutch)")
    print("  pinch      = gripper 0..1")
    print("  r = reset to 0,0,0    q = quit")
    print("-" * 72)
    print(f"{'x':>8} {'y':>8} {'z':>8} {'grip':>6} {'roll':>8}  state")

    win = "Target Position (relative teleop)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 1024, 756)

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
                if not cam.is_opened() and now >= next_reopen:
                    next_reopen = now + 3.0
                    cam.open()
                placeholder = np.zeros((378, 512, 3), dtype=np.uint8)
                cv2.putText(
                    placeholder,
                    "NO CAMERA FEED",
                    (90, 170),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    placeholder,
                    "Spatial Anchor ON  |  q quit",
                    (60, 210),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 165, 255),
                    1,
                    cv2.LINE_AA,
                )
                cv2.imshow(win, placeholder)
                key = cv2.waitKey(30) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord("r"):
                    teleop.reset()
                    print("RESET → target (0, 0, 0)")
                continue
            waiting_since = None

            if len(frame.shape) == 2:
                vis = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                gray = frame
            else:
                vis = frame.copy()
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            tracking = tracker.process(gray)
            target = teleop.update(tracking)

            if tracking is not None:
                draw_hand(vis, tracking.landmarks, tracking.fist)

            state = (
                "CLUTCH"
                if target.clutched
                else ("TRACK" if target.valid else "NO HAND")
            )
            color = (
                (0, 0, 255)
                if target.clutched
                else ((0, 255, 0) if target.valid else (0, 165, 255))
            )

            cv2.putText(
                vis,
                f"{source} | {state}",
                (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                color,
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                vis,
                f"target  x={target.x:+.3f}  y={target.y:+.3f}  z={target.z:+.3f}",
                (10, 58),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                vis,
                f"gripper={target.gripper:.2f}   roll={target.wrist_roll:+.1f}deg",
                (10, 86),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                vis,
                "fist=freeze   r=reset   q=quit",
                (10, 114),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (180, 180, 180),
                1,
                cv2.LINE_AA,
            )

            now = time.perf_counter()
            if now - last_print > 0.2:
                print(
                    f"{target.x:+8.3f} {target.y:+8.3f} {target.z:+8.3f} "
                    f"{target.gripper:6.2f} {target.wrist_roll:+8.1f}  {state}"
                )
                last_print = now

            cv2.imshow(win, vis)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("r"):
                teleop.reset()
                print("RESET → target (0, 0, 0)")
    finally:
        tracker.close()
        cam.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

"""M1 — MediaPipe hand landmarks from Eye or webcam.

Usage (from armteleop/):
  python scripts/m1_hand_test.py              # uses config.yaml camera.source
  python scripts/m1_hand_test.py --source eye
  python scripts/m1_hand_test.py --source webcam

Keys: q = quit
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from camera import make_camera  # noqa: E402
from hand_tracking import draw_hand, make_hand_tracker  # noqa: E402


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="M1 hand landmark visualization")
    parser.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    parser.add_argument("--source", choices=["eye", "webcam"], default=None)
    parser.add_argument("--webcam-index", type=int, default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.source:
        cfg.setdefault("camera", {})["source"] = args.source
    if args.webcam_index is not None:
        cfg.setdefault("camera", {})["webcam_index"] = args.webcam_index

    flip = bool(cfg.get("camera", {}).get("flip_horizontal", True))
    source_name = cfg["camera"]["source"]
    # Always enhance for Eye; light enhance helps webcam too in dim rooms
    enhance = True

    print(f"Opening camera source={source_name!r} ...")
    cam = make_camera(cfg)
    tracker = make_hand_tracker(cfg, root=ROOT)
    print("Ready. Hold your hand in front of the Eye cameras. Press q to quit.")
    if source_name == "eye":
        print("Tip: Eye looks forward from the glasses — hand must be in that view + bright light.")

    win = "M1 Hand Tracking (XREAL Eye)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 1024, 756)

    fps_t0 = time.perf_counter()
    fps_n = 0
    fps = 0.0
    last_print = 0.0

    import numpy as np

    no_feed_since: float | None = None

    try:
        while True:
            frame = cam.read()
            if frame is None:
                # Keep the window responsive and show what's wrong instead of
                # spinning silently (freezes the window: "Not Responding").
                now = time.perf_counter()
                if no_feed_since is None:
                    no_feed_since = now
                placeholder = np.zeros((378, 512, 3), dtype=np.uint8)
                cv2.putText(placeholder, "NO CAMERA FEED", (90, 170),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2, cv2.LINE_AA)
                cv2.putText(placeholder, f"waiting {now - no_feed_since:.0f}s - check Spatial Anchor",
                            (60, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 1, cv2.LINE_AA)
                cv2.putText(placeholder, "q = quit", (60, 240),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA)
                cv2.imshow(win, placeholder)
                if (cv2.waitKey(30) & 0xFF) == ord("q"):
                    break
                continue
            no_feed_since = None

            if flip:
                frame = cv2.flip(frame, 1)

            pose = tracker.process(frame, enhance=enhance)
            vis = draw_hand(frame, pose)

            fps_n += 1
            now = time.perf_counter()
            if now - fps_t0 >= 0.5:
                fps = fps_n / (now - fps_t0)
                fps_t0 = now
                fps_n = 0

            status = "HAND" if pose.present else "no hand"
            cv2.putText(
                vis,
                f"{source_name} | {status} | FPS {fps:.1f}",
                (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0) if pose.present else (0, 165, 255),
                2,
                cv2.LINE_AA,
            )
            if pose.present:
                # All values needed for teleop, visible for bugchecking:
                cv2.putText(
                    vis,
                    f"pos  x={pose.x:.2f}  y={pose.y:.2f}   (0-1 normalized)",
                    (10, 56),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    vis,
                    f"roll {pose.roll:+.1f} deg   pinch {pose.pinch:.2f}   depth(size) {pose.depth_proxy:.3f}",
                    (10, 80),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
                fist_txt = "FIST (CLUTCH ON)" if pose.fist else f"open hand ({pose.gesture or 'none'})"
                cv2.putText(
                    vis,
                    fist_txt,
                    (10, 108),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 0, 255) if pose.fist else (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )
                if now - last_print > 0.5:
                    print(
                        f"hand x={pose.x:.3f} y={pose.y:.3f} roll={pose.roll:+.1f}deg "
                        f"pinch={pose.pinch:.3f} size={pose.depth_proxy:.3f} "
                        f"fist={pose.fist} gesture={pose.gesture or '-'}"
                    )
                    last_print = now

            cv2.imshow(win, vis)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                break
    finally:
        tracker.close()
        cam.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

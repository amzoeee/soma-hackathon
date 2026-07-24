"""M2 — Hand moves the arm (Zoe's architecture).

Fist = clutch (freeze). Open hand = engaged, motion relative to current pose.
Pinch = gripper. Palm roll = wrist_roll. ikpy IK seeded from servo encoders.

Usage:
  python scripts/m2_hand_to_arm.py --source eye
  python scripts/m2_hand_to_arm.py --source webcam --sim   # no arm, print goals
  python scripts/m2_hand_to_arm.py --source eye --mode full  # full state machine

Keys: ESC=e-stop  H=home  F=flag  T=takeover  R=resume  Q=quit
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

from arm import ArmController  # noqa: E402
from camera import make_camera  # noqa: E402
from display import OperatorHUD  # noqa: E402
from hand_tracking import draw_hand, make_hand_tracker  # noqa: E402
from ik import make_ik  # noqa: E402
from mapping import ClutchState, HandToArmMapper  # noqa: E402
from smoothing import HandSmoother  # noqa: E402
from state_machine import Mode, ModeController  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    parser.add_argument("--source", choices=["eye", "webcam"], default=None)
    parser.add_argument("--port", type=str, default=None)
    parser.add_argument("--sim", action="store_true", help="Force arm sim mode")
    parser.add_argument("--mode", choices=["takeover", "full"], default="takeover",
                        help="takeover=hand control always active; full=state machine demo")
    args = parser.parse_args()

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if args.source:
        cfg["camera"]["source"] = args.source
    if args.port:
        cfg["arm"]["port"] = args.port
    if args.sim:
        cfg["arm"]["sim"] = True

    cam = make_camera(cfg)
    tracker = make_hand_tracker(cfg, root=ROOT)
    s = cfg.get("smoothing", {})
    smoother = HandSmoother(
        min_cutoff=float(s.get("min_cutoff", 1.0)),
        beta=float(s.get("beta", 0.007)),
        pinch_ema_alpha=float(s.get("pinch_ema_alpha", 0.4)),
    )
    mapper = HandToArmMapper(cfg)
    clutch = ClutchState(debounce_frames=int(cfg.get("hand", {}).get("clutch_debounce_frames", 3)))
    ik = make_ik(cfg, root=ROOT)
    arm = ArmController(cfg)
    sm = ModeController(cfg)
    on_glasses = str(cfg.get("display", {}).get("target_monitor", "auto")) != "primary"
    hud = OperatorHUD(on_glasses=on_glasses)

    arm.connect()
    flip = bool(cfg["camera"].get("flip_horizontal", True))
    source_name = cfg["camera"]["source"]
    stall_threshold = float(cfg.get("arm", {}).get("stall_threshold_deg", 10.0))

    print("M2 ready (Zoe architecture).")
    print("  Open hand = control ACTIVE.  Fist = clutch/freeze.  Pinch = gripper.")
    print("  ESC=e-stop  H=home  F=flag  T=takeover  R=resume  Q=quit")

    keys_down: set[str] = set()
    estopped = False
    fps, fps_n, fps_t0 = 0.0, 0, time.perf_counter()
    frame_i = 0
    stalled: dict[str, float] = {}
    last_frame_t = time.perf_counter()
    warned_no_feed = False

    try:
        while True:
            frame = cam.read()
            if frame is None:
                # Keep the UI alive even with no camera — never freeze the window
                if time.perf_counter() - last_frame_t > 2.0:
                    if not warned_no_feed:
                        print("[m2] NO CAMERA FEED — if source=eye, check Spatial Anchor is ON")
                        warned_no_feed = True
                    import numpy as np
                    placeholder = np.zeros((378, 512, 3), dtype=np.uint8)
                    cv2.putText(placeholder, "NO CAMERA FEED", (60, 170),
                                cv2.FONT_HERSHEY_DUPLEX, 1.2, (60, 60, 230), 2)
                    cv2.putText(placeholder, "eye: turn Spatial Anchor ON", (60, 220),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (230, 230, 230), 2)
                    hud.render(
                        mode="ESTOP" if estopped else "TAKEOVER",
                        engaged=False, hand_present=False, camera_bgr=placeholder,
                        fps=0.0, source=source_name, arm_connected=not arm.sim,
                    )
                    if (cv2.waitKey(50) & 0xFF) == ord("q"):
                        break
                else:
                    time.sleep(0.005)
                continue
            last_frame_t = time.perf_counter()
            warned_no_feed = False
            if flip:
                frame = cv2.flip(frame, 1)
            frame_i += 1

            t = time.perf_counter()
            pose = smoother.filter(tracker.process(frame, enhance=True), t)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == 27:
                arm.set_torque(False)
                estopped = True
                keys_down.add("esc")
            elif key == ord("h") and not estopped:
                arm.home_arm()
            elif key in (ord("f"), ord("t")):
                keys_down.add(chr(key))
            elif key == ord("r"):
                keys_down.add("r")
                estopped = False

            mode = Mode.TAKEOVER if args.mode == "takeover" else sm.update(
                keys_down=keys_down, load=None
            )
            keys_down -= {"f", "t", "r", "esc"}

            engaged = clutch.update(pose) and not estopped
            control_active = (mode == Mode.TAKEOVER) and engaged

            if control_active:
                target = mapper.map(pose, engaged=True)
                # Seed IK from real encoder positions (feedback loop)
                ik.set_current(arm.read_positions())
                goals = ik.solve(target)
                if goals is not None:
                    goals["wrist_roll"] = target.wrist_roll  # hand roll, not IK's choice
                    arm.write_positions(goals)
            else:
                mapper.map(pose, engaged=False)  # keeps clutch anchor fresh

            # Stall check every ~15 frames (reads serial — don't spam)
            if frame_i % 15 == 0:
                stalled = arm.check_stall(stall_threshold)

            # Heartbeat so a silent death is localizable in the log
            if frame_i % 150 == 0:
                print(f"[m2] frame {frame_i}  fps={fps:.1f}  hand={pose.present}  engaged={engaged}")

            # Camera view with skeleton, embedded in the HUD
            vis = draw_hand(frame, pose)

            fps_n += 1
            now = time.perf_counter()
            if now - fps_t0 >= 0.5:
                fps = fps_n / (now - fps_t0)
                fps_t0, fps_n = now, 0
            hud.render(
                mode="ESTOP" if estopped else (mode.name if args.mode == "full" else "TAKEOVER"),
                engaged=engaged,
                hand_present=pose.present,
                camera_bgr=vis,
                gesture=pose.gesture,
                gripper_open=mapper._gripper_open,
                fps=fps,
                source=source_name,
                arm_connected=not arm.sim,
                positions=arm.read_positions() if frame_i % 5 == 0 or arm.sim else None,
                commanded=arm._last_cmd or None,
                stalled=stalled or None,
            )
    finally:
        tracker.close()
        arm.disconnect()
        cam.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

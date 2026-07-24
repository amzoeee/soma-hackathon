"""M0 — Arm hello world. Set arm.port in config.yaml first.

Usage:
  python scripts/m0_arm_hello.py
  python scripts/m0_arm_hello.py --port COM3
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arm import ArmController  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    parser.add_argument("--port", type=str, default=None)
    parser.add_argument("--nudge-deg", type=float, default=5.0)
    args = parser.parse_args()

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if args.port:
        cfg.setdefault("arm", {})["port"] = args.port
        cfg["arm"]["sim"] = False

    arm = ArmController(cfg)
    if arm.sim:
        print("ERROR: arm.port is still TBD. Pass --port COMx or edit config.yaml")
        print("Tip: python -m serial.tools.list_ports")
        sys.exit(1)

    print("Connecting... (wall power ON, clear the workspace)")
    arm.connect()
    pos = arm.read_positions()
    print("Present positions:")
    for k, v in pos.items():
        print(f"  {k:16s} {v:8.2f}")

    load = arm.read_load()
    print("Present load:")
    for k, v in load.items():
        print(f"  {k:16s} {v:8.2f}")

    joint = "shoulder_pan"
    print(f"\nNudging {joint} by +{args.nudge_deg}° in 2s... Ctrl+C to abort")
    time.sleep(2)
    goal = dict(pos)
    goal[joint] = pos[joint] + args.nudge_deg
    sent = arm.write_positions(goal)
    time.sleep(1.0)
    after = arm.read_positions()
    print(f"sent {joint}={sent.get(joint):.2f}  now={after[joint]:.2f}")
    print("If it moved the WRONG way, flip ik.joint_sign.shoulder_pan to -1 in config.yaml")

    print("Returning toward start...")
    arm.write_positions(pos)
    time.sleep(1.0)
    arm.disconnect()
    print("Done. Fill joint_sign + load_flag_threshold, then run M2.")


if __name__ == "__main__":
    main()

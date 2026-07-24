#!/usr/bin/env python3
"""
Passive observation script for LeRobot SO-101 follower arm.
Disables torque so you can move the arm freely by hand and continuously prints joint angles.
"""

import time
import argparse
from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

def read_observations(port: str):
    config = SO101FollowerConfig(port=port, id="follower")
    robot = SO101Follower(config)

    print(f"Connecting to robot on {port}...")
    robot.connect()

    try:
        # Disable torque on all motors so the user can move the arm by hand
        print("Disabling torque... You can now move the arm manually.")
        if hasattr(robot, 'bus'):
            robot.bus.disable_torque()
        elif hasattr(robot, 'robot') and hasattr(robot.robot, 'bus'):
            robot.robot.bus.disable_torque()

        print("\nPress Ctrl+C to stop.\n")
        print("-" * 75)
        print(f"{'shoulder_pan':<12} | {'shoulder_lift':<12} | {'elbow_flex':<12} | {'wrist_flex':<12} | {'wrist_roll':<12} | {'gripper':<10}")
        print("-" * 75)

        while True:
            obs = robot.get_observation()
            
            # Format and print positions cleanly
            pan = obs.get("shoulder_pan.pos", 0.0)
            lift = obs.get("shoulder_lift.pos", 0.0)
            elbow = obs.get("elbow_flex.pos", 0.0)
            w_flex = obs.get("wrist_flex.pos", 0.0)
            w_roll = obs.get("wrist_roll.pos", 0.0)
            grip = obs.get("gripper.pos", 0.0)

            print(f"{pan:<12.2f} | {lift:<12.2f} | {elbow:<12.2f} | {w_flex:<12.2f} | {w_roll:<12.2f} | {grip:<10.2f}\r", end="")
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n\nStopped by user.")
    finally:
        print("Disconnecting...")
        robot.disconnect()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read arm joint observations while torque is disabled.")
    parser.add_argument("--port", type=str, default="/dev/tty.usbmodem5A460820851", help="Serial port")
    args = parser.parse_args()

    read_observations(args.port)

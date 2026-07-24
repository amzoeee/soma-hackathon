#!/usr/bin/env python3
"""
Test script to move the LeRobot SO-101 follower arm to a target joint position.
Explicitly enables motor torque before sending actions.
"""

import time
import argparse
from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

def move_robot(port: str, target_angles: dict, duration: float = 10.0, steps: int = 200):
    config = SO101FollowerConfig(port=port, id="follower")
    robot = SO101Follower(config)

    print(f"Connecting to robot at {port}...")
    robot.connect()

    try:
        # Explicitly enable torque on all motors
        print("Enabling motor torque...")
        if hasattr(robot, 'bus') and hasattr(robot.bus, 'enable_torque'):
            robot.bus.enable_torque()
        elif hasattr(robot, 'robot') and hasattr(robot.robot, 'bus'):
            robot.robot.bus.enable_torque()

        current_obs = robot.get_observation()
        print("Current observation:", current_obs)

        # Get starting positions (fallback to target if missing from obs key format)
        start_positions = {}
        for key in target_angles:
            if key in current_obs:
                start_positions[key] = current_obs[key]
            else:
                start_positions[key] = target_angles[key]

        print("Smoothly moving to target angles...")
        sleep_time = duration / steps

        for i in range(1, steps + 1):
            alpha = i / steps
            interpolated_action = {}
            for key, target_val in target_angles.items():
                start_val = start_positions[key]
                interpolated_action[key] = start_val + alpha * (target_val - start_val)

            current_obs = robot.get_observation()
            print("Current observation:", current_obs)

            robot.send_action(interpolated_action)
            time.sleep(sleep_time)

        print("Finished movement. Final observation:")
        print(robot.get_observation())

    finally:
        print("Done!")
        time.sleep(10000)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Move SO-101 follower arm to target joint angles.")
    parser.add_argument("--port", type=str, default="/dev/tty.usbmodem5A460820851", help="Serial port")
    args = parser.parse_args()

    # Define target joint positions
    target_angles = {
        "shoulder_pan.pos": 0.0,
        "shoulder_lift.pos": 0.0,
        "elbow_flex.pos": 0.0,
        "wrist_flex.pos": 0.0,
        "wrist_roll.pos": 0.0,
        "gripper.pos": 50.0,
    }

    move_robot(args.port, target_angles)

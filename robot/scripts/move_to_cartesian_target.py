#!/usr/bin/env python3
"""
Script to move the LeRobot SO-101 follower arm to a 3D target Cartesian position (X, Y, Z in meters)
using ikpy and the so101.urdf file. Explicitly enables motor torque before sending actions.
"""

import sys
import os
import time
import argparse

# Add repo root to python path dynamically
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Try imports for both repo structures
try:
    from robot.src.ik.solver import IKSolver
except ModuleNotFoundError:
    from src.ik.solver import IKSolver

from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

def move_to_cartesian_target(port: str, target_xyz: tuple, duration: float = 5.0, steps: int = 200):
    urdf_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../config/so101.urdf"))
    if not os.path.exists(urdf_path):
        print(f"Error: URDF file not found at {urdf_path}")
        return

    # Initialize IK Solver
    solver = IKSolver(urdf_path=urdf_path)
    print(f"Solving IK for target position X={target_xyz[0]}m, Y={target_xyz[1]}m, Z={target_xyz[2]}m...")

    # Solve IK (returns dict of degrees for joints)
    joint_degrees = solver.solve(target_position=target_xyz)

    print("\nSolved joint angles (degrees):")
    for joint, deg in joint_degrees.items():
        print(f"  {joint}: {deg:.2f}°")

    # Map to LeRobot action keys
    target_action = {
        "shoulder_pan.pos": joint_degrees.get("shoulder_pan", 0.0),
        "shoulder_lift.pos": joint_degrees.get("shoulder_lift", 0.0),
        "elbow_flex.pos": joint_degrees.get("elbow_flex", 0.0),
        "wrist_flex.pos": joint_degrees.get("wrist_flex", 0.0),
        "wrist_roll.pos": 0.0,
        "gripper.pos": 50.0,
    }

    # Connect to robot and execute smooth movement
    config = SO101FollowerConfig(port=port, id="follower")
    robot = SO101Follower(config)

    print(f"\nConnecting to robot at {port}...")
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

        # Get starting joint positions
        start_positions = {}
        for key in target_action:
            if key in current_obs:
                start_positions[key] = current_obs[key]
            else:
                start_positions[key] = target_action[key]

        print(f"Smoothly moving arm to target over {duration} seconds...")
        sleep_time = duration / steps

        for i in range(1, steps + 1):
            alpha = i / steps
            interpolated_action = {}
            for key, target_val in target_action.items():
                start_val = start_positions[key]
                interpolated_action[key] = start_val + alpha * (target_val - start_val)

            current_obs = robot.get_observation()
            print("Current observation:", current_obs)

            robot.send_action(interpolated_action)
            time.sleep(sleep_time)

        final_obs = robot.get_observation()
        print("\nMovement complete. Final observation:")
        print(final_obs)

        # Calculate actual end cartesian position via FK
        final_joint_angles = [
            final_obs.get("shoulder_pan.pos", target_action["shoulder_pan.pos"]),
            final_obs.get("shoulder_lift.pos", target_action["shoulder_lift.pos"]),
            final_obs.get("elbow_flex.pos", target_action["elbow_flex.pos"]),
            final_obs.get("wrist_flex.pos", target_action["wrist_flex.pos"]),
        ]
        actual_xyz = solver.forward_kinematics(final_joint_angles)

        print("\n" + "=" * 50)
        print("TARGET END STATE SUMMARY")
        print("=" * 50)
        print(f"Target Cartesian Position (X, Y, Z): ({target_xyz[0]:.4f}, {target_xyz[1]:.4f}, {target_xyz[2]:.4f}) m")
        print(f"Actual Cartesian Position (FK)     : ({actual_xyz[0]:.4f}, {actual_xyz[1]:.4f}, {actual_xyz[2]:.4f}) m")
        print("Target Joint Angles:")
        for joint, angle in target_action.items():
            print(f"  {joint:20s}: {angle:+.2f}°")
        print("=" * 50)

    finally:
        print("Done!")
        time.sleep(10000)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Move SO-101 arm to target X, Y, Z coordinates using IK.")
    parser.add_argument("--port", type=str, default="/dev/tty.usbmodem5A460820851", help="Serial port")
    # so101.urdf is right-handed: +x forward, +y left, +z up. At all joints 0
    # the tool sits at (0.391, 0.000, 0.227), and shoulder_pan sweeps y.
    parser.add_argument("--x", type=float, default=0.20, help="Target X in meters (forward reach)")
    parser.add_argument("--y", type=float, default=0.0, help="Target Y in meters (lateral, + is left)")
    parser.add_argument("--z", type=float, default=0.20, help="Target Z in meters (height)")
    args = parser.parse_args()

    move_to_cartesian_target(args.port, (args.x, args.y, args.z))

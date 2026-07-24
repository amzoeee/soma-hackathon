#!/usr/bin/env python3
"""
Test script for SO-101 Inverse Kinematics (IK) solver.
Tests forward kinematics (FK) and inverse kinematics (IK) using ikpy and so101.urdf.
"""

import sys
import os
import math
import numpy as np

# Ensure project root & robot directory are in python path dynamically
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROBOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "../../"))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../../../"))

for p in (ROBOT_DIR, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from src.ik.solver import IKSolver
    from src.ik.conversions import degrees_to_radians, radians_to_degrees
except ModuleNotFoundError:
    from robot.src.ik.solver import IKSolver
    from robot.src.ik.conversions import degrees_to_radians, radians_to_degrees

def test_ik_solver():
    urdf_path = os.path.abspath(os.path.join(SCRIPT_DIR, "../../config/so101.urdf"))
    print(f"Loading URDF from: {urdf_path}")

    if not os.path.exists(urdf_path):
        print(f"Error: URDF file not found at {urdf_path}")
        return

    solver = IKSolver(urdf_path=urdf_path)
    print("IK Solver initialized successfully.")

    # Test 1: Forward Kinematics for zero joint angles
    neutral_angles_rad = [0.0, 0.0, 0.0, 0.0]
    fk_pos = solver.forward_kinematics(neutral_angles_rad)
    print("\n--- Test 1: Forward Kinematics (Neutral Position) ---")
    print(f"Input Angles (deg): [0.0, 0.0, 0.0, 0.0]")
    print(f"Computed End-Effector Target (x, y, z meters): ({fk_pos[0]:.4f}, {fk_pos[1]:.4f}, {fk_pos[2]:.4f})")

    # Test 2: Solve IK for the FK target position (Roundtrip test)
    print("\n--- Test 2: Inverse Kinematics (Roundtrip Solve) ---")
    ik_solution = solver.solve(target_position=fk_pos)
    print("IK Solved Joint Angles (deg):")
    for joint_name, val_deg in ik_solution.items():
        print(f"  {joint_name}: {val_deg:.2f}°")

    # Test 3: Solve IK for a target reach position within SO-101 workspace
    target_reach = (0.25, 0.10, 0.20)  # x=0.25m, y=0.10m forward/side reach, z=0.20m up
    print(f"\n--- Test 3: Inverse Kinematics for Custom Target {target_reach} ---")
    ik_solution_reach = solver.solve(target_position=target_reach)
    print("IK Solved Joint Angles (deg):")
    for joint_name, val_deg in ik_solution_reach.items():
        print(f"  {joint_name}: {val_deg:.2f}°")

    # Verify FK from solved reach angles matches requested target (forward_kinematics expects degrees)
    solved_degs = [ik_solution_reach[j] for j in ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex"]]
    reach_fk = solver.forward_kinematics(solved_degs)
    err = np.linalg.norm(np.array(reach_fk) - np.array(target_reach))
    print(f"FK Verification Position: ({reach_fk[0]:.4f}, {reach_fk[1]:.4f}, {reach_fk[2]:.4f})")
    print(f"Position Error: {err * 1000:.2f} mm")

    if err < 0.01:
        print("\nSUCCESS: IK solver verified working clean.")
    else:
        print("\nWARNING: High error in IK solution.")

if __name__ == "__main__":
    test_ik_solver()

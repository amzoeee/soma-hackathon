"""Inverse kinematics solver for LeRobot SO-101 using ikpy."""

import logging
from typing import Dict, List, Optional, Tuple

import ikpy.chain
import numpy as np

logger = logging.getLogger(__name__)

class IKSolver:
    """Inverse kinematics solver for the SO-101 robot arm."""
    
    # Joint names in order for SO-101
    JOINT_NAMES = [
        "shoulder_pan",
        "shoulder_lift",
        "elbow_flex",
        "wrist_flex"
    ]
    
    def __init__(self, urdf_path: str):
        """
        Initializes the IK solver.
        """
        self.urdf_path = urdf_path
        try:
            self.chain = ikpy.chain.Chain.from_urdf_file(self.urdf_path)
            logger.info(f"Initialized IK chain with {len(self.chain.links)} links.")
        except Exception as e:
            logger.error(f"Failed to load URDF from {urdf_path}: {e}")
            raise

    def solve(self, target_position: Tuple[float, float, float], current_angles: Optional[List[float]] = None) -> Dict[str, float]:
        """
        Solves IK for the given target position.
        """
        target_pos_np = np.array(target_position)
        
        # Compute inverse kinematics using ikpy
        ik_solution = self.chain.inverse_kinematics(target_position=target_pos_np)
        
        active_joints = [i for i, link in enumerate(self.chain.links) if link.has_rotation]
        
        result = {}
        for i, joint_name in enumerate(self.JOINT_NAMES):
            if i < len(active_joints):
                joint_idx = active_joints[i]
                result[joint_name] = float(ik_solution[joint_idx])
            else:
                result[joint_name] = 0.0
                
        return result

    def forward_kinematics(self, joint_angles: List[float]) -> Tuple[float, float, float]:
        """
        Computes forward kinematics for the given joint angles.
        """
        full_angles = [0.0] * len(self.chain.links)
        
        active_joints = [i for i, link in enumerate(self.chain.links) if link.has_rotation]
        
        for i, angle in enumerate(joint_angles):
            if i < len(active_joints):
                joint_idx = active_joints[i]
                full_angles[joint_idx] = angle
                
        fk_matrix = self.chain.forward_kinematics(full_angles)
        
        x, y, z = fk_matrix[:3, 3]
        return float(x), float(y), float(z)

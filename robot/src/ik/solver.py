"""Inverse kinematics solver for LeRobot SO-101 using ikpy.

Outputs joint angles in DEGREES, matching LeRobot's .pos units
(SO101FollowerConfig(use_degrees=True)). Seed the solver with the arm's
actual encoder angles each cycle so solutions stay continuous.
"""

from __future__ import annotations

import logging
import math
import warnings
from typing import Dict, List, Optional, Tuple

import ikpy.chain
import numpy as np

logger = logging.getLogger(__name__)


class IKSolver:
    """Inverse kinematics solver for the SO-101 robot arm."""

    JOINT_NAMES = [
        "shoulder_pan",
        "shoulder_lift",
        "elbow_flex",
        "wrist_flex",
    ]

    LIMITS_DEG = {
        "shoulder_pan": (-110.0, 110.0),
        "shoulder_lift": (-100.0, 100.0),
        "elbow_flex": (-97.0, 97.0),
        "wrist_flex": (-95.0, 95.0),
    }

    MISS_TOLERANCE_M = 0.03

    def __init__(self, urdf_path: str):
        self.urdf_path = urdf_path
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.chain = ikpy.chain.Chain.from_urdf_file(
                    self.urdf_path,
                    base_elements=["base_link"],
                    active_links_mask=[False, True, True, True, True, True, False],
                )
            logger.info("Initialized IK chain with %d links.", len(self.chain.links))
        except Exception as e:
            logger.error("Failed to load URDF from %s: %s", urdf_path, e)
            raise
        self._q = np.zeros(len(self.chain.links))

    def solve(
        self,
        target_position: Tuple[float, float, float],
        current_angles: Optional[List[float]] = None,
    ) -> Dict[str, float]:
        if current_angles:
            for i, angle_deg in enumerate(current_angles[: len(self.JOINT_NAMES)]):
                self._q[i + 1] = math.radians(angle_deg)

        target = np.array(target_position, dtype=float)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                q = self.chain.inverse_kinematics(target, initial_position=self._q)
        except Exception as e:
            logger.warning("IK solve failed: %s -- holding last solution", e)
            return self._angles_from_q(self._q)

        reached = self.chain.forward_kinematics(q)[:3, 3]
        miss = float(np.linalg.norm(reached - target))
        if miss > self.MISS_TOLERANCE_M:
            logger.debug("IK miss %.3fm > tolerance -- holding last solution", miss)
            return self._angles_from_q(self._q)

        self._q = q
        return self._angles_from_q(q)

    def _angles_from_q(self, q: np.ndarray) -> Dict[str, float]:
        result = {}
        for i, joint_name in enumerate(self.JOINT_NAMES):
            deg = math.degrees(float(q[i + 1]))
            lo, hi = self.LIMITS_DEG[joint_name]
            result[joint_name] = max(lo, min(hi, deg))
        return result

    def forward_kinematics(self, joint_angles: List[float]) -> Tuple[float, float, float]:
        full_angles = np.zeros(len(self.chain.links))
        for i, angle_deg in enumerate(joint_angles[: len(self.JOINT_NAMES)]):
            full_angles[i + 1] = math.radians(angle_deg)
        fk_matrix = self.chain.forward_kinematics(full_angles)
        x, y, z = fk_matrix[:3, 3]
        return float(x), float(y), float(z)

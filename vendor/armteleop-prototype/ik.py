"""IK for SO-101: ikpy URDF solver (primary) + Tier A analytic fallback.

Both return joint goals in DEGREES keyed by LeRobot joint names, gripper 0-100
passed through. wrist_roll in the output is a placeholder — the caller
overrides it with the hand-derived roll (Zoe's architecture).
"""

from __future__ import annotations

import math
import warnings
from pathlib import Path
from typing import Any

import numpy as np

from mapping import ArmTarget

JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]

# URDF limits (rad→deg, rounded slightly inward)
LIMITS_DEG = {
    "shoulder_pan": (-110.0, 110.0),
    "shoulder_lift": (-100.0, 100.0),
    "elbow_flex": (-97.0, 97.0),
    "wrist_flex": (-95.0, 95.0),
    "wrist_roll": (-157.0, 163.0),
}


def _apply_signs_and_limits(goals: dict[str, float], sign: dict[str, float]) -> dict[str, float]:
    for name in JOINTS:
        goals[name] = goals[name] * sign.get(name, 1.0)
        lo, hi = LIMITS_DEG[name]
        goals[name] = max(lo, min(hi, goals[name]))
    goals["gripper"] = max(0.0, min(100.0, goals["gripper"]))
    return goals


def _read_signs(ik_cfg: dict[str, Any]) -> dict[str, float]:
    signs = ik_cfg.get("joint_sign", {})
    return {j: float(signs.get(j, 1)) for j in JOINTS}


class IkpyIK:
    """Numerical position IK against the SO-101 URDF via ikpy.

    Seeded each cycle from actual servo positions (set_current), so solutions
    stay continuous and follow the real arm, not the commanded fiction.
    """

    def __init__(self, config: dict[str, Any], root: Path | None = None):
        from ikpy.chain import Chain

        ik = config.get("ik", config)
        urdf = Path(ik.get("urdf_path", "assets/so101.urdf"))
        if not urdf.is_absolute():
            urdf = (root or Path.cwd()) / urdf
        if not urdf.is_file():
            raise FileNotFoundError(f"URDF not found: {urdf}")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.chain = Chain.from_urdf_file(
                str(urdf),
                base_elements=["base_link"],
                active_links_mask=[False, True, True, True, True, True, False],
            )
        self.sign = _read_signs(ik)
        # q layout: [base(fixed), pan, lift, elbow, wrist_flex, wrist_roll, tip(fixed)]
        self._q = np.zeros(len(self.chain.links))

    def set_current(self, positions_deg: dict[str, float]) -> None:
        """Seed the solver with actual servo positions (from get_observation)."""
        for i, name in enumerate(JOINTS, start=1):
            if name in positions_deg:
                self._q[i] = math.radians(positions_deg[name] / self.sign.get(name, 1.0))

    def solve(self, target: ArmTarget) -> dict[str, float] | None:
        if not target.valid:
            return None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                q = self.chain.inverse_kinematics(
                    [target.x, target.y, target.z],
                    initial_position=self._q,
                )
        except Exception:
            return None

        # Reject if the solution misses badly (target outside workspace)
        reached = self.chain.forward_kinematics(q)[:3, 3]
        err = float(np.linalg.norm(reached - [target.x, target.y, target.z]))
        if err > 0.03:  # 3 cm tolerance
            return None

        self._q = q
        goals = {name: math.degrees(q[i]) for i, name in enumerate(JOINTS, start=1)}
        goals["gripper"] = float(target.gripper)
        return _apply_signs_and_limits(goals, self.sign)


class AnalyticIK:
    """Tier A closed-form position IK (fallback). Fixed wrist attitude."""

    def __init__(self, config: dict[str, Any]):
        ik = config.get("ik", config)
        self.L1 = float(ik["L1"])
        self.L2 = float(ik["L2"])
        self.z0 = float(ik["z0"])
        self.wrist_flex = float(ik["wrist_flex_fixed_deg"])
        self.sign = _read_signs(ik)

    def set_current(self, positions_deg: dict[str, float]) -> None:
        pass  # closed-form, no seed needed

    def solve(self, target: ArmTarget) -> dict[str, float] | None:
        if not target.valid:
            return None

        x, y, z = target.x, target.y, target.z
        r = math.hypot(x, y)
        if r < 1e-4:
            return None

        pan = math.atan2(y, x)
        z_rel = z - self.z0
        dist = math.sqrt(r * r + z_rel * z_rel)
        reach_max = (self.L1 + self.L2) * 0.98
        reach_min = abs(self.L1 - self.L2) + 0.01
        if dist < 1e-6:
            return None
        # Project onto reachable annulus instead of failing at the edge
        if dist > reach_max or dist < reach_min:
            scale = (reach_max if dist > reach_max else reach_min) / dist
            r *= scale
            z_rel *= scale
            dist = reach_max if dist > reach_max else reach_min

        cos_e = (dist * dist - self.L1 * self.L1 - self.L2 * self.L2) / (2.0 * self.L1 * self.L2)
        cos_e = max(-1.0, min(1.0, cos_e))
        elbow = -math.acos(cos_e)  # elbow-up
        lift = math.atan2(z_rel, r) - math.atan2(
            self.L2 * math.sin(elbow), self.L1 + self.L2 * math.cos(elbow)
        )

        goals = {
            "shoulder_pan": math.degrees(pan),
            "shoulder_lift": math.degrees(lift),
            "elbow_flex": math.degrees(elbow),
            "wrist_flex": self.wrist_flex,
            "wrist_roll": 0.0,
            "gripper": float(target.gripper),
        }
        return _apply_signs_and_limits(goals, self.sign)


def make_ik(config: dict[str, Any], root: Path | None = None):
    tier = str(config.get("ik", {}).get("tier", "ikpy")).lower()
    if tier == "ikpy":
        try:
            return IkpyIK(config, root=root)
        except Exception as e:
            print(f"[ik] ikpy init failed ({e}); falling back to analytic")
    return AnalyticIK(config)

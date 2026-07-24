"""Hand tracking to end-effector mapping."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Tuple

from .filters import SignalFilter


@dataclass
class EETarget:
    """Target position and state for the end-effector."""

    x: float
    y: float
    z: float
    wrist_roll: float
    gripper: float


class HandToEEMapper:
    """Maps hand landmark positions to end-effector targets for the robot arm."""

    def __init__(
        self,
        hand_box: Dict[str, float],
        workspace_bounds: Dict[str, float],
        z_filter_alpha: float = 0.3,
        z_clamp_range: Tuple[float, float] = (0.05, 0.35),
    ):
        self.hand_box = hand_box
        self.workspace_bounds = workspace_bounds
        self.z_clamp_range = z_clamp_range
        self.z_filter = SignalFilter(alpha=z_filter_alpha)

    def map(self, tracking_result: Any) -> EETarget:
        landmarks = tracking_result.landmarks
        wrist = landmarks[0]
        thumb_tip = landmarks[4]
        index_tip = landmarks[8]

        hx, hy, hz = wrist[0], wrist[1], wrist[2]
        ee_x, ee_y, ee_z = self._scale_position(hx, hy, hz)
        wrist_roll = self.compute_wrist_roll(landmarks)
        gripper = self.compute_pinch_distance(thumb_tip, index_tip, landmarks)

        return EETarget(
            x=ee_x,
            y=ee_y,
            z=ee_z,
            wrist_roll=wrist_roll,
            gripper=gripper,
        )

    def compute_wrist_roll(self, landmarks: Any) -> float:
        """Wrist roll in DEGREES from knuckle line (index MCP -> pinky MCP)."""
        index_mcp = landmarks[5]
        pinky_mcp = landmarks[17]
        dx = pinky_mcp[0] - index_mcp[0]
        dy = pinky_mcp[1] - index_mcp[1]
        return math.degrees(math.atan2(dy, dx))

    def compute_pinch_distance(
        self, thumb_tip: Any, index_tip: Any, landmarks: Any
    ) -> float:
        """Pinch openness 0-100, normalized by hand size."""
        dx = thumb_tip[0] - index_tip[0]
        dy = thumb_tip[1] - index_tip[1]
        pinch = math.sqrt(dx * dx + dy * dy)

        wrist = landmarks[0]
        middle_mcp = landmarks[9]
        hand_size = (
            math.sqrt(
                (middle_mcp[0] - wrist[0]) ** 2 + (middle_mcp[1] - wrist[1]) ** 2
            )
            + 1e-6
        )
        normalized = max(0.0, min(1.0, pinch / (hand_size * 2.0)))
        return normalized * 100.0

    def _scale_position(
        self, hand_x: float, hand_y: float, hand_z: float
    ) -> Tuple[float, float, float]:
        nx = (hand_x - self.hand_box["x_min"]) / (
            self.hand_box["x_max"] - self.hand_box["x_min"]
        )
        ny = (hand_y - self.hand_box["y_min"]) / (
            self.hand_box["y_max"] - self.hand_box["y_min"]
        )
        nx = max(0.0, min(1.0, nx))
        ny = max(0.0, min(1.0, ny))

        wx = self.workspace_bounds["x_min"] + nx * (
            self.workspace_bounds["x_max"] - self.workspace_bounds["x_min"]
        )
        wy = self.workspace_bounds["y_min"] + ny * (
            self.workspace_bounds["y_max"] - self.workspace_bounds["y_min"]
        )

        raw_z = self.workspace_bounds["z_min"] + (hand_z + 0.1) * (
            self.workspace_bounds["z_max"] - self.workspace_bounds["z_min"]
        ) * 5
        filtered_z = self.z_filter.update(raw_z)
        cz = max(self.z_clamp_range[0], min(self.z_clamp_range[1], filtered_z))
        return wx, wy, cz

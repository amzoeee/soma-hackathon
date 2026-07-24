"""Hand tracking to end-effector mapping."""

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
        z_clamp_range: Tuple[float, float] = (0.05, 0.35)
    ):
        """
        Args:
            hand_box: dict with x_min, x_max, y_min, y_max (normalized hand coords)
            workspace_bounds: dict with x_min, x_max, y_min, y_max, z_min, z_max (meters)
            z_filter_alpha: alpha for exponential moving average on Z axis
            z_clamp_range: min and max clamp values for Z axis
        """
        self.hand_box = hand_box
        self.workspace_bounds = workspace_bounds
        self.z_clamp_range = z_clamp_range
        self.z_filter = SignalFilter(alpha=z_filter_alpha)

    def map(self, tracking_result: Any) -> EETarget:
        """
        Maps a hand tracking result to an end-effector target.
        """
        landmarks = tracking_result.landmarks
        wrist = landmarks[0]
        thumb_tip = landmarks[4]
        index_tip = landmarks[8]
        
        # Base position from wrist
        hx, hy, hz = wrist.x, wrist.y, wrist.z
        
        # Scale to workspace
        ee_x, ee_y, ee_z = self._scale_position(hx, hy, hz)
        
        # Compute wrist roll and gripper
        wrist_roll = self.compute_wrist_roll(landmarks)
        gripper = self.compute_pinch_distance(thumb_tip, index_tip)
        
        return EETarget(
            x=ee_x,
            y=ee_y,
            z=ee_z,
            wrist_roll=wrist_roll,
            gripper=gripper
        )

    def compute_wrist_roll(self, landmarks: Any) -> float:
        """
        Computes wrist roll from landmarks.
        Uses angle between wrist-to-middle-finger-base vector projected onto palm plane.
        """
        # Landmark 0: wrist, Landmark 9: middle finger base
        wrist = landmarks[0]
        middle_base = landmarks[9]
        
        # Simple projection on X-Y plane
        dx = middle_base.x - wrist.x
        dy = middle_base.y - wrist.y
        
        # Calculate angle in radians
        angle = math.atan2(dy, dx)
        return angle

    def compute_pinch_distance(self, thumb_tip: Any, index_tip: Any) -> float:
        """
        Computes pinch distance and normalizes it to 0-100.
        """
        dx = thumb_tip.x - index_tip.x
        dy = thumb_tip.y - index_tip.y
        dz = thumb_tip.z - index_tip.z
        
        # Euclidean distance
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        
        min_dist = 0.02
        max_dist = 0.15
        
        normalized = (dist - min_dist) / (max_dist - min_dist)
        normalized = max(0.0, min(1.0, normalized))
        
        return normalized * 100.0

    def _scale_position(self, hand_x: float, hand_y: float, hand_z: float) -> Tuple[float, float, float]:
        """Scales hand coordinates to workspace coordinates."""
        # Normalize X and Y from hand_box to 0-1
        nx = (hand_x - self.hand_box['x_min']) / (self.hand_box['x_max'] - self.hand_box['x_min'])
        ny = (hand_y - self.hand_box['y_min']) / (self.hand_box['y_max'] - self.hand_box['y_min'])
        
        nx = max(0.0, min(1.0, nx))
        ny = max(0.0, min(1.0, ny))
        
        wx = self.workspace_bounds['x_min'] + nx * (self.workspace_bounds['x_max'] - self.workspace_bounds['x_min'])
        wy = self.workspace_bounds['y_min'] + ny * (self.workspace_bounds['y_max'] - self.workspace_bounds['y_min'])
        
        raw_z = self.workspace_bounds['z_min'] + (hand_z + 0.1) * (self.workspace_bounds['z_max'] - self.workspace_bounds['z_min']) * 5
        filtered_z = self.z_filter.update(raw_z)
        
        cz = max(self.z_clamp_range[0], min(self.z_clamp_range[1], filtered_z))
        
        return wx, wy, cz

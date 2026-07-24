"""Clutch controller for disengaging and re-engaging hand tracking."""

from typing import Optional, Tuple
from .hand_to_ee import EETarget

class ClutchController:
    """Handles clutch logic for hand tracking."""
    
    def __init__(self):
        self._is_engaged = True
        self._clutched_hand_pos: Optional[Tuple[float, float, float]] = None
        self._clutched_ee_target: Optional[EETarget] = None
        self._hand_offset_x = 0.0
        self._hand_offset_y = 0.0
        self._hand_offset_z = 0.0

    def update(self, is_clutch_active: bool, current_ee_target: EETarget, current_hand_position: Tuple[float, float, float]) -> Optional[EETarget]:
        """
        Updates clutch state and computes the adjusted target if unclutched.
        """
        hx, hy, hz = current_hand_position
        
        if is_clutch_active:
            if self._is_engaged:
                self._is_engaged = False
                self._clutched_hand_pos = (hx, hy, hz)
                self._clutched_ee_target = current_ee_target
            return None
        else:
            if not self._is_engaged:
                self._is_engaged = True
                
                if self._clutched_hand_pos and self._clutched_ee_target:
                    raw_x, raw_y, raw_z = current_ee_target.x, current_ee_target.y, current_ee_target.z
                    self._hand_offset_x = raw_x - self._clutched_ee_target.x
                    self._hand_offset_y = raw_y - self._clutched_ee_target.y
                    self._hand_offset_z = raw_z - self._clutched_ee_target.z
            
            adjusted_target = EETarget(
                x=current_ee_target.x - self._hand_offset_x,
                y=current_ee_target.y - self._hand_offset_y,
                z=current_ee_target.z - self._hand_offset_z,
                wrist_roll=current_ee_target.wrist_roll,
                gripper=current_ee_target.gripper
            )
            return adjusted_target

    def is_engaged(self) -> bool:
        """Returns True if tracking is active, False if clutched/frozen."""
        return self._is_engaged

    def reset(self):
        """Resets the clutch offsets and state."""
        self._is_engaged = True
        self._clutched_hand_pos = None
        self._clutched_ee_target = None
        self._hand_offset_x = 0.0
        self._hand_offset_y = 0.0
        self._hand_offset_z = 0.0

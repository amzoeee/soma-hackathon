import logging
from typing import Dict

logger = logging.getLogger(__name__)

class SafetyController:
    """Safety controller that clamps per-step joint movement and detects stalls."""
    
    def __init__(self, max_relative_target: float = 5.0, stall_threshold: float = 3.0, stall_frames: int = 10):
        self.max_relative_target = max_relative_target
        self.stall_threshold = stall_threshold
        self.stall_frames = stall_frames
        self._stall_counters: Dict[str, int] = {}
        self._is_stalled: Dict[str, bool] = {}

    def clamp_action(self, action: Dict[str, float], current_observation: Dict[str, float]) -> Dict[str, float]:
        """Returns clamped action dict to protect against snap motions."""
        clamped_action = {}
        for joint, target_val in action.items():
            if joint in current_observation:
                current_val = current_observation[joint]
                lower_bound = current_val - self.max_relative_target
                upper_bound = current_val + self.max_relative_target
                clamped_action[joint] = max(lower_bound, min(upper_bound, target_val))
            else:
                clamped_action[joint] = target_val
        return clamped_action

    def check_stall(self, action: Dict[str, float], observation: Dict[str, float]) -> Dict[str, bool]:
        """Returns per-joint stall status."""
        for joint, commanded_val in action.items():
            actual_val = observation.get(joint, commanded_val)
            diff = abs(commanded_val - actual_val)
            
            if diff > self.stall_threshold:
                self._stall_counters[joint] = self._stall_counters.get(joint, 0) + 1
            else:
                self._stall_counters[joint] = 0
            
            self._is_stalled[joint] = self._stall_counters[joint] >= self.stall_frames

        return self._is_stalled.copy()

    def is_any_stall(self) -> bool:
        """Checks if any joint is currently stalled."""
        return any(self._is_stalled.values())

    def reset(self) -> None:
        """Resets stall counters and states."""
        self._stall_counters.clear()
        self._is_stalled.clear()

import cv2
import numpy as np
import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

@dataclass
class OverlayState:
    connected: bool
    clutch_active: bool
    joint_positions: Dict[str, float]
    joint_observations: Dict[str, float]
    ee_target: Optional[Tuple[float, float, float]]
    hand_detected: bool
    fps: float
    stall_warnings: Dict[str, bool]
    gesture: Optional[str]

class StatusOverlay:
    """Status overlay window that displays on the Xreal One Pro glasses."""

    def __init__(self, window_name: str = 'Teleop Status', width: int = 800, height: int = 400, display_index: Optional[int] = None):
        self.window_name = window_name
        self.width = width
        self.height = height
        self.display_index = display_index
        self._open = False
        
        # Initialize window
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.window_name, self.width, self.height)
        self._open = True

    def update(self, state: OverlayState) -> None:
        """Renders telemetry, joint states, and connection status."""
        if not self._open:
            return

        # Create black canvas
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        # Colors (BGR)
        GREEN = (0, 255, 0)
        YELLOW = (0, 255, 255)
        RED = (0, 0, 255)
        WHITE = (255, 255, 255)
        GRAY = (100, 100, 100)

        # 1. Connection Status
        conn_color = GREEN if state.connected else RED
        conn_text = "Connected" if state.connected else "Disconnected"
        cv2.putText(frame, f"Robot: {conn_text}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, conn_color, 2)

        # 2. FPS
        cv2.putText(frame, f"FPS: {state.fps:.1f}", (self.width - 150, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, WHITE, 2)

        # 3. Clutch and Hand Detection
        clutch_color = YELLOW if state.clutch_active else GRAY
        cv2.putText(frame, f"Clutch: {'ACTIVE' if state.clutch_active else 'INACTIVE'}", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, clutch_color, 2)
        
        hand_color = GREEN if state.hand_detected else GRAY
        cv2.putText(frame, f"Hand: {'DETECTED' if state.hand_detected else 'MISSING'}", (250, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, hand_color, 2)

        # 4. Gesture
        gesture_text = state.gesture if state.gesture else "None"
        cv2.putText(frame, f"Gesture: {gesture_text}", (480, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, WHITE, 2)

        # 5. Joint Status Bars
        y_offset = 120
        cv2.putText(frame, "Joint States (Cmd vs Act):", (20, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.6, WHITE, 1)
        y_offset += 30

        for joint, cmd_pos in state.joint_positions.items():
            act_pos = state.joint_observations.get(joint, 0.0)
            is_stalled = state.stall_warnings.get(joint, False)
            
            # Label
            text_color = RED if is_stalled else WHITE
            short_name = joint.replace(".pos", "")[:10]
            cv2.putText(frame, f"{short_name}", (20, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, text_color, 1)
            
            # Map values roughly [-180, 180] -> [0, 400] for display
            def map_angle(val):
                return int(np.clip((val + 180) / 360.0 * 400, 0, 400))
            
            cmd_x = map_angle(cmd_pos)
            act_x = map_angle(act_pos)

            # Draw track
            cv2.line(frame, (150, y_offset - 5), (550, y_offset - 5), GRAY, 2)
            # Actual Position (Cyan)
            cv2.circle(frame, (150 + act_x, y_offset - 5), 6, (255, 255, 0), -1)
            # Commanded Position (Magenta hollow)
            cv2.circle(frame, (150 + cmd_x, y_offset - 5), 8, (255, 0, 255), 2)
            
            if is_stalled:
                cv2.putText(frame, "STALL", (570, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, RED, 2)

            y_offset += 30

        # 6. End Effector Target
        if state.ee_target:
            ee_text = f"EE: [{state.ee_target[0]:.2f}, {state.ee_target[1]:.2f}, {state.ee_target[2]:.2f}]"
            cv2.putText(frame, ee_text, (20, y_offset + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, WHITE, 1)

        cv2.imshow(self.window_name, frame)
        cv2.waitKey(1)

    def show(self) -> None:
        """Ensures window is created and visible."""
        if not self._open:
            cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self.window_name, self.width, self.height)
            self._open = True

    def close(self) -> None:
        """Closes the overlay window."""
        if self._open:
            cv2.destroyWindow(self.window_name)
            self._open = False
            cv2.waitKey(1)

    def is_open(self) -> bool:
        return self._open

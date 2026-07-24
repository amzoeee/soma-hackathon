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
    camera_frame: Optional[np.ndarray] = None
    landmarks: Optional[list[tuple[float, float, float]]] = None


HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
    (5, 9), (9, 13), (13, 17),
]

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

        # Create black canvas. Camera occupies the left side; telemetry is a
        # compact panel on the right so the operator sees the actual Eye feed.
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        # Colors (BGR)
        GREEN = (0, 255, 0)
        YELLOW = (0, 255, 255)
        RED = (0, 0, 255)
        WHITE = (255, 255, 255)
        GRAY = (100, 100, 100)

        camera_w = int(self.width * 0.64)
        panel_x = camera_w + 16
        panel_w = self.width - panel_x - 10

        if state.camera_frame is not None:
            camera = state.camera_frame
            if camera.ndim == 2:
                camera = cv2.cvtColor(camera, cv2.COLOR_GRAY2BGR)
            else:
                camera = camera.copy()

            if state.landmarks:
                h, w = camera.shape[:2]
                pts = [
                    (int(lm[0] * w), int(lm[1] * h))
                    for lm in state.landmarks
                ]
                skeleton_color = RED if state.clutch_active else GREEN
                for a, b in HAND_CONNECTIONS:
                    cv2.line(camera, pts[a], pts[b], skeleton_color, 2, cv2.LINE_AA)
                for point in pts:
                    cv2.circle(camera, point, 3, (0, 128, 255), -1, cv2.LINE_AA)

            scale = min(camera_w / camera.shape[1], self.height / camera.shape[0])
            draw_w = max(1, int(camera.shape[1] * scale))
            draw_h = max(1, int(camera.shape[0] * scale))
            camera = cv2.resize(camera, (draw_w, draw_h), interpolation=cv2.INTER_NEAREST)
            x0 = (camera_w - draw_w) // 2
            y0 = (self.height - draw_h) // 2
            frame[y0:y0 + draw_h, x0:x0 + draw_w] = camera
        else:
            cv2.putText(
                frame, "NO EYE FRAME", (30, self.height // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, RED, 2,
            )

        cv2.line(frame, (camera_w, 0), (camera_w, self.height), GRAY, 1)

        # 1. Connection Status
        conn_color = GREEN if state.connected else RED
        conn_text = "Connected" if state.connected else "Disconnected"
        cv2.putText(frame, f"Robot: {conn_text}", (panel_x, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, conn_color, 2)

        # 2. FPS
        cv2.putText(frame, f"FPS: {state.fps:.1f}", (panel_x, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)

        # 3. Clutch and Hand Detection
        clutch_color = YELLOW if state.clutch_active else GRAY
        cv2.putText(frame, f"Clutch: {'ACTIVE' if state.clutch_active else 'INACTIVE'}", (panel_x, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.5, clutch_color, 2)
        
        hand_color = GREEN if state.hand_detected else GRAY
        cv2.putText(frame, f"Hand: {'DETECTED' if state.hand_detected else 'MISSING'}", (panel_x, 106), cv2.FONT_HERSHEY_SIMPLEX, 0.5, hand_color, 2)

        # 4. Gesture
        gesture_text = state.gesture if state.gesture else "None"
        cv2.putText(frame, f"Gesture: {gesture_text}", (panel_x, 132), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)

        # 5. Compact joint values
        y_offset = 164
        cv2.putText(frame, "Joints cmd / actual", (panel_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)
        y_offset += 24

        for joint, cmd_pos in state.joint_positions.items():
            act_pos = state.joint_observations.get(joint, 0.0)
            is_stalled = state.stall_warnings.get(joint, False)
            text_color = RED if is_stalled else WHITE
            short_name = joint.replace(".pos", "")[:9]
            suffix = " STALL" if is_stalled else ""
            cv2.putText(
                frame, f"{short_name:<9} {cmd_pos:6.1f}/{act_pos:6.1f}{suffix}",
                (panel_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.4, text_color, 1,
            )
            y_offset += 21

        # 6. End Effector Target
        if state.ee_target:
            ee_text = f"EE: [{state.ee_target[0]:.2f}, {state.ee_target[1]:.2f}, {state.ee_target[2]:.2f}]"
            cv2.putText(frame, ee_text, (panel_x, y_offset + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.42, WHITE, 1)

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

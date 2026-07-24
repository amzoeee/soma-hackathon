"""
Main entry point for the Xreal One Pro hand-tracking teleop pipeline.

Orchestrates: camera capture -> hand tracking -> gesture recognition ->
hand-to-EE mapping -> clutch logic -> IK solving -> safety clamping ->
robot command -> status overlay.
"""

import logging
import signal
import sys
import time

from config import Settings
from src.camera import XrealEyeCamera, WebcamFallback
from src.tracking import HandTracker
from src.mapping import HandToEEMapper, ClutchController, SignalFilter, AngleFilter, RateLimiter
from src.ik import IKSolver
from src.robot import ArmController, SafetyController
from src.overlay import StatusOverlay
from src.overlay.status_display import OverlayState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class TeleopPipeline:
    """Orchestrates the full hand-tracking teleop loop."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.running = False
        self._setup_signal_handlers()

        logger.info("Initializing teleop pipeline components...")
        self._init_camera()
        self._init_tracking()
        self._init_mapping()
        self._init_ik()
        self._init_robot()
        self._init_overlay()

    # ------------------------------------------------------------------ init
    def _setup_signal_handlers(self):
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        logger.info("Termination signal received, shutting down...")
        self.running = False

    def _init_camera(self):
        if self.settings.use_webcam_fallback:
            logger.info("Using webcam fallback")
            self.camera = WebcamFallback(
                device_index=self.settings.camera_device_index,
                resolution=self.settings.camera_resolution,
            )
        else:
            logger.info("Using Xreal One Pro Eye camera (TCP grayscale stream)")
            self.camera = XrealEyeCamera(
                host=self.settings.eye_host,
                port=self.settings.eye_port,
            )

    def _init_tracking(self):
        # One VIDEO-mode GestureRecognizer does landmarks + fist. Running
        # HandLandmarker and GestureRecognizer separately in IMAGE mode was
        # the main source of flickering skeletons on the Eye feed.
        self.hand_tracker = HandTracker(
            model_path=self.settings.gesture_model_path,
            num_hands=self.settings.num_hands,
            min_detection_confidence=self.settings.min_detection_confidence,
            min_tracking_confidence=self.settings.min_tracking_confidence,
            fist_score_threshold=self.settings.min_gesture_confidence,
        )
        self.gesture_recognizer = None  # clutch comes from hand_tracker.fist

    def _init_mapping(self):
        hand_box = {
            "x_min": self.settings.hand_box_x_min,
            "x_max": self.settings.hand_box_x_max,
            "y_min": self.settings.hand_box_y_min,
            "y_max": self.settings.hand_box_y_max,
        }
        workspace_bounds = {
            "x_min": self.settings.workspace_x_min,
            "x_max": self.settings.workspace_x_max,
            "y_min": self.settings.workspace_y_min,
            "y_max": self.settings.workspace_y_max,
            "z_min": self.settings.workspace_z_min,
            "z_max": self.settings.workspace_z_max,
        }
        self.mapper = HandToEEMapper(
            hand_box=hand_box,
            workspace_bounds=workspace_bounds,
            z_filter_alpha=self.settings.z_filter_alpha,
            z_clamp_range=self.settings.z_clamp_range,
        )
        self.clutch = ClutchController()
        self.pos_filter_x = SignalFilter(alpha=self.settings.position_filter_alpha)
        self.pos_filter_y = SignalFilter(alpha=self.settings.position_filter_alpha)
        self.pos_filter_z = SignalFilter(alpha=self.settings.z_filter_alpha)
        self.roll_filter = AngleFilter(
            alpha=self.settings.roll_filter_alpha,
            deadzone_deg=self.settings.roll_deadzone_deg,
        )
        self.roll_rate = RateLimiter(max_delta=self.settings.roll_max_delta_deg)
        self.gripper_filter = SignalFilter(alpha=self.settings.gripper_filter_alpha)

    def _init_ik(self):
        self.ik_solver = IKSolver(urdf_path=self.settings.urdf_path)

    def _init_robot(self):
        self.arm = ArmController(
            port=self.settings.robot_port,
            robot_id=self.settings.robot_id,
        )
        self.safety = SafetyController(
            max_relative_target=self.settings.max_relative_target,
            stall_threshold=self.settings.stall_threshold,
            stall_frames=self.settings.stall_frames,
        )

    def _init_overlay(self):
        self.overlay = StatusOverlay(
            width=self.settings.overlay_width,
            height=self.settings.overlay_height,
            display_index=self.settings.overlay_display_index,
        )

    # ------------------------------------------------------------------ run
    def run(self):
        """Main teleop loop."""
        # Connect hardware. The Eye stream is silent whenever Spatial Anchor
        # drops, so retry instead of killing the demo.
        for attempt in range(10):
            if self.camera.open():
                logger.info("Camera opened")
                break
            logger.warning(
                "Camera not streaming (attempt %d/10). For Eye: turn Spatial Anchor ON.",
                attempt + 1,
            )
            time.sleep(3.0)
        else:
            logger.error("Camera never started streaming -- aborting")
            return

        if not self.arm.connect():
            logger.warning("Failed to connect to robot -- running in dry-run mode")

        self.running = True
        frame_time = 1.0 / self.settings.target_fps
        missed_frames = 0
        RESET_AFTER_MISSES = 15  # ~0.5s sustained loss before filters reset
        logger.info("Teleop pipeline running (press ESC to quit)")

        try:
            while self.running:
                t0 = time.time()

                # -- a. Read camera frame
                ok, frame = self.camera.read()
                if not ok or frame is None:
                    logger.debug("Dropped frame")
                    time.sleep(0.001)
                    continue

                # -- b. Hand tracking (landmarks + fist in one VIDEO-mode pass)
                tracking_result = self.hand_tracker.process(frame)
                hand_detected = tracking_result is not None
                clutch_active = bool(tracking_result.fist) if tracking_result else False
                gesture_name = tracking_result.gesture if tracking_result else None

                # -- c. (gesture/clutch folded into tracking_result above)

                # -- d. If hand detected, map -> clutch -> IK -> send
                action = None
                ee_target = None
                stall_status = {}
                if hand_detected:
                    missed_frames = 0
                    ee_target = self.mapper.map(tracking_result)

                    # Smooth positions + roll/gripper (roll needs angle-aware EMA)
                    ee_target.x = self.pos_filter_x.update(ee_target.x)
                    ee_target.y = self.pos_filter_y.update(ee_target.y)
                    ee_target.z = self.pos_filter_z.update(ee_target.z)
                    ee_target.wrist_roll = self.roll_filter.update(ee_target.wrist_roll)
                    ee_target.gripper = self.gripper_filter.update(ee_target.gripper)

                    # Clutch logic
                    hand_pos = (
                        tracking_result.wrist_position[0],
                        tracking_result.wrist_position[1],
                        tracking_result.wrist_position[2],
                    )
                    adjusted = self.clutch.update(clutch_active, ee_target, hand_pos)

                    if adjusted is not None:
                        # Rate-limit wrist roll so even a filtered step can't snap
                        adjusted.wrist_roll = self.roll_rate.update(adjusted.wrist_roll)

                        # IK solve for the 4 arm joints
                        current_angles = self.arm.get_joint_angles() if self.arm.is_connected() else None
                        ik_result = self.ik_solver.solve(
                            target_position=(adjusted.x, adjusted.y, adjusted.z),
                            current_angles=current_angles,
                        )

                        # Assemble full action dict
                        action = {
                            "shoulder_pan.pos": ik_result.get("shoulder_pan", 0.0),
                            "shoulder_lift.pos": ik_result.get("shoulder_lift", 0.0),
                            "elbow_flex.pos": ik_result.get("elbow_flex", 0.0),
                            "wrist_flex.pos": ik_result.get("wrist_flex", 0.0),
                            "wrist_roll.pos": adjusted.wrist_roll,
                            "gripper.pos": adjusted.gripper,
                        }

                        # Safety clamp
                        observation = self.arm.get_observation() if self.arm.is_connected() else {}
                        if observation:
                            action = self.safety.clamp_action(action, observation)
                            stall_status = self.safety.check_stall(action, observation)
                        else:
                            stall_status = {}

                        # Send to robot
                        if self.arm.is_connected():
                            self.arm.send_action(action)
                else:
                    # Detection flickers on the grayscale feed; only reset the
                    # filters after a sustained loss so smoothing keeps history
                    # across single dropped frames.
                    missed_frames += 1
                    if missed_frames >= RESET_AFTER_MISSES:
                        self.roll_filter.reset()
                        self.roll_rate.reset()
                        self.gripper_filter.reset()

                # -- e. Get observation
                observation = self.arm.get_observation() if self.arm.is_connected() else {}

                # -- f. Update overlay
                elapsed = time.time() - t0
                fps = 1.0 / elapsed if elapsed > 0 else 0.0
                state = OverlayState(
                    connected=self.arm.is_connected(),
                    clutch_active=clutch_active,
                    joint_positions=action if action else {},
                    joint_observations=observation,
                    ee_target=(ee_target.x, ee_target.y, ee_target.z) if ee_target else None,
                    hand_detected=hand_detected,
                    fps=fps,
                    stall_warnings=stall_status if hand_detected and action else {},
                    gesture=gesture_name,
                )
                self.overlay.update(state)
                self.overlay.show()

                # -- g. Check for quit
                import cv2
                if cv2.waitKey(1) & 0xFF == 27:
                    logger.info("ESC pressed, exiting")
                    self.running = False

                # FPS regulation
                remaining = frame_time - (time.time() - t0)
                if remaining > 0:
                    time.sleep(remaining)

        except Exception:
            logger.exception("Pipeline error")
        finally:
            self.cleanup()

    def cleanup(self):
        """Release all resources."""
        logger.info("Cleaning up...")
        try:
            self.camera.close()
        except Exception:
            pass
        try:
            self.hand_tracker.close()
        except Exception:
            pass
        try:
            if self.gesture_recognizer is not None:
                self.gesture_recognizer.close()
        except Exception:
            pass
        try:
            self.arm.disconnect()
        except Exception:
            pass
        try:
            self.overlay.close()
        except Exception:
            pass
        import cv2
        cv2.destroyAllWindows()
        logger.info("Shutdown complete")


def main():
    settings = Settings.from_args()
    pipeline = TeleopPipeline(settings)
    pipeline.run()


if __name__ == "__main__":
    main()

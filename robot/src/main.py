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
from src.mapping import RelativeTeleop, RateLimiter
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
            min_hand_size=getattr(self.settings, "min_hand_size", 0.04),
            hold_frames=getattr(self.settings, "hold_frames", 24),
        )
        self.gesture_recognizer = None  # clutch comes from hand_tracker.fist

    def _init_mapping(self):
        # Relative teleop owns smoothing + fist clutch. Target starts at
        # (0,0,0); we add home_* and clamp into workspace before IK.
        self.teleop = RelativeTeleop(
            scale_x=self.settings.teleop_scale_x,
            scale_y=self.settings.teleop_scale_y,
            scale_z=self.settings.teleop_scale_z,
            roll_scale=self.settings.teleop_roll_scale,
            pos_filter_alpha=self.settings.position_filter_alpha,
            z_filter_alpha=self.settings.z_filter_alpha,
            xy_deadband=self.settings.xy_deadband,
            z_deadband=self.settings.z_deadband,
            roll_filter_alpha=self.settings.roll_filter_alpha,
            roll_deadzone_deg=self.settings.roll_deadzone_deg,
            gripper_filter_alpha=self.settings.gripper_filter_alpha,
        )
        self.roll_rate = RateLimiter(max_delta=self.settings.roll_max_delta_deg)
        self.workspace = {
            "x": (self.settings.workspace_x_min, self.settings.workspace_x_max),
            "y": (self.settings.workspace_y_min, self.settings.workspace_y_max),
            "z": (self.settings.workspace_z_min, self.settings.workspace_z_max),
        }

    def _init_ik(self):
        self.ik_solver = IKSolver(urdf_path=self.settings.urdf_path)

    def _init_robot(self):
        self.arm = ArmController(
            port=self.settings.robot_port,
            robot_id=self.settings.robot_id,
            max_relative_target=self.settings.max_relative_target,
            calibration_dir=getattr(self.settings, "calibration_dir", "calibration"),
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
            # Soft fallback: config home only when no arm is present.
            self.teleop.seed_pose(
                self.settings.home_x,
                self.settings.home_y,
                self.settings.home_z,
            )
        else:
            # Seed absolute teleop target from live FK + encoder roll/gripper
            # so the first command holds the physical pose (no snap to 0,0,0).
            try:
                angles = self.arm.get_joint_angles()
                obs = self.arm.get_observation() or {}
                hx, hy, hz = self.ik_solver.forward_kinematics(angles)
                wrist_roll = 90.0  # locked to horizontal
                gripper01 = float(obs.get("gripper.pos", 100.0)) / 100.0
                self.teleop.seed_pose(
                    hx, hy, hz, wrist_roll=wrist_roll, gripper=gripper01
                )
                # Don't yank the arm if current FK sits slightly outside the box.
                self._expand_workspace_to_include(hx, hy, hz)
                self.roll_rate.update(wrist_roll)  # prime rate limiter at current roll
                logger.info(
                    "Teleop seeded from arm FK: (%.3f, %.3f, %.3f) roll=%.1f grip=%.2f",
                    hx, hy, hz, wrist_roll, gripper01,
                )
            except Exception as e:
                logger.warning(
                    "Could not seed from arm FK (%s); using config home", e
                )
                self.teleop.seed_pose(
                    self.settings.home_x,
                    self.settings.home_y,
                    self.settings.home_z,
                )

        self.running = True
        frame_time = 1.0 / self.settings.target_fps
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
                gesture_name = tracking_result.gesture if tracking_result else None

                # -- c/d. Relative teleop already holds absolute EE meters
                # (seeded from FK). Clamp into workspace -> IK -> safety -> send
                target = self.teleop.update(tracking_result)
                clutch_active = target.clutched

                wx = self._clamp(target.x, *self.workspace["x"])
                wy = self._clamp(target.y, *self.workspace["y"])
                wz = self._clamp(target.z, *self.workspace["z"])
                ee_xyz = (wx, wy, wz)
                wrist_roll = 90.0  # locked to horizontal (90 deg)
                gripper = max(0.0, min(100.0, target.gripper * 100.0))

                current_angles = (
                    self.arm.get_joint_angles() if self.arm.is_connected() else None
                )
                ik_result = self.ik_solver.solve(
                    target_position=ee_xyz,
                    current_angles=current_angles,
                )
                action = {
                    "shoulder_pan.pos": ik_result.get("shoulder_pan", 0.0),
                    "shoulder_lift.pos": ik_result.get("shoulder_lift", 0.0),
                    "elbow_flex.pos": ik_result.get("elbow_flex", 0.0),
                    "wrist_flex.pos": ik_result.get("wrist_flex", 0.0),
                    "wrist_roll.pos": wrist_roll,
                    "gripper.pos": gripper,
                }

                observation = (
                    self.arm.get_observation() if self.arm.is_connected() else {}
                )
                stall_status = {}
                if observation:
                    action = self.safety.clamp_action(action, observation)
                    stall_status = self.safety.check_stall(action, observation)

                if self.arm.is_connected():
                    self.arm.send_action(action)

                # -- e. Fresh observation for overlay
                observation = (
                    self.arm.get_observation() if self.arm.is_connected() else {}
                )

                # -- f. Update overlay
                elapsed = time.time() - t0
                fps = 1.0 / elapsed if elapsed > 0 else 0.0
                state = OverlayState(
                    connected=self.arm.is_connected(),
                    clutch_active=clutch_active,
                    joint_positions=action,
                    joint_observations=observation,
                    ee_target=ee_xyz,
                    hand_detected=hand_detected,
                    fps=fps,
                    stall_warnings=stall_status,
                    gesture=gesture_name,
                    camera_frame=frame,
                    landmarks=tracking_result.landmarks if tracking_result else None,
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

    def _expand_workspace_to_include(self, x: float, y: float, z: float) -> None:
        """Grow workspace bounds so a live FK seed isn't immediately clamped."""
        margin = 0.01
        for axis, value in (("x", x), ("y", y), ("z", z)):
            lo, hi = self.workspace[axis]
            self.workspace[axis] = (min(lo, value - margin), max(hi, value + margin))

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

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

import argparse
import yaml
from dataclasses import dataclass, asdict
from typing import Optional, Tuple

@dataclass
class Settings:
    # Camera
    camera_device_index: int = 0
    camera_resolution: Tuple[int, int] = (640, 480)
    use_webcam_fallback: bool = False
    # Eye TCP stream (Aloim grayscale protocol — not a UVC device index)
    eye_host: str = '169.254.2.1'
    eye_port: int = 52997
    
    # Hand tracking — looser on Eye grayscale so we don't freeze mid-move
    hand_model_path: str = 'models/hand_landmarker.task'
    gesture_model_path: str = 'models/gesture_recognizer.task'
    num_hands: int = 1
    min_detection_confidence: float = 0.15
    min_tracking_confidence: float = 0.15
    min_gesture_confidence: float = 0.60
    hold_frames: int = 24
    min_hand_size: float = 0.04
    
    # Mapping - hand tracking box (normalized coords 0-1)
    hand_box_x_min: float = 0.2
    hand_box_x_max: float = 0.8
    hand_box_y_min: float = 0.2
    hand_box_y_max: float = 0.8
    
    # Mapping - robot workspace bounds (meters, SO-101 URDF frame:
    # +x forward/reach, +y left, +z up). Tuned from live FK of the arm.
    workspace_x_min: float = 0.12
    workspace_x_max: float = 0.30
    workspace_y_min: float = -0.15
    workspace_y_max: float = 0.15
    workspace_z_min: float = 0.05
    workspace_z_max: float = 0.30

    # Relative teleop: (0,0,0) + home offset = reachable start pose in meters.
    # Scales convert normalized hand deltas → meters. Tune live if reach feels off.
    home_x: float = 0.20
    home_y: float = 0.0
    home_z: float = 0.15
    teleop_scale_x: float = 0.5   # depth (hand size) → reach (x)
    teleop_scale_y: float = 0.6   # image-x → lateral (y)
    teleop_scale_z: float = 0.5   # image-y → up/down (z)
    teleop_roll_scale: float = 0.0  # Wrist roll locked to horizontal (0.0 deg)
    
    # Filters
    z_filter_alpha: float = 0.08
    z_clamp_range: Tuple[float, float] = (0.05, 0.30)
    position_filter_alpha: float = 0.15
    deadzone_threshold: float = 0.005
    xy_deadband: float = 0.006
    z_deadband: float = 0.010
    # Wrist roll is the noisiest channel (landmark geometry on grayscale).
    # Low alpha + deadzone = arm doesn't twitch from jitter; intentional
    # twists still come through after a beat.
    roll_filter_alpha: float = 0.12
    roll_deadzone_deg: float = 4.0
    roll_max_delta_deg: float = 3.0   # per-frame rate limit on wrist_roll.pos
    gripper_filter_alpha: float = 0.25
    
    # Robot (Windows: COMx, Linux: /dev/ttyACM0)
    # Device Manager currently shows the Feetech bus on COM7.
    robot_port: str = 'COM7'
    robot_id: str = 'follower'
    urdf_path: str = 'config/so101.urdf'
    # Local calibration JSON dir (file must be named {robot_id}.json)
    calibration_dir: str = 'calibration'
    
    # Safety
    max_relative_target: float = 5.0
    stall_threshold: float = 3.0
    stall_frames: int = 10
    
    # Overlay
    overlay_width: int = 1100
    overlay_height: int = 600
    overlay_display_index: Optional[int] = None
    
    # Loop
    target_fps: int = 30

    @classmethod
    def from_yaml(cls, path: str) -> 'Settings':
        """Load settings from a YAML file."""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        if data:
            if 'camera_resolution' in data and isinstance(data['camera_resolution'], list):
                data['camera_resolution'] = tuple(data['camera_resolution'])
            if 'z_clamp_range' in data and isinstance(data['z_clamp_range'], list):
                data['z_clamp_range'] = tuple(data['z_clamp_range'])
            return cls(**data)
        return cls()

    def to_yaml(self, path: str) -> None:
        """Save settings to a YAML file."""
        with open(path, 'w') as f:
            yaml.safe_dump(asdict(self), f)

    @classmethod
    def from_args(cls) -> 'Settings':
        """Parse command-line arguments to override settings."""
        parser = argparse.ArgumentParser(description="Teleop Pipeline Settings")
        parser.add_argument('--config', type=str, help='Path to YAML config file')
        parser.add_argument('--port', type=str, help='Robot port (e.g. /dev/ttyACM0)')
        parser.add_argument('--use-webcam', action='store_true', help='Use webcam fallback')
        parser.add_argument('--fps', type=int, help='Target FPS')
        parser.add_argument('--camera-index', type=int, help='Camera device index')
        
        args, unknown = parser.parse_known_args()
        
        settings = cls()
        if args.config:
            settings = cls.from_yaml(args.config)
            
        if args.port:
            settings.robot_port = args.port
        if args.use_webcam:
            settings.use_webcam_fallback = True
        if args.fps:
            settings.target_fps = args.fps
        if args.camera_index is not None:
            settings.camera_device_index = args.camera_index
            
        return settings

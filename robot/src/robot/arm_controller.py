"""LeRobot SO-101 follower arm controller.

LeRobot >=0.6 moved SO-101 to ``lerobot.robots.so_follower`` (older builds
used ``lerobot.robots.so101_follower``). Actions are dicts of ``'<joint>.pos'``
in DEGREES when ``use_degrees=True``.
"""

from __future__ import annotations

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

try:
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
except ImportError:
    try:
        from lerobot.robots.so101_follower import SO101Follower, SO101FollowerConfig
    except ImportError:
        logger.warning(
            "Could not import SO101Follower from lerobot. Running in mock mode."
        )
        SO101FollowerConfig = None
        SO101Follower = None


class ArmController:
    """Controls the LeRobot SO-101 follower arm via the lerobot SDK."""

    JOINT_KEYS = [
        "shoulder_pan.pos",
        "shoulder_lift.pos",
        "elbow_flex.pos",
        "wrist_flex.pos",
        "wrist_roll.pos",
        "gripper.pos",
    ]

    def __init__(
        self,
        port: str = "COM7",
        robot_id: str = "follower",
        max_relative_target: float = 5.0,
        max_delta_deg_per_tick: float = 3.0,
        calibration_dir: str | None = "calibration",
    ):
        self.port = port
        self.robot_id = robot_id
        self.max_relative_target = max_relative_target
        self.max_delta = max_delta_deg_per_tick
        self.calibration_dir = calibration_dir
        self._robot = None
        self._connected = False
        self._mock = SO101Follower is None
        self._mock_state: Dict[str, float] = {k: 0.0 for k in self.JOINT_KEYS}
        self._mock_state["gripper.pos"] = 100.0

    def connect(self) -> bool:
        if self._mock:
            logger.warning("Mock connection established (lerobot not installed).")
            self._connected = True
            return True
        try:
            from pathlib import Path

            kwargs = {
                "port": self.port,
                "id": self.robot_id,
                "use_degrees": True,
                "max_relative_target": self.max_relative_target,
            }
            if self.calibration_dir:
                cal_dir = Path(self.calibration_dir)
                cal_file = cal_dir / f"{self.robot_id}.json"
                if cal_file.is_file():
                    kwargs["calibration_dir"] = cal_dir
                else:
                    logger.warning(
                        "No calibration at %s — lerobot may prompt to calibrate",
                        cal_file,
                    )

            config = SO101FollowerConfig(**kwargs)
            self._robot = SO101Follower(config)
            # Prefer existing calibration; don't block on interactive recalibrate.
            self._robot.connect(calibrate=False)
            if hasattr(self._robot, "bus") and hasattr(self._robot.bus, "enable_torque"):
                self._robot.bus.enable_torque()
            self._connected = True
            logger.info("Connected to SO-101 on %s", self.port)
            return True
        except Exception as e:
            logger.error("Failed to connect to SO101 arm on %s: %s", self.port, e)
            self._connected = False
            return False

    def send_action(self, action: Dict[str, float]) -> bool:
        if not self._connected:
            return False

        current = self.get_observation()
        limited: Dict[str, float] = {}
        for key, goal in action.items():
            g = float(goal)
            if key == "gripper.pos":
                limited[key] = max(0.0, min(100.0, g))
            else:
                c = float(current.get(key, g))
                delta = max(-self.max_delta, min(self.max_delta, g - c))
                limited[key] = c + delta

        if self._mock:
            self._mock_state.update(limited)
            return True

        try:
            self._robot.send_action(limited)
            return True
        except Exception as e:
            logger.error("Failed to send action: %s", e)
            return False

    def get_observation(self) -> Dict[str, float]:
        if self._mock or self._robot is None:
            return dict(self._mock_state)
        try:
            obs = self._robot.get_observation()
            return {k: float(obs[k]) for k in self.JOINT_KEYS if k in obs}
        except Exception as e:
            logger.error("Failed to get observation: %s", e)
            return {}

    def get_joint_angles(self) -> List[float]:
        obs = self.get_observation()
        return [
            obs.get("shoulder_pan.pos", 0.0),
            obs.get("shoulder_lift.pos", 0.0),
            obs.get("elbow_flex.pos", 0.0),
            obs.get("wrist_flex.pos", 0.0),
        ]

    def disconnect(self) -> None:
        if self._robot is not None:
            try:
                self._robot.disconnect()
            except Exception as e:
                logger.error("Error disconnecting: %s", e)
            self._robot = None
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

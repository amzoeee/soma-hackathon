import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

# TODO: Adjust these imports based on the exact lerobot SDK version/API
try:
    from lerobot.common.robots.so101_follower.config_so101_follower import So101FollowerConfig
    from lerobot.common.robots.so101_follower.so101_follower import SO101Follower
except ImportError:
    logger.warning("Could not import SO101Follower from lerobot. Running in mock mode.")
    So101FollowerConfig = None
    SO101Follower = None

class ArmController:
    """Controls the LeRobot SO-101 follower arm via lerobot SDK."""

    JOINT_KEYS = [
        "shoulder_pan.pos",
        "shoulder_lift.pos",
        "elbow_flex.pos",
        "wrist_flex.pos",
        "wrist_roll.pos",
        "gripper.pos"
    ]

    def __init__(self, port: str = '/dev/ttyACM0', robot_id: str = 'follower'):
        self.port = port
        self.robot_id = robot_id
        self._robot = None
        self._connected = False

    def connect(self) -> bool:
        """Connects to the robot arm."""
        try:
            if SO101Follower is not None and So101FollowerConfig is not None:
                config = So101FollowerConfig(port=self.port)
                self._robot = SO101Follower(config=config)
                self._robot.connect()
            else:
                logger.warning("Mock connection established.")
            self._connected = True
            return True
        except Exception as e:
            logger.error("Failed to connect to SO101 arm: %s", e)
            self._connected = False
            return False

    def send_action(self, action: Dict[str, float]) -> bool:
        """Sends the 6-key action dict to the robot."""
        if not self._connected:
            return False
            
        try:
            # TODO: Adapt action dict to exact lerobot send format.
            # Usually robots accept a tensor or a list of values in a specific order.
            if self._robot:
                # Example conversion if SDK expects a dict or specific list
                # values = [action[k] for k in self.JOINT_KEYS]
                # self._robot.write(values)
                pass
            return True
        except Exception as e:
            logger.error("Failed to send action: %s", e)
            return False

    def get_observation(self) -> Dict[str, float]:
        """Returns current servo encoder readings."""
        obs = {k: 0.0 for k in self.JOINT_KEYS}
        if not self._connected:
            return obs
            
        try:
            # TODO: Retrieve from actual robot SDK
            if self._robot:
                # state = self._robot.read()
                # for i, k in enumerate(self.JOINT_KEYS):
                #     obs[k] = state[i]
                pass
        except Exception as e:
            logger.error("Failed to get observation: %s", e)
        
        return obs

    def get_joint_angles(self) -> List[float]:
        """Returns just the 4 IK-relevant joint angles."""
        obs = self.get_observation()
        return [
            obs.get("shoulder_pan.pos", 0.0),
            obs.get("shoulder_lift.pos", 0.0),
            obs.get("elbow_flex.pos", 0.0),
            obs.get("wrist_flex.pos", 0.0)
        ]

    def disconnect(self) -> None:
        """Disconnects from the robot arm."""
        if self._robot:
            try:
                self._robot.disconnect()
            except Exception as e:
                logger.error("Error disconnecting: %s", e)
        self._connected = False
        
    def is_connected(self) -> bool:
        return self._connected

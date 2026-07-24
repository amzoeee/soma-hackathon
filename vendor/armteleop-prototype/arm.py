"""SO-101 arm wrapper (LeRobot) with velocity limits + sim mode."""

from __future__ import annotations

from typing import Any


class ArmController:
    """
    Talks to SO-101 via lerobot SO101Follower.
    Set arm.sim: true in config to develop without hardware.
    """

    JOINTS = [
        "shoulder_pan",
        "shoulder_lift",
        "elbow_flex",
        "wrist_flex",
        "wrist_roll",
        "gripper",
    ]

    def __init__(self, config: dict[str, Any]):
        arm = config.get("arm", config)
        self.port = arm.get("port", "TBD")
        self.sim = bool(arm.get("sim", False)) or self.port in (None, "", "TBD")
        self.use_degrees = bool(arm.get("use_degrees", True))
        self.max_delta = float(arm.get("max_delta_deg_per_tick", 3.0))
        self.max_relative = arm.get("max_relative_target", 5.0)
        self.home = dict(arm.get("home_pose_deg", {}))
        self._robot = None
        self._last: dict[str, float] = dict(self.home) if self.home else {j: 0.0 for j in self.JOINTS}
        if "gripper" not in self._last:
            self._last["gripper"] = 100.0
        self._last_cmd: dict[str, float] = {}

    def connect(self) -> None:
        if self.sim:
            print(f"[arm] SIM mode (port={self.port!r}) — no serial")
            return
        from lerobot.robots.so101_follower import SO101Follower, SO101FollowerConfig

        cfg = SO101FollowerConfig(
            port=self.port,
            use_degrees=self.use_degrees,
            max_relative_target=self.max_relative,
        )
        self._robot = SO101Follower(cfg)
        self._robot.connect(calibrate=True)
        self._last = self.read_positions()
        print(f"[arm] connected on {self.port}")

    def read_positions(self) -> dict[str, float]:
        if self.sim or self._robot is None:
            return dict(self._last)
        obs = self._robot.get_observation()
        return {j: float(obs[f"{j}.pos"]) for j in self.JOINTS}

    def read_load(self) -> dict[str, float]:
        if self.sim or self._robot is None:
            return {j: 0.0 for j in self.JOINTS}
        return {k: float(v) for k, v in self._robot.bus.sync_read("Present_Load").items()}

    def write_positions(self, goals: dict[str, float]) -> dict[str, float]:
        current = self.read_positions()
        limited: dict[str, float] = {}
        for j in self.JOINTS:
            if j not in goals:
                continue
            g = float(goals[j])
            c = float(current.get(j, g))
            if j != "gripper":
                delta = max(-self.max_delta, min(self.max_delta, g - c))
                g = c + delta
            else:
                g = max(0.0, min(100.0, g))
            limited[j] = g

        self._last.update(limited)
        self._last_cmd.update(limited)
        if self.sim or self._robot is None:
            return dict(limited)

        action = {f"{j}.pos": limited[j] for j in limited}
        return self._robot.send_action(action)

    def check_stall(self, threshold_deg: float = 10.0) -> dict[str, float]:
        """Commanded-vs-actual divergence (from encoders, not commanded fiction).

        Returns joints whose divergence exceeds the threshold — a stall means
        the arm is pushing against something it can't move through.
        """
        if self.sim or self._robot is None or not self._last_cmd:
            return {}
        actual = self.read_positions()
        stalled = {}
        for j, cmd in self._last_cmd.items():
            if j == "gripper":
                continue
            div = cmd - actual.get(j, cmd)
            if abs(div) > threshold_deg:
                stalled[j] = div
        return stalled

    def home_arm(self) -> None:
        if self.home:
            self.write_positions(self.home)

    def set_torque(self, enable: bool) -> None:
        if self.sim or self._robot is None:
            print(f"[arm] SIM torque={'ON' if enable else 'OFF'}")
            return
        if enable:
            self._robot.bus.enable_torque()
        else:
            self._robot.bus.disable_torque()

    def disconnect(self) -> None:
        if self._robot is not None:
            self._robot.disconnect()
            self._robot = None

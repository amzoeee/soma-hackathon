"""SO-101 driver for the Linq agent.

Motion follows ``robot/scripts/move_to_cartesian_target.py``, which is the
reference for how this arm is driven:

  1. solve IK for an **absolute** (x, y, z) target in meters,
  2. build a **full** joint action in LeRobot ``.pos`` units (degrees for the
     five arm joints, 0-100 for the gripper),
  3. **ramp** to it over N interpolated steps instead of jumping.

Transport is LeRobot's ``SO101Follower`` whenever ``lerobot`` is importable —
byte for byte the same path as the script. When it is not (the agent venv is
Python 3.14 and cannot get lerobot today), we fall back to the Feetech SDK and
reproduce LeRobot's exact normalization, so both transports speak the same
units and the motion logic above stays identical.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("demo.hardware.so101")

# STS3215 control table (protocol 0) — Feetech fallback transport only.
_TORQUE_ENABLE = 40
_ACCELERATION = 41
_GOAL_POSITION = 42
_GOAL_SPEED = 46
_PRESENT_POSITION = 56

# LeRobot normalizes against resolution - 1; match it exactly.
MOTOR_RESOLUTION = 4096
MAX_RES = MOTOR_RESOLUTION - 1

DEFAULT_BAUD = 1_000_000
DEFAULT_ACCEL = 60
DEFAULT_GOAL_SPEED = 450

DEFAULT_JOINT_IDS = {
    "shoulder_pan": 1,
    "shoulder_lift": 2,
    "elbow_flex": 3,
    "wrist_flex": 4,
    "wrist_roll": 5,
    "gripper": 6,
}

# Joints the IK chain solves for, in chain order.
IK_JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex")
# LeRobot gives the gripper RANGE_0_100; every other joint is DEGREES.
GRIPPER = "gripper"

MAX_CARTESIAN_STEP_M = 0.06

# The so101.urdf chain is right-handed with +x forward, +y left, +z up.
# Measured off the loaded chain (all joints at 0 deg): the tool sits at
# (0.391, 0.000, 0.227) — fully extended along +x — and shoulder_pan swings
# the tool along y, not x. The script's docstring says x is left/right and y
# is reach; that is backwards, and following it makes "forward" travel
# sideways. Directions below use the measured frame.
WORKSPACE = {
    "x": (0.05, 0.33),   # forward reach
    "y": (-0.20, 0.20),  # lateral, + is left
    "z": (0.02, 0.35),   # height
}

# Ramp shape. The script uses 10s/100 steps for a full-reach absolute move;
# agent moves are <=6cm nudges, so the same 0.05s cadence over a shorter ramp.
MOVE_DURATION_S = 2.0
MOVE_STEPS = 40
JOINT_DURATION_S = 1.0
JOINT_STEPS = 20

# How far the solved pose may sit from the requested target before we call it
# unreachable. IKSolver silently returns its *previous* solution on a miss, so
# we re-check with FK and fail loud instead of reporting a phantom success.
IK_TOLERANCE_M = 0.02

# Smallest change we count as "the arm actually moved" (degrees / gripper %).
MOVED_EPSILON = 0.5


@dataclass(frozen=True)
class JointCalib:
    """One motor's calibration, in LeRobot's ``MotorCalibration`` shape."""

    name: str
    motor_id: int
    drive_mode: int
    homing_offset: int
    range_min: int
    range_max: int

    @property
    def mid(self) -> float:
        return (self.range_min + self.range_max) / 2.0

    def clamp_ticks(self, ticks: int) -> int:
        lo, hi = sorted((self.range_min, self.range_max))
        return max(lo, min(hi, int(ticks)))

    # --- LeRobot normalization (lerobot/motors/motors_bus.py) -------------
    # DEGREES:      pos = (ticks - mid) * 360 / MAX_RES        (drive_mode unused)
    # RANGE_0_100:  pos = (ticks - min) / (max - min) * 100    (inverted if drive_mode)

    def to_pos(self, ticks: int) -> float:
        if self.name == GRIPPER:
            span = self.range_max - self.range_min
            norm = (self.clamp_ticks(ticks) - self.range_min) / span * 100.0
            return 100.0 - norm if self.drive_mode else norm
        return (float(ticks) - self.mid) * 360.0 / MAX_RES

    def from_pos(self, pos: float) -> int:
        if self.name == GRIPPER:
            span = self.range_max - self.range_min
            value = 100.0 - pos if self.drive_mode else pos
            value = max(0.0, min(100.0, value))
            return self.clamp_ticks(int(value / 100.0 * span + self.range_min))
        return self.clamp_ticks(int(pos * MAX_RES / 360.0 + self.mid))

    @property
    def pos_limits(self) -> tuple[float, float]:
        """Reachable range of this joint in the same units as ``to_pos``."""
        if self.name == GRIPPER:
            return (0.0, 100.0)
        lo = self.to_pos(min(self.range_min, self.range_max))
        hi = self.to_pos(max(self.range_min, self.range_max))
        return (lo, hi)

    def clamp_pos(self, pos: float) -> float:
        lo, hi = self.pos_limits
        return max(lo, min(hi, float(pos)))


def _repo_root() -> Path:
    # agent/src/demo/hardware/so101.py → repo root
    return Path(__file__).resolve().parents[4]


def default_calibration_path() -> Path:
    return _repo_root() / "robot" / "calibration" / "my_follower.json"


def default_urdf_path() -> Path:
    return _repo_root() / "robot" / "config" / "so101.urdf"


def load_calibration(path: str | Path | None = None) -> dict[str, JointCalib]:
    cal_path = Path(path) if path else default_calibration_path()
    if not cal_path.is_file():
        raise FileNotFoundError(f"Calibration file not found: {cal_path}")

    raw = json.loads(cal_path.read_text())
    out: dict[str, JointCalib] = {}
    for name, spec in raw.items():
        out[name] = JointCalib(
            name=name,
            motor_id=int(spec.get("id", DEFAULT_JOINT_IDS.get(name, 0))),
            drive_mode=int(spec.get("drive_mode", 0)),
            homing_offset=int(spec.get("homing_offset", 0)),
            range_min=int(spec.get("range_min", 0)),
            range_max=int(spec.get("range_max", MAX_RES)),
        )
    missing = [n for n in DEFAULT_JOINT_IDS if n not in out]
    if missing:
        raise ValueError(f"Calibration missing joints: {missing}")
    logger.info("Loaded SO-101 calibration from %s (%d joints)", cal_path, len(out))
    return out


# Feetech encodes Present_Position / Goal_Position sign-magnitude on bit 15
# (lerobot/motors/feetech/tables.py: STS_SMS_SERIES_ENCODINGS_TABLE).
def _decode_sign_magnitude(value: int) -> int:
    return -(value & 0x7FFF) if value & 0x8000 else value


def _encode_sign_magnitude(value: int) -> int:
    return (-value & 0x7FFF) | 0x8000 if value < 0 else value & 0x7FFF


def _load_ik_solver(urdf_path: Path):
    """Import the repo IK solver (ikpy) with a stable sys.path."""
    import sys

    robot_src = str(_repo_root() / "robot" / "src")
    if robot_src not in sys.path:
        sys.path.insert(0, robot_src)
    from ik.solver import IKSolver  # type: ignore

    return IKSolver(str(urdf_path))


# ---------------------------------------------------------------------------
# Transports. Both expose read_pos() / write_pos() in LeRobot `.pos` units.
# ---------------------------------------------------------------------------


class _LeRobotTransport:
    """The script's transport: ``SO101Follower`` with ``use_degrees=True``."""

    name = "lerobot"

    def __init__(self, port: str, calibration_path: Path, baudrate: int) -> None:
        self.port = port
        self.calibration_path = calibration_path
        self.baudrate = baudrate
        self._robot = None

    @staticmethod
    def available() -> bool:
        import importlib.util

        return importlib.util.find_spec("lerobot") is not None

    def connect(self) -> None:
        try:
            from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
        except ImportError:  # lerobot < 0.6 layout
            from lerobot.robots.so101_follower import (  # type: ignore
                SO101Follower,
                SO101FollowerConfig,
            )

        config = SO101FollowerConfig(
            port=self.port,
            id=self.calibration_path.stem,
            calibration_dir=self.calibration_path.parent,
            use_degrees=True,
        )
        robot = SO101Follower(config)
        if not robot.calibration:
            raise RuntimeError(
                f"LeRobot found no calibration at {robot.calibration_fpath}; "
                "run robot/scripts/calibrate.sh or point ROBOT_CALIBRATION_PATH "
                "at the follower json."
            )

        # calibrate=False: SO101Follower.calibrate() prompts on stdin, which
        # would hang the webhook server. We push the file's values instead.
        robot.connect(calibrate=False)
        if not robot.bus.is_calibrated:
            logger.info("Motors disagree with %s; writing calibration", self.calibration_path)
            robot.bus.write_calibration(robot.calibration)

        # Explicitly enable torque, as the script does.
        robot.bus.enable_torque()
        self._robot = robot

    def read_pos(self) -> dict[str, float]:
        obs = self._robot.get_observation()  # type: ignore[union-attr]
        return {
            key.removesuffix(".pos"): float(value)
            for key, value in obs.items()
            if key.endswith(".pos")
        }

    def write_pos(self, action: dict[str, float]) -> None:
        self._robot.send_action({f"{k}.pos": float(v) for k, v in action.items()})  # type: ignore[union-attr]

    def disconnect(self) -> None:
        if self._robot is not None:
            try:
                self._robot.disconnect()
            finally:
                self._robot = None


class _FeetechTransport:
    """Fallback transport: raw scservo SDK, LeRobot's units."""

    name = "feetech"

    def __init__(
        self,
        port: str,
        calibration: dict[str, JointCalib],
        baudrate: int,
        accel: int,
        goal_speed: int,
    ) -> None:
        self.port_name = port
        self.calibration = calibration
        self.baudrate = baudrate
        self.accel = accel
        self.goal_speed = goal_speed
        self._sdk = None
        self._port = None
        self._packet = None

    def connect(self) -> None:
        try:
            import scservo_sdk as sdk
        except ImportError as exc:
            raise RuntimeError(
                "feetech-servo-sdk is required (pip install feetech-servo-sdk pyserial)"
            ) from exc

        port = sdk.PortHandler(self.port_name)
        packet = sdk.PacketHandler(0)
        if not port.openPort():
            raise RuntimeError(f"Failed to open robot port {self.port_name}")
        if not port.setBaudRate(self.baudrate):
            port.closePort()
            raise RuntimeError(f"Failed to set baud on {self.port_name}")

        pan_id = self.calibration["shoulder_pan"].motor_id
        _, result, _ = packet.ping(port, pan_id)
        if result != sdk.COMM_SUCCESS:
            port.closePort()
            raise RuntimeError(f"No SO-101 response on {self.port_name}")

        self._sdk = sdk
        self._port = port
        self._packet = packet

        # Torque + motion profile once at connect; the ramp then only writes
        # Goal_Position, which keeps each interpolation step cheap.
        for cal in self.calibration.values():
            self._write1(cal.motor_id, _TORQUE_ENABLE, 1)
            self._write1(cal.motor_id, _ACCELERATION, self.accel)
            self._write2(cal.motor_id, _GOAL_SPEED, self.goal_speed)

    def read_pos(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for name, cal in self.calibration.items():
            out[name] = cal.to_pos(self._read2(cal.motor_id, _PRESENT_POSITION))
        return out

    def write_pos(self, action: dict[str, float]) -> None:
        for name, value in action.items():
            cal = self.calibration.get(name)
            if cal is None:
                continue
            self._write2(
                cal.motor_id,
                _GOAL_POSITION,
                _encode_sign_magnitude(cal.from_pos(float(value))),
            )

    def disconnect(self) -> None:
        try:
            for cal in self.calibration.values():
                try:
                    self._write1(cal.motor_id, _TORQUE_ENABLE, 0)
                except Exception:  # noqa: BLE001
                    pass
        finally:
            if self._port is not None:
                self._port.closePort()
            self._sdk = self._port = self._packet = None

    # --- register helpers -------------------------------------------------

    def _read2(self, motor_id: int, address: int) -> int:
        last: Exception | None = None
        for _ in range(4):
            val, result, error = self._packet.read2ByteTxRx(self._port, motor_id, address)
            if result == self._sdk.COMM_SUCCESS:
                if error:
                    logger.warning("servo id=%s addr=%s err=%s", motor_id, address, error)
                return _decode_sign_magnitude(val)
            last = RuntimeError(f"read2 id={motor_id} addr={address} result={result}")
            time.sleep(0.03)
        raise last  # type: ignore[misc]

    def _write1(self, motor_id: int, address: int, value: int) -> None:
        result, error = self._packet.write1ByteTxRx(self._port, motor_id, address, value)
        if result != self._sdk.COMM_SUCCESS:
            raise RuntimeError(f"write1 id={motor_id} addr={address} result={result}")
        if error:
            logger.warning("servo id=%s addr=%s err=%s", motor_id, address, error)

    def _write2(self, motor_id: int, address: int, value: int) -> None:
        result, error = self._packet.write2ByteTxRx(self._port, motor_id, address, value)
        if result != self._sdk.COMM_SUCCESS:
            raise RuntimeError(f"write2 id={motor_id} addr={address} result={result}")
        if error:
            logger.warning("servo id=%s addr=%s err=%s", motor_id, address, error)


# ---------------------------------------------------------------------------
# The arm
# ---------------------------------------------------------------------------


class SO101Arm:
    def __init__(
        self,
        port: str,
        *,
        calibration: dict[str, JointCalib],
        calibration_path: str | Path | None = None,
        urdf_path: str | Path | None = None,
        baudrate: int = DEFAULT_BAUD,
        accel: int = DEFAULT_ACCEL,
        goal_speed: int = DEFAULT_GOAL_SPEED,
    ) -> None:
        self.port_name = port
        self.calibration = calibration
        self.calibration_path = (
            Path(calibration_path) if calibration_path else default_calibration_path()
        )
        self.urdf_path = Path(urdf_path) if urdf_path else default_urdf_path()
        self.baudrate = baudrate
        self.accel = accel
        self.goal_speed = goal_speed
        self._lock = threading.RLock()
        self._transport = None
        self._connected = False
        self._ik = None

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        with self._lock:
            if self._connected:
                return

            if _LeRobotTransport.available():
                transport: Any = _LeRobotTransport(
                    self.port_name, self.calibration_path, self.baudrate
                )
            else:
                logger.warning(
                    "lerobot not importable; using the Feetech SDK transport "
                    "(same units, same motion path)"
                )
                transport = _FeetechTransport(
                    self.port_name,
                    self.calibration,
                    self.baudrate,
                    self.accel,
                    self.goal_speed,
                )

            transport.connect()
            self._transport = transport
            self._connected = True

            # A fresh solver per connection: IKSolver carries the last solution
            # in self._q, and a stale seed from an old session skews the first
            # solve of this one.
            try:
                self._ik = _load_ik_solver(self.urdf_path)
                logger.info("IK solver ready (%s)", self.urdf_path)
            except Exception:  # noqa: BLE001
                self._ik = None
                logger.exception("IK unavailable; cartesian moves will fail closed")

            logger.info(
                "Connected SO-101 on %s via %s (joints=%s)",
                self.port_name,
                transport.name,
                list(self.calibration),
            )

    def disconnect(self) -> None:
        with self._lock:
            if not self._connected:
                return
            try:
                self._transport.disconnect()
            finally:
                self._transport = None
                self._connected = False
                logger.info("Disconnected SO-101 on %s", self.port_name)

    def _ensure(self) -> None:
        if not self._connected:
            self.connect()

    # --- state ------------------------------------------------------------

    def read_pos(self) -> dict[str, float]:
        """Every joint in LeRobot ``.pos`` units (degrees; gripper 0-100)."""
        with self._lock:
            self._ensure()
            return self._transport.read_pos()

    def get_ik_joint_degrees(self) -> list[float]:
        pos = self.read_pos()
        return [pos[name] for name in IK_JOINTS]

    def forward_kinematics(self) -> tuple[float, float, float]:
        with self._lock:
            self._ensure()
            if self._ik is None:
                raise RuntimeError("IK solver is not available")
            return self._ik.forward_kinematics(self.get_ik_joint_degrees())

    # --- motion -----------------------------------------------------------

    def _ramp(
        self,
        start: dict[str, float],
        goal: dict[str, float],
        duration: float,
        steps: int,
    ) -> dict[str, float]:
        """Interpolate from ``start`` to ``goal``, exactly as the script does."""
        sleep_time = duration / steps
        for i in range(1, steps + 1):
            alpha = i / steps
            self._transport.write_pos(
                {
                    name: start[name] + alpha * (goal[name] - start[name])
                    for name in goal
                }
            )
            time.sleep(sleep_time)
        return self._transport.read_pos()

    def move_to_xyz(
        self,
        target: tuple[float, float, float],
        *,
        duration: float = MOVE_DURATION_S,
        steps: int = MOVE_STEPS,
    ) -> dict[str, Any]:
        """Move the end effector to an absolute (x, y, z) in meters."""
        with self._lock:
            self._ensure()
            if self._ik is None:
                raise RuntimeError("IK solver is not available")

            start = self._transport.read_pos()
            seed = [start[name] for name in IK_JOINTS]
            solution = self._ik.solve(tuple(target), current_angles=seed)

            # IKSolver holds its previous solution when it cannot reach the
            # target, so verify with FK before committing to the motors.
            reached = self._ik.forward_kinematics([solution[n] for n in IK_JOINTS])
            miss = math.dist(reached, tuple(target))
            if miss > IK_TOLERANCE_M:
                logger.warning(
                    "IK could not reach (%.3f, %.3f, %.3f); closest was "
                    "(%.3f, %.3f, %.3f), off by %.3fm",
                    *target,
                    *reached,
                    miss,
                )
                return {
                    "ok": False,
                    "error": "target unreachable",
                    "target_xyz": tuple(target),
                    "closest_xyz": reached,
                    "miss_m": round(miss, 4),
                }

            # Full action, like the script — but hold wrist_roll and the
            # gripper where they are instead of snapping them to a constant.
            goal = dict(start)
            for name in IK_JOINTS:
                goal[name] = self.calibration[name].clamp_pos(solution[name])

            measured = self._ramp(start, goal, duration, steps)
            moved = any(
                abs(measured[n] - start[n]) >= MOVED_EPSILON for n in IK_JOINTS
            )
            logger.info(
                "IK move → (%.3f, %.3f, %.3f) joints=%s moved=%s",
                *target,
                {k: round(goal[k], 1) for k in IK_JOINTS},
                moved,
            )
            return {
                "ok": True,
                "mode": "ik",
                "target_xyz": tuple(target),
                "miss_m": round(miss, 4),
                "start_pos": {k: round(v, 2) for k, v in start.items()},
                "goal_pos": {k: round(v, 2) for k, v in goal.items()},
                "measured_pos": {k: round(v, 2) for k, v in measured.items()},
                "moved": moved,
            }

    def move_cartesian(
        self,
        dx: float = 0.0,
        dy: float = 0.0,
        dz: float = 0.0,
    ) -> dict[str, Any]:
        """Shift the end effector by a cartesian delta (meters).

        Frame is the URDF's: x = forward reach, y = lateral (+ left), z = up.
        """
        with self._lock:
            self._ensure()
            current = self.forward_kinematics()
            x, y, z = current
            # Clamp only the axes we are actually moving. The rest pose sits
            # outside the reach envelope, so clamping every axis would drag
            # the arm 4cm backwards on a pure "up" command.
            target = tuple(
                max(WORKSPACE[axis][0], min(WORKSPACE[axis][1], value + delta))
                if delta
                else value
                for axis, value, delta in zip("xyz", current, (dx, dy, dz))
            )
            result = self.move_to_xyz(target)
            result["from_xyz"] = (round(x, 4), round(y, 4), round(z, 4))
            result["delta_xyz"] = (dx, dy, dz)
            return result

    def nudge_joint(self, joint: str, delta: float) -> dict[str, Any]:
        """Ramp one joint by ``delta`` (degrees, or gripper percent)."""
        with self._lock:
            self._ensure()
            cal = self.calibration[joint]
            start = self._transport.read_pos()
            goal = dict(start)
            goal[joint] = cal.clamp_pos(start[joint] + float(delta))

            measured = self._ramp(start, goal, JOINT_DURATION_S, JOINT_STEPS)
            moved = abs(measured[joint] - start[joint]) >= MOVED_EPSILON
            logger.info(
                "SO-101 %s: %.2f → %.2f (delta=%.2f measured=%.2f moved=%s limits=%s)",
                joint,
                start[joint],
                goal[joint],
                delta,
                measured[joint],
                moved,
                cal.pos_limits,
            )
            return {
                "ok": True,
                "joint": joint,
                "before": round(start[joint], 2),
                "goal": round(goal[joint], 2),
                "measured": round(measured[joint], 2),
                "delta": float(delta),
                "moved": moved,
                "limits": [round(v, 1) for v in cal.pos_limits],
            }

    def hold(self) -> dict[str, Any]:
        """Command the current pose so gravity does not drop the links."""
        with self._lock:
            self._ensure()
            pos = self._transport.read_pos()
            self._transport.write_pos(pos)
            return {"ok": True, "held": {k: round(v, 2) for k, v in pos.items()}}


_arm: SO101Arm | None = None
_arm_lock = threading.Lock()
_arm_key: tuple[str, str, str] | None = None


def get_arm(
    port: str,
    calibration_path: str | Path | None = None,
    urdf_path: str | Path | None = None,
) -> SO101Arm:
    global _arm, _arm_key
    cal_path = str(Path(calibration_path) if calibration_path else default_calibration_path())
    urdf = str(Path(urdf_path) if urdf_path else default_urdf_path())
    key = (port, cal_path, urdf)
    with _arm_lock:
        if _arm is None or _arm_key != key:
            if _arm is not None:
                try:
                    _arm.disconnect()
                except Exception:  # noqa: BLE001
                    logger.exception("Error disconnecting previous arm")
            _arm = SO101Arm(
                port,
                calibration=load_calibration(cal_path),
                calibration_path=cal_path,
                urdf_path=urdf,
            )
            _arm_key = key
        return _arm


def _cartesian_step_m(distance_meters: float | None) -> float:
    meters = abs(float(distance_meters or 0.05))
    # Text distances are often large (0.2–1m); clamp to a safe EE step.
    return max(0.015, min(MAX_CARTESIAN_STEP_M, meters))


# Joint-space only for wrist / gripper. Spatial moves use IK.
_JOINT_ONLY: dict[str, tuple[str, int]] = {
    "tilt_up": ("wrist_flex", +1),
    "tilt_down": ("wrist_flex", -1),
    "roll_left": ("wrist_roll", +1),
    "roll_right": ("wrist_roll", -1),
    "open": ("gripper", +1),
    "close": ("gripper", -1),
}

DEFAULT_WRIST_DEGREES = 20.0
GRIPPER_STEP_PERCENT = 25.0


def apply_move(
    *,
    port: str,
    direction: str,
    distance_meters: float | None,
    angle_degrees: float | None,
    calibration_path: str | Path | None = None,
    urdf_path: str | Path | None = None,
) -> dict[str, Any]:
    arm = get_arm(port, calibration_path, urdf_path)
    arm.connect()

    if direction == "stop":
        return {"ok": True, "detail": arm.hold()}

    # Cartesian IK path — drives shoulder_lift AND elbow_flex as separate servos.
    if direction in {"forward", "backward", "up", "down", "left", "right"}:
        step = _cartesian_step_m(distance_meters)
        if direction in {"left", "right"}:
            # Convert turn angle into a sideways EE step at ~current reach.
            degrees = float(angle_degrees if angle_degrees is not None else 30.0)
            step = max(0.015, min(MAX_CARTESIAN_STEP_M, abs(degrees) / 90.0 * 0.06))

        # See WORKSPACE: +x is reach, +y is left, +z is up.
        dx = dy = dz = 0.0
        if direction == "forward":
            dx = +step
        elif direction == "backward":
            dx = -step
        elif direction == "up":
            dz = +step
        elif direction == "down":
            dz = -step
        elif direction == "left":
            dy = +step
        elif direction == "right":
            dy = -step

        try:
            detail = arm.move_cartesian(dx=dx, dy=dy, dz=dz)
        except Exception as exc:  # noqa: BLE001
            logger.exception("IK move failed")
            return {"ok": False, "detail": {"error": f"ik failed: {exc}"}}

        return {"ok": bool(detail.get("ok")), "detail": detail}

    mapping = _JOINT_ONLY.get(direction)
    if mapping is None:
        return {"ok": False, "detail": {"error": f"unsupported direction {direction!r}"}}

    joint, sign = mapping
    if direction in {"open", "close"}:
        delta = sign * GRIPPER_STEP_PERCENT
    else:
        degrees = abs(float(angle_degrees if angle_degrees is not None else DEFAULT_WRIST_DEGREES))
        delta = sign * degrees

    detail = arm.nudge_joint(joint, delta)
    return {"ok": bool(detail.get("moved", True)), "detail": detail}

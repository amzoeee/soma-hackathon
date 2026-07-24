"""SO-101 driver using LeRobot calibration ranges for safe multi-joint motion."""

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

# STS3215 control table (protocol 0)
_TORQUE_ENABLE = 40
_ACCELERATION = 41
_GOAL_POSITION = 42
_GOAL_SPEED = 46
_PRESENT_POSITION = 56
_HOMING_OFFSET = 31

TICKS_PER_REV = 4096
TICKS_PER_DEGREE = TICKS_PER_REV / 360.0

DEFAULT_BAUD = 1_000_000
DEFAULT_ACCEL = 60
DEFAULT_GOAL_SPEED = 450
MIN_WRIST_DEGREES = -160.0
MAX_WRIST_DEGREES = 160.0

DEFAULT_JOINT_IDS = {
    "shoulder_pan": 1,
    "shoulder_lift": 2,
    "elbow_flex": 3,
    "wrist_flex": 4,
    "wrist_roll": 5,
    "gripper": 6,
}

IK_JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex")
MAX_CARTESIAN_STEP_M = 0.06
WORKSPACE = {
    "x": (-0.20, 0.20),
    "y": (0.02, 0.35),
    "z": (0.02, 0.35),
}


@dataclass(frozen=True)
class JointCalib:
    name: str
    motor_id: int
    drive_mode: int
    homing_offset: int
    range_min: int
    range_max: int

    @property
    def sign(self) -> int:
        # LeRobot drive_mode 1 inverts the positive direction.
        return -1 if self.drive_mode == 1 else 1

    def clamp(self, ticks: int) -> int:
        lo, hi = self.range_min, self.range_max
        if lo > hi:
            lo, hi = hi, lo
        return max(lo, min(hi, int(ticks)))


def _repo_root() -> Path:
    # agent/src/demo/hardware/so101.py → repo root
    return Path(__file__).resolve().parents[4]


def default_calibration_path() -> Path:
    return _repo_root() / "robot" / "calibration" / "my_follower.json"


def default_urdf_path() -> Path:
    return _repo_root() / "robot" / "config" / "so101.urdf"


def _load_ik_solver(urdf_path: Path):
    """Import the repo IK solver (ikpy) with a stable sys.path."""
    import sys

    robot_src = str(_repo_root() / "robot" / "src")
    if robot_src not in sys.path:
        sys.path.insert(0, robot_src)
    from ik.solver import IKSolver  # type: ignore

    return IKSolver(str(urdf_path))


def ticks_to_degrees(cal: JointCalib, ticks: int) -> float:
    """Map calibrated raw ticks → degrees (0° ≈ mid of calibrated range)."""
    mid = (cal.range_min + cal.range_max) / 2.0
    return cal.sign * (float(ticks) - mid) / TICKS_PER_DEGREE


def degrees_to_ticks(cal: JointCalib, degrees: float) -> int:
    """Map degrees → calibrated raw ticks, clamped to range_min/max."""
    mid = (cal.range_min + cal.range_max) / 2.0
    raw = mid + cal.sign * float(degrees) * TICKS_PER_DEGREE
    return cal.clamp(int(round(raw)))


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
            range_max=int(spec.get("range_max", 4095)),
        )
    missing = [n for n in DEFAULT_JOINT_IDS if n not in out]
    if missing:
        raise ValueError(f"Calibration missing joints: {missing}")
    logger.info("Loaded SO-101 calibration from %s (%d joints)", cal_path, len(out))
    return out


def _decode_position(raw: int) -> int:
    if raw & 0x8000:
        return -(raw & 0x7FFF)
    return raw & 0x7FFF


def _encode_position(pos: int) -> int:
    if pos < 0:
        return (-pos & 0x7FFF) | 0x8000
    return pos & 0x7FFF


class SO101Arm:
    def __init__(
        self,
        port: str,
        *,
        calibration: dict[str, JointCalib],
        urdf_path: str | Path | None = None,
        baudrate: int = DEFAULT_BAUD,
        accel: int = DEFAULT_ACCEL,
        goal_speed: int = DEFAULT_GOAL_SPEED,
    ) -> None:
        self.port_name = port
        self.calibration = calibration
        self.urdf_path = Path(urdf_path) if urdf_path else default_urdf_path()
        self.baudrate = baudrate
        self.accel = accel
        self.goal_speed = goal_speed
        self._lock = threading.RLock()
        self._port = None
        self._packet = None
        self._sdk = None
        self._connected = False
        self._ik = None

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        with self._lock:
            if self._connected:
                return
            try:
                import scservo_sdk as sdk
            except ImportError as exc:
                raise RuntimeError(
                    "feetech-servo-sdk is required "
                    "(pip install feetech-servo-sdk pyserial)"
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
            self._connected = True
            try:
                self._ik = _load_ik_solver(self.urdf_path)
                logger.info("IK solver ready (%s)", self.urdf_path)
            except Exception:  # noqa: BLE001
                self._ik = None
                logger.exception("IK unavailable; cartesian moves will fail closed")
            self._stabilize_unlocked(skip_gripper=True)
            logger.info(
                "Connected SO-101 on %s with calibration joints=%s",
                self.port_name,
                list(self.calibration),
            )

    def disconnect(self) -> None:
        with self._lock:
            if not self._connected:
                return
            try:
                for cal in self.calibration.values():
                    try:
                        self._write1(cal.motor_id, _TORQUE_ENABLE, 0)
                    except Exception:  # noqa: BLE001
                        pass
            finally:
                try:
                    if self._port is not None:
                        self._port.closePort()
                finally:
                    self._port = None
                    self._packet = None
                    self._sdk = None
                    self._connected = False
                    logger.info("Disconnected SO-101 on %s", self.port_name)

    def _ensure(self) -> None:
        if not self._connected:
            self.connect()

    def _read2(self, motor_id: int, address: int) -> int:
        assert self._packet and self._port and self._sdk
        last: Exception | None = None
        for _ in range(4):
            val, result, error = self._packet.read2ByteTxRx(self._port, motor_id, address)
            if result == self._sdk.COMM_SUCCESS:
                if error:
                    logger.warning("servo id=%s addr=%s err=%s", motor_id, address, error)
                return val
            last = RuntimeError(f"read2 id={motor_id} addr={address} result={result}")
            time.sleep(0.03)
        raise last  # type: ignore[misc]

    def _write1(self, motor_id: int, address: int, value: int) -> None:
        assert self._packet and self._port and self._sdk
        result, error = self._packet.write1ByteTxRx(self._port, motor_id, address, value)
        if result != self._sdk.COMM_SUCCESS:
            raise RuntimeError(f"write1 id={motor_id} addr={address} result={result}")
        if error:
            logger.warning("servo id=%s addr=%s err=%s", motor_id, address, error)

    def _write2(self, motor_id: int, address: int, value: int) -> None:
        assert self._packet and self._port and self._sdk
        result, error = self._packet.write2ByteTxRx(self._port, motor_id, address, value)
        if result != self._sdk.COMM_SUCCESS:
            raise RuntimeError(f"write2 id={motor_id} addr={address} result={result}")
        if error:
            logger.warning("servo id=%s addr=%s err=%s", motor_id, address, error)

    def _read_pos(self, motor_id: int) -> int:
        return _decode_position(self._read2(motor_id, _PRESENT_POSITION))

    def _set_goal(self, cal: JointCalib, goal: int, *, retries: int = 4) -> int:
        goal = cal.clamp(goal)
        last: Exception | None = None
        for attempt in range(retries):
            try:
                self._write1(cal.motor_id, _TORQUE_ENABLE, 1)
                self._write1(cal.motor_id, _ACCELERATION, self.accel)
                self._write2(cal.motor_id, _GOAL_SPEED, self.goal_speed)
                self._write2(cal.motor_id, _GOAL_POSITION, _encode_position(goal))
                return goal
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(0.04 * (attempt + 1))
        raise last  # type: ignore[misc]

    def _stabilize_unlocked(self, *, skip_gripper: bool = True) -> dict[str, int]:
        held: dict[str, int] = {}
        for name, cal in self.calibration.items():
            if skip_gripper and name == "gripper":
                continue
            try:
                pos = self._read_pos(cal.motor_id)
                self._set_goal(cal, pos)
                held[name] = pos
            except Exception:  # noqa: BLE001
                logger.exception("Failed to stabilize %s", name)
        return held

    def stabilize(self) -> dict[str, int]:
        with self._lock:
            self._ensure()
            held = self._stabilize_unlocked(skip_gripper=True)
            logger.info("SO-101 stabilized %s", held)
            return held

    def nudge_joint(self, joint: str, delta_ticks: int) -> dict[str, Any]:
        with self._lock:
            self._ensure()
            cal = self.calibration[joint]
            # Hold the rest of the arm so links don't collapse.
            held = self._stabilize_unlocked(skip_gripper=(joint != "gripper"))
            before = held.get(joint)
            if before is None:
                before = self._read_pos(cal.motor_id)
            # Apply calibration drive_mode sign.
            signed_delta = int(delta_ticks) * cal.sign
            goal = self._set_goal(cal, before + signed_delta)
            time.sleep(0.2)
            after = self._read_pos(cal.motor_id)
            moved = abs(after - before) >= 6
            logger.info(
                "SO-101 %s id=%s: %s → goal %s (cmd_delta=%s signed=%s measured=%s moved=%s range=%s..%s)",
                joint,
                cal.motor_id,
                before,
                goal,
                delta_ticks,
                signed_delta,
                after,
                moved,
                cal.range_min,
                cal.range_max,
            )
            return {
                "joint": joint,
                "motor_id": cal.motor_id,
                "before": before,
                "goal": goal,
                "measured": after,
                "delta_ticks": int(delta_ticks),
                "moved": moved,
                "range": [cal.range_min, cal.range_max],
            }

    def set_gripper(self, state: str) -> dict[str, Any]:
        """Move the gripper to its calibrated open or closed endpoint."""
        with self._lock:
            self._ensure()
            cal = self.calibration["gripper"]
            before = self._read_pos(cal.motor_id)
            goal = cal.range_max if state == "open" else cal.range_min
            self._set_goal(cal, goal)
            time.sleep(0.3)
            measured = self._read_pos(cal.motor_id)
            moved = abs(measured - before) >= 6 or abs(goal - before) < 6
            return {
                "state": state,
                "before": before,
                "goal": goal,
                "measured": measured,
                "moved": moved,
                "range": [cal.range_min, cal.range_max],
            }

    def hold(self) -> dict[str, Any]:
        with self._lock:
            self._ensure()
            return {"held": self._stabilize_unlocked(skip_gripper=True)}

    def get_ik_joint_degrees(self) -> list[float]:
        """Current IK-relevant joint angles in degrees (pan, lift, elbow, wrist_flex)."""
        with self._lock:
            self._ensure()
            degrees: list[float] = []
            for name in IK_JOINTS:
                cal = self.calibration[name]
                ticks = self._read_pos(cal.motor_id)
                degrees.append(ticks_to_degrees(cal, ticks))
            return degrees

    def set_ik_joint_degrees(self, angles: dict[str, float]) -> dict[str, Any]:
        """Command multiple IK joints at once (keeps wrist_roll / gripper held)."""
        with self._lock:
            self._ensure()
            held = self._stabilize_unlocked(skip_gripper=True)
            applied: dict[str, Any] = {}
            for name in IK_JOINTS:
                if name not in angles:
                    continue
                cal = self.calibration[name]
                before = held.get(name, self._read_pos(cal.motor_id))
                goal = degrees_to_ticks(cal, float(angles[name]))
                self._set_goal(cal, goal)
                applied[name] = {
                    "before_ticks": before,
                    "goal_ticks": goal,
                    "goal_deg": float(angles[name]),
                }
            time.sleep(0.25)
            measured = {
                name: self._read_pos(self.calibration[name].motor_id) for name in IK_JOINTS
            }
            return {"applied": applied, "measured_ticks": measured}

    def move_cartesian(
        self,
        dx: float = 0.0,
        dy: float = 0.0,
        dz: float = 0.0,
    ) -> dict[str, Any]:
        """Move the end-effector by a cartesian delta using IK (meters).

        Coordinates match the demo script convention:
        x = left/right, y = forward reach, z = up/down.
        """
        with self._lock:
            self._ensure()
            if self._ik is None:
                raise RuntimeError("IK solver is not available")

            current = self.get_ik_joint_degrees()
            x, y, z = self._ik.forward_kinematics(current)
            target = (
                max(WORKSPACE["x"][0], min(WORKSPACE["x"][1], x + dx)),
                max(WORKSPACE["y"][0], min(WORKSPACE["y"][1], y + dy)),
                max(WORKSPACE["z"][0], min(WORKSPACE["z"][1], z + dz)),
            )
            solution = self._ik.solve(target, current_angles=current)
            result = self.set_ik_joint_degrees(solution)
            measured_ticks = result.get("measured_ticks", {})
            measured_angles = [
                ticks_to_degrees(
                    self.calibration[name],
                    int(measured_ticks.get(name, 0)),
                )
                for name in IK_JOINTS
            ]
            measured_xyz = self._ik.forward_kinematics(measured_angles)
            logger.info(
                "IK cartesian (%.3f,%.3f,%.3f) → target (%.3f,%.3f,%.3f) "
                "measured (%.3f,%.3f,%.3f) joints=%s",
                x,
                y,
                z,
                target[0],
                target[1],
                target[2],
                measured_xyz[0],
                measured_xyz[1],
                measured_xyz[2],
                {k: round(v, 1) for k, v in solution.items()},
            )
            return {
                "mode": "ik",
                "from_xyz": (x, y, z),
                "to_xyz": target,
                "measured_xyz": measured_xyz,
                "delta_xyz": (dx, dy, dz),
                "joints_deg": solution,
                "command": result,
            }


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
                urdf_path=urdf,
            )
            _arm_key = key
        return _arm


def _limit_cartesian_delta(
    delta_x_m: float,
    delta_y_m: float,
    delta_z_m: float,
) -> tuple[float, float, float]:
    """Limit a vector while preserving its XYZ direction."""
    requested = (float(delta_x_m), float(delta_y_m), float(delta_z_m))
    magnitude = math.sqrt(sum(value * value for value in requested))
    if magnitude <= MAX_CARTESIAN_STEP_M:
        return requested
    scale = MAX_CARTESIAN_STEP_M / magnitude
    return tuple(value * scale for value in requested)  # type: ignore[return-value]


def apply_cartesian_delta(
    *,
    port: str,
    delta_x_m: float,
    delta_y_m: float,
    delta_z_m: float,
    calibration_path: str | Path | None = None,
    urdf_path: str | Path | None = None,
) -> dict[str, Any]:
    arm = get_arm(port, calibration_path, urdf_path)
    arm.connect()

    requested = (float(delta_x_m), float(delta_y_m), float(delta_z_m))
    commanded = _limit_cartesian_delta(*requested)
    try:
        detail = arm.move_cartesian(
            dx=commanded[0],
            dy=commanded[1],
            dz=commanded[2],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("IK move failed")
        return {"ok": False, "detail": {"error": f"ik failed: {exc}"}}

    from_xyz = detail.get("from_xyz", (0.0, 0.0, 0.0))
    measured_xyz = detail.get("measured_xyz", detail.get("to_xyz", from_xyz))
    applied = tuple(float(measured_xyz[i]) - float(from_xyz[i]) for i in range(3))
    changed = any(
        abs(joint_info.get("goal_ticks", 0) - joint_info.get("before_ticks", 0)) >= 6
        for joint_info in detail.get("command", {}).get("applied", {}).values()
    )
    detail.update(
        {
            "requested_delta_xyz": requested,
            "commanded_delta_xyz": commanded,
            "applied_delta_xyz": applied,
            "moved": changed,
        }
    )
    return {"ok": changed, "detail": detail}


def apply_wrist_delta(
    *,
    port: str,
    pitch_degrees: float,
    roll_degrees: float,
    calibration_path: str | Path | None = None,
    urdf_path: str | Path | None = None,
) -> dict[str, Any]:
    """Apply differential wrist pitch and roll, each bounded to ±160 degrees."""
    pitch = float(pitch_degrees)
    roll = float(roll_degrees)
    if not MIN_WRIST_DEGREES <= pitch <= MAX_WRIST_DEGREES:
        return {"ok": False, "detail": {"error": "pitch must be between -160 and +160"}}
    if not MIN_WRIST_DEGREES <= roll <= MAX_WRIST_DEGREES:
        return {"ok": False, "detail": {"error": "roll must be between -160 and +160"}}

    arm = get_arm(port, calibration_path, urdf_path)
    arm.connect()
    results: dict[str, Any] = {}
    if abs(pitch) > 1e-9:
        pitch_ticks = int(round(pitch * TICKS_PER_DEGREE))
        results["pitch"] = arm.nudge_joint("wrist_flex", pitch_ticks)
    if abs(roll) > 1e-9:
        # Public convention is +roll right; this servo's positive tick direction is left.
        roll_ticks = int(round(-roll * TICKS_PER_DEGREE))
        results["roll"] = arm.nudge_joint("wrist_roll", roll_ticks)
    moved = all(result.get("moved", False) for result in results.values())
    applied_pitch = 0.0
    if "pitch" in results:
        result = results["pitch"]
        cal = arm.calibration["wrist_flex"]
        applied_pitch = (
            cal.sign
            * (float(result["measured"]) - float(result["before"]))
            / TICKS_PER_DEGREE
        )
    applied_roll = 0.0
    if "roll" in results:
        result = results["roll"]
        cal = arm.calibration["wrist_roll"]
        applied_roll = (
            -cal.sign
            * (float(result["measured"]) - float(result["before"]))
            / TICKS_PER_DEGREE
        )
    return {
        "ok": moved,
        "detail": {
            "requested": {"pitch_degrees": pitch, "roll_degrees": roll},
            "applied": {
                "pitch_degrees": applied_pitch,
                "roll_degrees": applied_roll,
            },
            "joints": results,
            "moved": moved,
        },
    }


def apply_gripper_state(
    *,
    port: str,
    state: str,
    calibration_path: str | Path | None = None,
    urdf_path: str | Path | None = None,
) -> dict[str, Any]:
    if state not in {"open", "closed"}:
        return {"ok": False, "detail": {"error": "state must be open or closed"}}
    arm = get_arm(port, calibration_path, urdf_path)
    detail = arm.set_gripper(state)
    return {"ok": bool(detail.get("moved")), "detail": detail}


def apply_hold_position(
    *,
    port: str,
    calibration_path: str | Path | None = None,
    urdf_path: str | Path | None = None,
) -> dict[str, Any]:
    arm = get_arm(port, calibration_path, urdf_path)
    return {"ok": True, "detail": arm.hold()}

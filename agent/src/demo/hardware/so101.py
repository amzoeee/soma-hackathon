"""Minimal SO-101 (Feetech STS3215) driver for text → real joint motion.

Maps the demo's base-style directions onto a few arm joints so iMessage
commands produce visible motion without full IK/calibration.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger("demo.hardware.so101")

# STS3215 control table (protocol 0)
_TORQUE_ENABLE = 40
_ACCELERATION = 41
_GOAL_POSITION = 42
_PRESENT_POSITION = 56

# SO-101 motor IDs (LeRobot convention)
JOINT_IDS: dict[str, int] = {
    "shoulder_pan": 1,
    "shoulder_lift": 2,
    "elbow_flex": 3,
    "wrist_flex": 4,
    "wrist_roll": 5,
    "gripper": 6,
}

TICKS_PER_REV = 4096
TICKS_PER_DEGREE = TICKS_PER_REV / 360.0

# Conservative defaults for first live text→motion tests.
DEFAULT_BAUD = 1_000_000
DEFAULT_ACCEL = 40
# ~10.5° of elbow motion per commanded meter.
TICKS_PER_METER = 120
MAX_TRANSLATION_TICKS = 160  # ~14°
MAX_TURN_TICKS = 250  # ~22°


def _decode_position(raw: int) -> int:
    """STS present/goal position uses sign-magnitude on bit 15."""
    if raw & 0x8000:
        return -(raw & 0x7FFF)
    return raw & 0x7FFF


def _encode_position(pos: int) -> int:
    if pos < 0:
        return (-pos & 0x7FFF) | 0x8000
    return pos & 0x7FFF


class SO101Arm:
    """Thread-safe singleton-friendly connection to one SO-101 follower."""

    def __init__(
        self,
        port: str,
        *,
        baudrate: int = DEFAULT_BAUD,
        accel: int = DEFAULT_ACCEL,
    ) -> None:
        self.port_name = port
        self.baudrate = baudrate
        self.accel = accel
        self._lock = threading.RLock()
        self._port = None
        self._packet = None
        self._connected = False

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
                    "feetech-servo-sdk is required for real robot motion "
                    "(pip install feetech-servo-sdk pyserial)"
                ) from exc

            port = sdk.PortHandler(self.port_name)
            packet = sdk.PacketHandler(0)
            if not port.openPort():
                raise RuntimeError(f"Failed to open robot port {self.port_name}")
            if not port.setBaudRate(self.baudrate):
                port.closePort()
                raise RuntimeError(f"Failed to set baud {self.baudrate} on {self.port_name}")

            # Verify at least the pan joint responds.
            _, result, _ = packet.ping(port, JOINT_IDS["shoulder_pan"])
            if result != sdk.COMM_SUCCESS:
                port.closePort()
                raise RuntimeError(f"No SO-101 response on {self.port_name}")

            self._sdk = sdk
            self._port = port
            self._packet = packet
            self._connected = True
            logger.info("Connected to SO-101 on %s", self.port_name)

    def disconnect(self) -> None:
        with self._lock:
            if not self._connected:
                return
            try:
                for mid in JOINT_IDS.values():
                    self._write1(mid, _TORQUE_ENABLE, 0)
            except Exception:  # noqa: BLE001 — best-effort torque off
                logger.exception("Failed to disable torque during disconnect")
            try:
                if self._port is not None:
                    self._port.closePort()
            finally:
                self._port = None
                self._packet = None
                self._connected = False
                logger.info("Disconnected SO-101 on %s", self.port_name)

    def _read2(self, motor_id: int, address: int) -> int:
        assert self._packet is not None and self._port is not None
        val, result, error = self._packet.read2ByteTxRx(self._port, motor_id, address)
        if result != self._sdk.COMM_SUCCESS:
            raise RuntimeError(f"read2 failed id={motor_id} addr={address} result={result}")
        if error:
            logger.warning("servo id=%s addr=%s error bit=%s", motor_id, address, error)
        return val

    def _write1(self, motor_id: int, address: int, value: int) -> None:
        assert self._packet is not None and self._port is not None
        result, error = self._packet.write1ByteTxRx(self._port, motor_id, address, value)
        if result != self._sdk.COMM_SUCCESS:
            raise RuntimeError(f"write1 failed id={motor_id} addr={address} result={result}")
        if error:
            logger.warning("servo id=%s addr=%s error bit=%s", motor_id, address, error)

    def _write2(self, motor_id: int, address: int, value: int) -> None:
        assert self._packet is not None and self._port is not None
        result, error = self._packet.write2ByteTxRx(self._port, motor_id, address, value)
        if result != self._sdk.COMM_SUCCESS:
            raise RuntimeError(f"write2 failed id={motor_id} addr={address} result={result}")
        if error:
            logger.warning("servo id=%s addr=%s error bit=%s", motor_id, address, error)

    def read_position(self, joint: str) -> int:
        with self._lock:
            self._ensure()
            return _decode_position(self._read2(JOINT_IDS[joint], _PRESENT_POSITION))

    def _ensure(self) -> None:
        if not self._connected:
            self.connect()

    def _enable_and_goal(self, joint: str, goal: int) -> None:
        mid = JOINT_IDS[joint]
        self._write1(mid, _TORQUE_ENABLE, 1)
        self._write1(mid, _ACCELERATION, self.accel)
        self._write2(mid, _GOAL_POSITION, _encode_position(goal))

    def nudge_joint(self, joint: str, delta_ticks: int) -> dict[str, Any]:
        """Relative move of one joint. Returns before/after goal info."""
        with self._lock:
            self._ensure()
            before = self.read_position(joint)
            goal = before + int(delta_ticks)
            self._enable_and_goal(joint, goal)
            logger.info(
                "SO-101 %s: %s → %s (delta=%s)",
                joint,
                before,
                goal,
                delta_ticks,
            )
            return {
                "joint": joint,
                "before": before,
                "goal": goal,
                "delta_ticks": int(delta_ticks),
            }

    def hold(self) -> dict[str, Any]:
        """Enable torque and hold each joint at its present position."""
        with self._lock:
            self._ensure()
            held: dict[str, int] = {}
            for joint in JOINT_IDS:
                pos = self.read_position(joint)
                self._enable_and_goal(joint, pos)
                held[joint] = pos
            logger.info("SO-101 hold at %s", held)
            return {"held": held}


_arm: SO101Arm | None = None
_arm_lock = threading.Lock()


def get_arm(port: str) -> SO101Arm:
    global _arm
    with _arm_lock:
        if _arm is None or _arm.port_name != port:
            if _arm is not None:
                try:
                    _arm.disconnect()
                except Exception:  # noqa: BLE001
                    logger.exception("Error disconnecting previous arm")
            _arm = SO101Arm(port)
        return _arm


def apply_move(
    *,
    port: str,
    direction: str,
    distance_meters: float | None,
    angle_degrees: float | None,
) -> dict[str, Any]:
    """Map demo directions onto a safe relative SO-101 joint nudge."""
    arm = get_arm(port)
    arm.connect()

    if direction == "stop":
        return {"ok": True, "detail": arm.hold()}

    if direction in ("forward", "backward"):
        meters = float(distance_meters or 0.0)
        ticks = int(round(meters * TICKS_PER_METER))
        ticks = max(-MAX_TRANSLATION_TICKS, min(MAX_TRANSLATION_TICKS, ticks))
        if direction == "backward":
            ticks = -ticks
        detail = arm.nudge_joint("elbow_flex", ticks)
        return {"ok": True, "detail": detail}

    if direction in ("left", "right"):
        degrees = float(angle_degrees if angle_degrees is not None else 90.0)
        ticks = int(round(degrees * TICKS_PER_DEGREE))
        ticks = max(-MAX_TURN_TICKS, min(MAX_TURN_TICKS, ticks))
        if direction == "right":
            ticks = -ticks
        detail = arm.nudge_joint("shoulder_pan", ticks)
        return {"ok": True, "detail": detail}

    return {"ok": False, "detail": {"error": f"unsupported direction {direction!r}"}}

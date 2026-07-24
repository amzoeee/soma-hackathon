"""
Unit conversion utilities for SO-101 motor positions.

LeRobot hardware uses degrees [-180, 180] or raw servo steps [0, 4095]
depending on configuration, whereas URDF and IK engines (ikpy) use Radians.
"""

import math

# Servo constants for Feetech STS3215
SERVO_CENTER_RAW = 2048
RAW_STEPS_PER_DEGREE = 4096.0 / 360.0  # ~11.377 steps per degree
RAW_STEPS_PER_RADIAN = 4096.0 / (2 * math.pi)

def degrees_to_radians(deg: float) -> float:
    """Convert degrees to radians."""
    return math.radians(deg)

def radians_to_degrees(rad: float) -> float:
    """Convert radians to degrees."""
    return math.degrees(rad)

def raw_to_degrees(raw: float) -> float:
    """Convert raw Feetech motor step [0, 4095] to centered degrees [-180, 180]."""
    return (raw - SERVO_CENTER_RAW) / RAW_STEPS_PER_DEGREE

def degrees_to_raw(deg: float) -> int:
    """Convert centered degrees [-180, 180] to raw Feetech motor step [0, 4095]."""
    return int(round(SERVO_CENTER_RAW + (deg * RAW_STEPS_PER_DEGREE)))

def raw_to_radians(raw: float) -> float:
    """Convert raw Feetech motor step to radians relative to center."""
    return (raw - SERVO_CENTER_RAW) / RAW_STEPS_PER_RADIAN

def radians_to_raw(rad: float) -> int:
    """Convert radians relative to center to raw Feetech motor step."""
    return int(round(SERVO_CENTER_RAW + (rad * RAW_STEPS_PER_RADIAN)))

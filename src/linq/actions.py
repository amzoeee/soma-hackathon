"""The action vocabulary Linq can emit, and the JSON schema Claude fills in.

Every action is a plain dict on the wire (that is what the model returns and
what LangGraph state carries). The dataclasses exist for typed access inside
the executor; use `parse_action` to go from dict -> dataclass.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union


def _obj(name: str, props: Dict[str, Any], doc: str) -> Dict[str, Any]:
    """Build one variant of the discriminated union."""
    properties = {"type": {"const": name}}
    properties.update(props)
    return {
        "type": "object",
        "description": doc,
        "properties": properties,
        "required": list(properties.keys()),
        "additionalProperties": False,
    }


_METERS = {"type": "number"}


@dataclass
class MoveTo:
    """Absolute end-effector target in robot frame (meters)."""
    x: float
    y: float
    z: float

    NAME = 'move_to'
    SCHEMA = _obj('move_to', {"x": _METERS, "y": _METERS, "z": _METERS},
                  "Move the gripper to an absolute (x, y, z) point in meters.")


@dataclass
class Nudge:
    """Relative end-effector offset from the current target (meters)."""
    dx: float
    dy: float
    dz: float

    NAME = 'nudge'
    SCHEMA = _obj('nudge', {"dx": _METERS, "dy": _METERS, "dz": _METERS},
                  "Shift the gripper by a relative offset in meters.")


@dataclass
class Gripper:
    """Gripper aperture, 0.0 = fully closed, 1.0 = fully open."""
    position: float

    NAME = 'gripper'
    SCHEMA = _obj('gripper', {"position": {"type": "number"}},
                  "Set gripper aperture: 0.0 closed, 1.0 open.")


@dataclass
class Home:
    """Return to the rest pose."""

    NAME = 'home'
    SCHEMA = _obj('home', {}, "Return the arm to its rest pose.")


@dataclass
class Wait:
    """Pause between actions."""
    seconds: float

    NAME = 'wait'
    SCHEMA = _obj('wait', {"seconds": {"type": "number"}},
                  "Pause for a number of seconds before the next action.")


@dataclass
class Say:
    """Surface a line on the glasses overlay / speaker."""
    text: str

    NAME = 'say'
    SCHEMA = _obj('say', {"text": {"type": "string"}},
                  "Show a short line on the operator overlay.")


@dataclass
class SendText:
    """Send an outbound message on a messaging channel."""
    to: str
    body: str

    NAME = 'send_text'
    SCHEMA = _obj('send_text', {"to": {"type": "string"}, "body": {"type": "string"}},
                  "Send a text message to a recipient handle.")


Action = Union[MoveTo, Nudge, Gripper, Home, Wait, Say, SendText]

ACTION_TYPES = [MoveTo, Nudge, Gripper, Home, Wait, Say, SendText]
_BY_NAME = {cls.NAME: cls for cls in ACTION_TYPES}

# What Claude is constrained to return. One reply line plus an ordered plan.
PLAN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "reply": {
            "type": "string",
            "description": "One short sentence back to the user, in Linq's voice.",
        },
        "actions": {
            "type": "array",
            "description": "Ordered actions to execute. Empty if nothing should move.",
            "items": {"anyOf": [cls.SCHEMA for cls in ACTION_TYPES]},
        },
    },
    "required": ["reply", "actions"],
    "additionalProperties": False,
}


def parse_action(payload: Dict[str, Any]) -> Optional[Action]:
    """Turn a wire dict into a typed action, or None if the type is unknown."""
    cls = _BY_NAME.get(payload.get("type", ""))
    if cls is None:
        return None
    fields = {k: v for k, v in payload.items() if k != "type"}
    return cls(**fields)


def describe_vocabulary() -> List[str]:
    """Human-readable action list for the system prompt."""
    return [f"- {cls.NAME}: {cls.SCHEMA['description']}" for cls in ACTION_TYPES]

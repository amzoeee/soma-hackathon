"""Deterministic gate between the model and the motors.

The schema already guarantees shape. This checks *meaning*: reachable targets,
sane plan length, no surprise action types. Nothing gets past here on trust.
"""

import logging
from typing import Any, Callable, Dict, List, Tuple

from ..actions import parse_action
from ..deps import LinqDeps
from ..executor import HOME_POSE
from ..state import LinqState

logger = logging.getLogger(__name__)


def _in_envelope(settings, x: float, y: float, z: float) -> bool:
    return (
        settings.workspace_x_min <= x <= settings.workspace_x_max
        and settings.workspace_y_min <= y <= settings.workspace_y_max
        and settings.workspace_z_min <= z <= settings.workspace_z_max
    )


def make_validate(deps: LinqDeps) -> Callable[[LinqState], Dict[str, Any]]:
    """Node: filter the plan down to what is safe to run."""

    def validate(state: LinqState) -> Dict[str, Any]:
        plan: List[Dict[str, Any]] = state.get("plan", [])
        errors: List[str] = list(state.get("errors", []))

        if errors:
            return {"approved": [], "errors": errors}

        if len(plan) > deps.config.max_actions:
            return {"approved": [],
                    "errors": [f"plan has {len(plan)} actions, limit is "
                               f"{deps.config.max_actions}"]}

        # Track the target across the plan so relative nudges are checked
        # against where the arm will actually be, not where it is now.
        cursor: Tuple[float, float, float] = deps.executor.ee_target
        approved: List[Dict[str, Any]] = []

        for payload in plan:
            action = parse_action(payload)
            if action is None:
                errors.append(f"unknown action type {payload.get('type')!r}")
                break

            kind = payload.get("type")

            if kind == "move_to":
                cursor = (action.x, action.y, action.z)
            elif kind == "nudge":
                cursor = (cursor[0] + action.dx, cursor[1] + action.dy,
                          cursor[2] + action.dz)
            elif kind == "home":
                cursor = HOME_POSE
            elif kind == "gripper":
                if not 0.0 <= action.position <= 1.0:
                    errors.append(f"gripper position {action.position} is outside 0-1")
                    break
            elif kind == "wait":
                if not 0.0 <= action.seconds <= deps.config.max_wait_seconds:
                    errors.append(f"wait of {action.seconds}s exceeds the "
                                  f"{deps.config.max_wait_seconds}s limit")
                    break

            if kind in ("move_to", "nudge", "home") and not _in_envelope(deps.settings, *cursor):
                errors.append(
                    f"{kind} would put the gripper at "
                    f"({cursor[0]:.3f}, {cursor[1]:.3f}, {cursor[2]:.3f}), "
                    "outside the reachable envelope"
                )
                break

            approved.append(payload)

        if errors:
            logger.warning("Rejected plan: %s", errors)
            # Refuse the whole plan rather than running a truncated prefix --
            # a half-executed sequence is worse than none.
            return {"approved": [], "errors": errors}

        return {"approved": approved, "errors": []}

    return validate

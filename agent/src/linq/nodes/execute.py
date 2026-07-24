"""Hand the approved plan to the executor."""

import logging
from typing import Any, Callable, Dict

from ..deps import LinqDeps
from ..state import LinqState

logger = logging.getLogger(__name__)


def make_execute(deps: LinqDeps) -> Callable[[LinqState], Dict[str, Any]]:
    """Node: run approved actions, collect per-action results."""

    def execute(state: LinqState) -> Dict[str, Any]:
        approved = state.get("approved", [])
        if not approved:
            return {"results": []}

        logger.info("Executing %d action(s)%s", len(approved),
                    " (dry-run)" if deps.executor.dry_run else "")
        results = deps.executor.run(approved)

        failures = [r["detail"] for r in results if not r["ok"]]
        return {"results": results, "errors": failures}

    return execute

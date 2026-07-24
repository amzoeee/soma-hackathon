"""The LangGraph wiring.

    understand -> validate -> execute -> respond
                     |                     ^
                     +--- (rejected) ------+

`understand` is the only LLM call. Everything downstream is deterministic, so
a bad plan fails closed at `validate` instead of reaching the motors.
"""

import logging
from typing import Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .deps import LinqDeps
from .nodes import make_execute, make_respond, make_understand, make_validate
from .state import LinqState, new_turn

logger = logging.getLogger(__name__)

__all__ = ["LinqDeps", "build_graph", "run_turn"]


def _route_after_validate(state: LinqState) -> str:
    """Skip execution if validation refused the plan or there is nothing to do."""
    if state.get("errors"):
        return "respond"
    if not state.get("approved"):
        return "respond"
    return "execute"


def build_graph(deps: LinqDeps, checkpointer=None):
    """Compile the Linq graph.

    Pass a checkpointer to persist conversations across turns; the default
    MemorySaver keeps them for the life of the process.
    """
    graph = StateGraph(LinqState)

    graph.add_node("understand", make_understand(deps))
    graph.add_node("validate", make_validate(deps))
    graph.add_node("execute", make_execute(deps))
    graph.add_node("respond", make_respond(deps))

    graph.add_edge(START, "understand")
    graph.add_edge("understand", "validate")
    graph.add_conditional_edges(
        "validate",
        _route_after_validate,
        {"execute": "execute", "respond": "respond"},
    )
    graph.add_edge("execute", "respond")
    graph.add_edge("respond", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())


def run_turn(app, message: str, thread_id: str = 'default',
             channel: str = 'cli') -> LinqState:
    """Run one inbound message through a compiled graph."""
    config = {"configurable": {"thread_id": thread_id}}
    return app.invoke(new_turn(message, channel), config=config)

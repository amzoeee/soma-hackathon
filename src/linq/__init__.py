"""Linq: message the robot, get movements.

Text/chat in -> LangGraph pipeline -> validated robot actions out.

Re-exports are lazy so importing a leaf module (e.g. `src.linq.actions`) does
not pull in langgraph.
"""

__all__ = ["LinqConfig", "LinqDeps", "build_graph", "run_turn"]

_LAZY = {
    "LinqConfig": ".config",
    "LinqDeps": ".deps",
    "build_graph": ".graph",
    "run_turn": ".graph",
}


def __getattr__(name: str):
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_name, __name__), name)


def __dir__():
    return sorted(__all__)

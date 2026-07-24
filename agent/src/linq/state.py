"""LangGraph state for a single Linq turn."""

import operator
from typing import Annotated, Any, Dict, List, TypedDict


class LinqState(TypedDict, total=False):
    """State threaded through the graph.

    `messages` accumulates across turns via the checkpointer; everything else
    is scratch for the current turn and gets overwritten each time.
    """

    # Conversation history: [{"role": "user" | "assistant", "content": str}]
    messages: Annotated[List[Dict[str, str]], operator.add]

    # Inbound
    inbound: str                     # raw text the user sent
    channel: str                     # which channel it arrived on ('cli', 'http', ...)

    # Planning
    plan: List[Dict[str, Any]]       # actions as returned by the model
    reply_draft: str                 # model's proposed reply

    # Validation / execution
    approved: List[Dict[str, Any]]   # actions that passed validation
    errors: List[str]                # why we refused to run something
    results: List[Dict[str, Any]]    # per-action outcome from the executor

    # Outbound
    reply: str                       # final text handed back to the channel


def new_turn(inbound: str, channel: str = 'cli') -> LinqState:
    """Seed state for one inbound message."""
    return {
        "messages": [{"role": "user", "content": inbound}],
        "inbound": inbound,
        "channel": channel,
        "plan": [],
        "reply_draft": "",
        "approved": [],
        "errors": [],
        "results": [],
        "reply": "",
    }

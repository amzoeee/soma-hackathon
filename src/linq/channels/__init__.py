"""Inbound message sources. Each channel feeds text into the graph."""

from .base import Channel, InboundMessage
from .cli import CLIChannel

__all__ = ["Channel", "InboundMessage", "CLIChannel"]

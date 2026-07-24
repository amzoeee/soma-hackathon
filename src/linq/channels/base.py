"""Channel interface: whatever carries messages to and from Linq."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator


@dataclass
class InboundMessage:
    """One message arriving from a channel."""

    text: str
    sender: str = 'operator'
    thread_id: str = 'default'
    metadata: Dict[str, Any] = field(default_factory=dict)


class Channel(ABC):
    """A bidirectional message transport.

    Implement `listen` as a generator so the runner can drive any transport
    with the same loop. `send` delivers Linq's reply back to the sender.
    """

    name: str = 'channel'

    @abstractmethod
    def listen(self) -> Iterator[InboundMessage]:
        """Yield inbound messages until the channel closes."""

    @abstractmethod
    def send(self, message: InboundMessage, reply: str) -> None:
        """Deliver a reply for the given inbound message."""

    def close(self) -> None:
        """Release any transport resources."""

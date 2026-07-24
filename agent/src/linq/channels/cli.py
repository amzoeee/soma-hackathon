"""Terminal channel -- the fastest way to poke at the graph."""

from typing import Iterator

from .base import Channel, InboundMessage

QUIT_WORDS = {'quit', 'exit', ':q'}


class CLIChannel(Channel):
    """Reads messages from stdin, prints replies to stdout."""

    name = 'cli'

    def __init__(self, thread_id: str = 'default', prompt: str = 'you> '):
        self.thread_id = thread_id
        self.prompt = prompt

    def listen(self) -> Iterator[InboundMessage]:
        while True:
            try:
                text = input(self.prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not text:
                continue
            if text.lower() in QUIT_WORDS:
                return
            yield InboundMessage(text=text, thread_id=self.thread_id)

    def send(self, message: InboundMessage, reply: str) -> None:
        print(f"linq> {reply}")

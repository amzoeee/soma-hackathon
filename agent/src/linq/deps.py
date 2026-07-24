"""Collaborators the graph nodes need, bundled so nodes stay pure functions."""

from dataclasses import dataclass
from typing import Any

from .config import LinqConfig
from .executor import ActionExecutor


@dataclass
class LinqDeps:
    """Everything a node may reach for. Built once at startup."""

    config: LinqConfig
    settings: Any            # config.settings.Settings -- workspace bounds, ports
    executor: ActionExecutor
    client: Any = None       # anthropic.Anthropic; created lazily if omitted

    def anthropic(self):
        """Return (and memoize) the Anthropic client.

        Credentials resolve from the environment: ANTHROPIC_API_KEY, or an
        `ant auth login` profile. Nothing is hardcoded here.
        """
        if self.client is None:
            import anthropic

            self.client = anthropic.Anthropic()
        return self.client

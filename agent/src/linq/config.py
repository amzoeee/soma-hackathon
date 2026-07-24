import argparse
from dataclasses import dataclass

DEFAULT_PERSONA = (
    "You are Linq, the operator brain for a LeRobot SO-101 arm (5-DOF + gripper). "
    "Users message you in plain language; you turn that into a short sequence of "
    "robot actions plus a one-line reply. Be literal and conservative: if a request "
    "is ambiguous or unsafe, emit no actions and ask for clarification in the reply."
)


@dataclass
class LinqConfig:
    """Tunables for the Linq agent (LLM + dispatch policy)."""

    # LLM
    model: str = 'claude-opus-4-8'
    # Text -> action-plan is a narrow task and sits in the control loop, so we
    # trade a little depth for latency. Raise to 'high' if plans get sloppy.
    effort: str = 'medium'
    max_tokens: int = 4096
    persona: str = DEFAULT_PERSONA

    # Dispatch policy
    max_actions: int = 12          # reject plans longer than this
    max_wait_seconds: float = 10.0  # reject a single wait longer than this
    dry_run: bool = True           # log actions instead of driving the arm

    # Conversation
    thread_id: str = 'default'

    @classmethod
    def from_args(cls) -> 'LinqConfig':
        """Parse Linq-specific command-line overrides."""
        parser = argparse.ArgumentParser(description="Linq Agent Settings")
        parser.add_argument('--model', type=str, help='Claude model id')
        parser.add_argument('--effort', type=str,
                            choices=['low', 'medium', 'high', 'xhigh', 'max'],
                            help='Reasoning effort')
        parser.add_argument('--live', action='store_true',
                            help='Actually drive the arm (default is dry-run)')
        parser.add_argument('--thread', type=str, help='Conversation thread id')

        args, _unknown = parser.parse_known_args()

        config = cls()
        if args.model:
            config.model = args.model
        if args.effort:
            config.effort = args.effort
        if args.live:
            config.dry_run = False
        if args.thread:
            config.thread_id = args.thread

        return config

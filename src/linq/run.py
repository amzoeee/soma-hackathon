"""Entry point: python -m src.linq.run

Defaults to dry-run (actions are logged, the arm never moves). Pass --live to
drive real hardware.
"""

import logging
import sys

from config.settings import Settings

from .channels import CLIChannel
from .config import LinqConfig
from .deps import LinqDeps
from .executor import build_executor
from .graph import build_graph, run_turn


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )

    config = LinqConfig.from_args()
    settings = Settings.from_args()

    executor = build_executor(settings, dry_run=config.dry_run)
    deps = LinqDeps(config=config, settings=settings, executor=executor)
    app = build_graph(deps)

    channel = CLIChannel(thread_id=config.thread_id)
    mode = 'dry-run' if executor.dry_run else 'LIVE'
    print(f"Linq ready ({config.model}, {mode}). Type 'quit' to exit.")

    try:
        for message in channel.listen():
            state = run_turn(app, message.text,
                             thread_id=message.thread_id, channel=channel.name)
            channel.send(message, state.get("reply", ""))
    finally:
        channel.close()
        if executor.arm is not None:
            executor.arm.disconnect()

    return 0


if __name__ == '__main__':
    sys.exit(main())

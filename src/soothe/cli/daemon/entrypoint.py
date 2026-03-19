"""Entry point for running Soothe daemon."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from pathlib import Path

from soothe.cli.daemon.server import SootheDaemon
from soothe.config import SOOTHE_HOME, SootheConfig


def run_daemon(config: SootheConfig | None = None) -> None:
    """Start the daemon in the current process (blocking).

    Args:
        config: Soothe configuration.
    """
    daemon = SootheDaemon(config)

    async def _main() -> None:
        await daemon.start()
        await daemon.serve_forever()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main())


def main() -> None:
    """CLI entry point for the daemon module."""
    from soothe.cli.core import setup_logging

    parser = argparse.ArgumentParser(description="Soothe daemon")
    parser.add_argument("--config", type=str, default=None, help="Config file path")
    args = parser.parse_args()

    cfg: SootheConfig | None = None
    if args.config:
        cfg = SootheConfig.from_yaml_file(args.config)
    else:
        default_config = Path(SOOTHE_HOME) / "config" / "config.yml"
        if default_config.exists():
            cfg = SootheConfig.from_yaml_file(str(default_config))

    setup_logging(cfg)
    run_daemon(cfg)


if __name__ == "__main__":
    main()

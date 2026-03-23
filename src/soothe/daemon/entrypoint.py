"""Entry point for running Soothe daemon."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from pathlib import Path

from soothe.config import SOOTHE_HOME, SootheConfig
from soothe.daemon.server import SootheDaemon


def run_daemon(
    config: SootheConfig | None = None,
    *,
    detached: bool = False,
) -> None:
    """Start the daemon in the current process (blocking).

    Args:
        config: Soothe configuration.
        detached: Whether daemon is running as a detached background process.
            In detached mode, SIGINT shutdown handling is disabled.
    """
    daemon = SootheDaemon(config, handle_sigint_shutdown=not detached)

    async def _main() -> None:
        await daemon.start()
        await daemon.serve_forever()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main())


def main() -> None:
    """CLI entry point for the daemon module."""
    from soothe.ux.core import setup_logging

    parser = argparse.ArgumentParser(description="Soothe daemon")
    parser.add_argument("--config", type=str, default=None, help="Config file path")
    parser.add_argument(
        "--detached",
        action="store_true",
        help="Run in detached/background mode (disables SIGINT-triggered shutdown).",
    )
    args = parser.parse_args()

    cfg: SootheConfig | None = None
    if args.config:
        cfg = SootheConfig.from_yaml_file(args.config)
    else:
        default_config = Path(SOOTHE_HOME) / "config" / "config.yml"
        if default_config.exists():
            cfg = SootheConfig.from_yaml_file(str(default_config))

    setup_logging(cfg)
    run_daemon(cfg, detached=args.detached)


if __name__ == "__main__":
    main()

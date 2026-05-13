"""Entry point for running Soothe daemon."""

from __future__ import annotations

# Load environment variables from .env file BEFORE any langchain imports
# so provider API keys and other env-backed config are visible at import time.
from dotenv import load_dotenv

load_dotenv()

import argparse  # noqa: E402
import asyncio  # noqa: E402
import contextlib  # noqa: E402

from soothe.config import SootheConfig  # noqa: E402
from soothe_daemon.config import SootheDaemonConfig  # noqa: E402
from soothe_daemon.server import SootheDaemon  # noqa: E402


def run_daemon(
    config: SootheConfig | None = None,
    daemon_config: SootheDaemonConfig | None = None,
    *,
    detached: bool = False,
) -> None:
    """Start the daemon in the current process (blocking).

    Args:
        config: Agent ``SootheConfig`` (in-proc agent core, ``config.yml``).
        daemon_config: Daemon-server ``SootheDaemonConfig`` (transports,
            worker pool, distributed runner, ``daemon_config.yml``).
        detached: Whether daemon is running as a detached background process.
            In detached mode, SIGINT shutdown handling is disabled.
    """
    daemon = SootheDaemon(
        config,
        daemon_config=daemon_config,
        handle_sigint_shutdown=not detached,
    )

    async def _main() -> None:
        await daemon.start()
        await daemon.serve_forever()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main())


def _load_daemon_config(daemon_config_path: str | None) -> SootheDaemonConfig:
    """Load ``SootheDaemonConfig`` from explicit path or default location."""
    if daemon_config_path:
        return SootheDaemonConfig.from_yaml_file(daemon_config_path)
    return SootheDaemonConfig.from_default_yaml()


def main() -> None:
    """CLI entry point for the daemon module."""
    from soothe.logging import setup_logging

    parser = argparse.ArgumentParser(description="Soothe daemon")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to daemon_config.yml (SootheDaemonConfig)",
    )
    parser.add_argument(
        "--soothe-config",
        type=str,
        default=None,
        help="Path to config.yml (SootheConfig); overrides daemon_config.soothe_config_path",
    )
    parser.add_argument(
        "--detached",
        action="store_true",
        help="Run in detached/background mode (disables SIGINT-triggered shutdown).",
    )
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="Run in foreground with console logging to stdout.",
    )
    args = parser.parse_args()

    daemon_cfg = _load_daemon_config(args.config)

    if args.soothe_config:
        cfg = SootheConfig.from_yaml_file(args.soothe_config)
    else:
        cfg = daemon_cfg.load_soothe_config()

    setup_logging(cfg, foreground=args.foreground)

    # Migrate runtime data files from root to data/ subdirectory
    from soothe_sdk.client.config import migrate_data_to_subdir

    migrate_data_to_subdir()

    run_daemon(cfg, daemon_config=daemon_cfg, detached=args.detached)


if __name__ == "__main__":
    main()

"""Allow running the daemon as a module: python -m soothe.cli.daemon"""

from soothe.cli.daemon.entrypoint import run_daemon
from soothe.config import SOOTHE_HOME, SootheConfig

if __name__ == "__main__":
    import argparse
    from pathlib import Path

    from soothe.cli.main import setup_logging

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

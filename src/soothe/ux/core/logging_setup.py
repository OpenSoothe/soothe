"""Logging configuration for Soothe CLI."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from soothe.config import SOOTHE_HOME, SootheConfig


def setup_logging(config: SootheConfig | None = None) -> None:
    """Configure the ``soothe`` logger hierarchy with file and optional console handlers.

    Writes to ``SOOTHE_HOME/logs/soothe.log`` (rotating, 10 MB max, 3 backups).
    Optionally outputs to console when enabled in config.

    Args:
        config: Optional config to read logging configuration from.
    """
    cfg = config or SootheConfig()
    log_dir = Path(SOOTHE_HOME) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Determine log levels
    file_level_name = cfg.logging.file.level.upper()
    console_level_name = cfg.logging.console.level.upper()

    if cfg.debug:
        file_level_name = "DEBUG"
        console_level_name = "DEBUG"

    file_level = getattr(logging, file_level_name, logging.INFO)
    console_level = getattr(logging, console_level_name, logging.WARNING)

    # Set root logger level to minimum of file and console levels
    root_logger = logging.getLogger("soothe")
    root_logger.setLevel(min(file_level, console_level))

    # Setup file handler
    log_file = cfg.logging.file.path or str(log_dir / "soothe.log")
    if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
        file_handler = RotatingFileHandler(
            log_file, maxBytes=cfg.logging.file.max_bytes, backupCount=cfg.logging.file.backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s %(message)s"))
        file_handler.setLevel(file_level)
        root_logger.addHandler(file_handler)

    # Setup console handler (optional, disabled by default)
    if cfg.logging.console.enabled:
        stream = sys.stderr if cfg.logging.console.stream == "stderr" else sys.stdout
        if not any(isinstance(h, logging.StreamHandler) and h.stream == stream for h in root_logger.handlers):
            console_handler = logging.StreamHandler(stream)
            console_handler.setFormatter(logging.Formatter(cfg.logging.console.format))
            console_handler.setLevel(console_level)
            root_logger.addHandler(console_handler)

    # Suppress noisy third-party loggers
    noisy_third_party = (
        "httpx",
        "httpcore",
        "openai",
        "anthropic",
        "langchain_core",
        "langgraph",
        "browser_use",
        "bubus",
        "cdp_use",
    )
    for name in noisy_third_party:
        logging.getLogger(name).setLevel(logging.WARNING)

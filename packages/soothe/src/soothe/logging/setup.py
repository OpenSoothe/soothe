"""Logging configuration for Soothe."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING

from soothe.config import SOOTHE_HOME
from soothe.logging.context import get_thread_id

if TYPE_CHECKING:
    from soothe.config import SootheConfig


class ThreadFormatter(logging.Formatter):
    """Custom formatter that includes the Soothe conversation thread ID."""

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with both Soothe and OS thread IDs.

        Args:
            record: The log record to format.

        Returns:
            The formatted log message string.
        """
        soothe_thread_id = get_thread_id()
        record.thread_id = f"[{soothe_thread_id}]" if soothe_thread_id else "[main]"
        return super().format(record)


def setup_logging(config: SootheConfig | None = None) -> None:
    """Configure the ``soothe`` logger hierarchy with file and optional console handlers.

    Writes to ``SOOTHE_HOME/logs/soothe-daemon.log`` (rotating, 5 MB max, 3 backups).
    Optionally outputs to console when enabled in config.

    Args:
        config: Optional config to read logging configuration from.
    """
    from soothe.config import SootheConfig as _SootheConfig

    cfg = config or _SootheConfig()
    log_dir = Path(SOOTHE_HOME) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    file_level_name = cfg.logging.file.level.upper()
    console_level_name = cfg.logging.console.level.upper()

    if cfg.debug:
        file_level_name = "DEBUG"
        console_level_name = "DEBUG"

    file_level = getattr(logging, file_level_name, logging.INFO)
    console_level = getattr(logging, console_level_name, logging.WARNING)

    root_logger = logging.getLogger("soothe")
    root_logger.setLevel(min(file_level, console_level))

    log_file = cfg.logging.file.path or str(log_dir / "soothe-daemon.log")
    if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=cfg.logging.file.max_bytes,
            backupCount=cfg.logging.file.backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            ThreadFormatter(
                "%(asctime)s %(levelname)-8s %(thread_id)s %(name)s:%(lineno)d %(message)s"
            )
        )
        file_handler.setLevel(file_level)
        root_logger.addHandler(file_handler)

    if cfg.logging.console.enabled:
        stream = sys.stderr if cfg.logging.console.stream == "stderr" else sys.stdout
        if not any(
            isinstance(h, logging.StreamHandler) and h.stream == stream
            for h in root_logger.handlers
        ):
            console_handler = logging.StreamHandler(stream)
            console_handler.setFormatter(logging.Formatter(cfg.logging.console.format))
            console_handler.setLevel(console_level)
            root_logger.addHandler(console_handler)

    _suppress_noisy_third_party()
    _log_langsmith_status()


def _suppress_noisy_third_party() -> None:
    """Suppress noisy third-party loggers to WARNING level."""
    noisy = (
        "httpx",
        "httpcore",
        "openai",
        "anthropic",
        "langchain_core",
        "langgraph",
        "langsmith",
        "browser_use",
        "bubus",
        "cdp_use",
    )
    for name in noisy:
        logging.getLogger(name).setLevel(logging.WARNING)


def _log_langsmith_status() -> None:
    """Log LangSmith tracing status at startup."""
    logger = logging.getLogger("soothe.core.tracing")

    langsmith_tracing = os.getenv("LANGSMITH_TRACING", "").lower()
    langchain_tracing = os.getenv("LANGCHAIN_TRACING_V2", "").lower()
    langsmith_api_key = os.getenv("LANGSMITH_API_KEY")
    langchain_api_key = os.getenv("LANGCHAIN_API_KEY")
    langsmith_project = os.getenv("LANGSMITH_PROJECT")
    langchain_project = os.getenv("LANGCHAIN_PROJECT")

    tracing_enabled = langsmith_tracing == "true" or langchain_tracing == "true"
    has_api_key = bool(langsmith_api_key or langchain_api_key)

    if tracing_enabled and has_api_key:
        project_name = langsmith_project or langchain_project or "default"
        logger.info("LangSmith tracing enabled (project: %s)", project_name)
    elif tracing_enabled and not has_api_key:
        logger.warning("LangSmith tracing enabled but API key is missing")
    elif has_api_key and not tracing_enabled:
        logger.info("LangSmith API key found but tracing is disabled")
    else:
        logger.debug("LangSmith tracing not configured")

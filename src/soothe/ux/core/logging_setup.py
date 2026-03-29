"""Logging configuration for Soothe CLI."""

import contextvars
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from soothe.config import SOOTHE_HOME, SootheConfig

# Thread-local storage for thread_id
_current_thread_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_thread_id", default=None)


def set_thread_id(thread_id: str | None) -> None:
    """Set the current thread ID for logging.

    Args:
        thread_id: The thread ID to include in log messages.
    """
    _current_thread_id.set(thread_id)


def get_thread_id() -> str | None:
    """Get the current thread ID for logging.

    Returns:
        The current thread ID or None if not set.
    """
    return _current_thread_id.get()


class ThreadFormatter(logging.Formatter):
    """Custom formatter that includes thread_id in log messages."""

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with both Soothe and OS thread IDs.

        Args:
            record: The log record to format.

        Returns:
            The formatted log message string.
        """
        # Get Soothe conversation thread ID (optional)
        soothe_thread_id = get_thread_id()

        # Format both IDs: [os:id] [soothe:id]
        if soothe_thread_id:
            record.thread_id = f"[T:{soothe_thread_id}]"
        else:
            record.thread_id = ""

        return super().format(record)


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
        file_handler.setFormatter(ThreadFormatter("%(asctime)s %(thread_id)s %(levelname)-8s %(name)s %(message)s"))
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

    # Log LangSmith tracing status if enabled
    _log_langsmith_status()


def _log_langsmith_status() -> None:
    """Log LangSmith tracing status at startup."""
    logger = logging.getLogger("soothe.core.tracing")

    # Check for LangSmith environment variables
    langsmith_tracing = os.getenv("LANGSMITH_TRACING", "").lower()
    langchain_tracing = os.getenv("LANGCHAIN_TRACING_V2", "").lower()
    langsmith_api_key = os.getenv("LANGSMITH_API_KEY")
    langchain_api_key = os.getenv("LANGCHAIN_API_KEY")
    langsmith_project = os.getenv("LANGSMITH_PROJECT")
    langchain_project = os.getenv("LANGCHAIN_PROJECT")

    # Determine if tracing is enabled
    tracing_enabled = langsmith_tracing == "true" or langchain_tracing == "true"
    has_api_key = bool(langsmith_api_key or langchain_api_key)

    if tracing_enabled and has_api_key:
        project_name = langsmith_project or langchain_project or "default"
        logger.info(
            "LangSmith tracing enabled (project: %s)",
            project_name,
        )
    elif tracing_enabled and not has_api_key:
        logger.warning("LangSmith tracing enabled but API key is missing")
    elif has_api_key and not tracing_enabled:
        logger.info("LangSmith API key found but tracing is disabled")
    else:
        logger.debug("LangSmith tracing not configured")

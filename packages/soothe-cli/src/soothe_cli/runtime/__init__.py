"""Daemon event processing and display state for the CLI (source of truth for TUI).

Bridges daemon events/messages to in-memory state. ``soothe_cli.tui`` owns widgets
and layout only.
"""

from soothe_cli.config.loader import load_config
from soothe_cli.config.logging_setup import setup_logging
from soothe_cli.runtime.headless.processor import EventProcessor
from soothe_cli.runtime.headless.processor_state import ProcessorState

__all__ = [
    "EventProcessor",
    "ProcessorState",
    "load_config",
    "setup_logging",
]

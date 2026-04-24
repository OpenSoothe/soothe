"""Persistent shell session management and health tracking."""

from __future__ import annotations

import contextlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

logger = logging.getLogger(__name__)

ANSI_ESCAPE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

_shell_instances: dict[str, Any] = {}


@dataclass
class ShellHealthState:
    """Track shell health across command executions.

    Enables intelligent responsiveness testing that skips redundant checks
    when the shell is healthy, reducing log noise and improving performance.

    Attributes:
        last_command_success: Whether the previous command succeeded.
        last_command_timestamp: When the previous command executed.
        consecutive_failures: Number of consecutive command failures.
        last_test_timestamp: When the last responsiveness test was performed.
        shell_recovered: Whether the shell was recently recovered.
        first_command_executed: Whether any command has been executed yet.
        last_trouble_sign: Type of trouble detected in last command.
    """

    last_command_success: bool = True
    last_command_timestamp: datetime | None = None
    consecutive_failures: int = 0
    last_test_timestamp: datetime | None = None
    shell_recovered: bool = False
    first_command_executed: bool = False
    last_trouble_sign: Literal["timeout", "eof", "error", "unexpected_output", "none"] = "none"


_shell_health_states: dict[str, ShellHealthState] = {}


def cleanup_shell(shell_id: str = "default") -> None:
    """Clean up shell resources and health states.

    Args:
        shell_id: Shell identifier.
    """
    if shell_id in _shell_instances:
        with contextlib.suppress(Exception):
            _shell_instances[shell_id].close()
        del _shell_instances[shell_id]

    _shell_health_states.pop(shell_id, None)

"""Shell subprocess helpers for colorful piped output in the TUI."""

from __future__ import annotations

import os
from collections.abc import Mapping

# Git ignores FORCE_COLOR; wrap invocations so piped stdout still gets ANSI.
# PAGER=cat avoids blocking on interactive pagers when color is enabled.
_SHELL_COLOR_PREFIX = (
    "export FORCE_COLOR=1 CLICOLOR_FORCE=1 GIT_PAGER=cat PAGER=cat; "
    'git() { command git -c color.ui=always "$@"; }; '
)


def shell_subprocess_env(
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build environment for TUI ``!`` shell commands with color-friendly defaults.

    Args:
        base: Starting environment (defaults to ``os.environ``).

    Returns:
        Copy of ``base`` with ``TERM``, ``COLORTERM``, ``FORCE_COLOR``, and
        ``CLICOLOR_FORCE`` set for piped subprocess output.
    """
    env = dict(base if base is not None else os.environ)
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("COLORTERM", "truecolor")
    env["FORCE_COLOR"] = "1"
    env["CLICOLOR_FORCE"] = "1"
    return env


def wrap_shell_command_for_color(command: str) -> str:
    """Prefix a shell command so piped stdout still receives ANSI from common CLIs.

    Args:
        command: User shell command from TUI shell mode.

    Returns:
        Command prefixed with exports and a POSIX ``git`` wrapper.
    """
    trimmed = command.strip()
    if not trimmed:
        return trimmed
    return f"{_SHELL_COLOR_PREFIX}{command}"

"""Cross-platform shell command compatibility checks."""

from __future__ import annotations

import re
import sys

_GNU_TIMEOUT_CMD = re.compile(r"(?:^|[;&|]\s*)timeout\s+\d")


def macos_shell_compatibility_error(command: str) -> str | None:
    """Return an error message when *command* uses macOS-incompatible shell features.

    Args:
        command: Shell command string from run_command.

    Returns:
        Error text when the command should be rejected, else None.
    """
    if sys.platform != "darwin":
        return None

    if _GNU_TIMEOUT_CMD.search(command.strip()):
        return (
            "Error: GNU `timeout` is not available on macOS by default. "
            "Use the target tool's native timeout flags (e.g. `go test -timeout 300s`), "
            "call run_command without wrapping in `timeout`, or use run_background for long jobs."
        )

    return None


__all__ = ["macos_shell_compatibility_error"]

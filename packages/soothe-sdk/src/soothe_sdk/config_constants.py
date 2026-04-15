"""Shared config constants for SDK and CLI packages.

These constants are used by both daemon server and CLI client, so they're
provided in the SDK to avoid CLI importing daemon runtime.

This module is part of Phase 1 of IG-174: CLI import violations fix.
"""

import os
from pathlib import Path

# Default Soothe home directory
# Overridable via SOOTHE_HOME environment variable
SOOTHE_HOME: str = os.environ.get(
    "SOOTHE_HOME",
    str(Path.home() / ".soothe")
)

"""Default Soothe home directory. Overridable via ``SOOTHE_HOME`` env var."""

# Default execution timeout for shell commands (seconds)
DEFAULT_EXECUTE_TIMEOUT: int = 60

"""Default timeout for execute tool operations in seconds."""

__all__ = [
    "SOOTHE_HOME",
    "DEFAULT_EXECUTE_TIMEOUT",
]

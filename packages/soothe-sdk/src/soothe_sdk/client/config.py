"""Client configuration constants and types.

Merged from config_constants.py + config_types.py per RFC-610 (IG-185).

These constants and protocols are used by both daemon server and CLI client,
provided in the SDK to avoid CLI importing daemon runtime.
"""

import os
from pathlib import Path
from typing import Protocol

# === Constants (from config_constants.py) ===

# Default Soothe home directory
# Overridable via SOOTHE_HOME environment variable
SOOTHE_HOME: str = os.environ.get("SOOTHE_HOME", str(Path.home() / ".soothe"))

"""Default Soothe home directory. Overridable via `SOOTHE_HOME` env var."""

# Default execution timeout for shell commands (seconds)
DEFAULT_EXECUTE_TIMEOUT: int = 60

"""Default timeout for execute tool operations in seconds."""


# === Types (from config_types.py) ===


class WebSocketConfigProtocol(Protocol):
    """Protocol for WebSocket transport configuration."""

    host: str
    port: int


class DaemonTransportConfigProtocol(Protocol):
    """Protocol for daemon transport configuration."""

    websocket: WebSocketConfigProtocol


class DaemonConfigProtocol(Protocol):
    """Protocol for daemon configuration."""

    transports: DaemonTransportConfigProtocol


class CliConfigProtocol(Protocol):
    """Protocol for CLI configuration (minimal interface).

    This allows CLI to load just the websocket settings without
    requiring the full SootheConfig from the daemon package.
    """

    daemon: DaemonConfigProtocol


__all__ = [
    # Constants
    "SOOTHE_HOME",
    "DEFAULT_EXECUTE_TIMEOUT",
    # Types
    "CliConfigProtocol",
    "DaemonConfigProtocol",
    "DaemonTransportConfigProtocol",
    "WebSocketConfigProtocol",
]

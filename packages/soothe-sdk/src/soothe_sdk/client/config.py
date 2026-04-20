"""Client configuration constants and types.

Merged from config_constants.py + config_types.py per RFC-610 (IG-185).

These constants and protocols are used by both daemon server and CLI client,
provided in the SDK to avoid CLI importing daemon runtime.
"""

import os
import shutil
from pathlib import Path
from typing import Protocol

# === Constants (from config_constants.py) ===

# Default Soothe home directory
# Overridable via SOOTHE_HOME environment variable
SOOTHE_HOME: str = os.environ.get("SOOTHE_HOME", str(Path.home() / ".soothe"))

"""Default Soothe home directory. Overridable via `SOOTHE_HOME` env var."""

# Default Soothe data directory for runtime database/history files
# Overridable via SOOTHE_DATA_DIR environment variable
SOOTHE_DATA_DIR: str = os.environ.get("SOOTHE_DATA_DIR", str(Path(SOOTHE_HOME) / "data"))

"""Default Soothe data directory. Overridable via `SOOTHE_DATA_DIR` env var."""

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


def migrate_data_to_subdir() -> None:
    """Migrate runtime data files from $SOOTHE_HOME/ to $SOOTHE_HOME/data/.

    Moves: checkpoints.db, metadata.db, history.jsonl
    Idempotent: safe to call multiple times.
    Non-blocking: logs warnings on failure, does not raise.
    """
    data_dir = Path(SOOTHE_DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)

    for filename in ("checkpoints.db", "metadata.db", "history.jsonl"):
        old_path = Path(SOOTHE_HOME) / filename
        new_path = data_dir / filename
        if old_path.exists() and not new_path.exists():
            try:
                shutil.move(str(old_path), str(new_path))
            except Exception:
                pass

    # Also migrate SQLite WAL/SHM files for metadata.db and checkpoints.db
    for suffix in ("-wal", "-shm"):
        for db_name in ("metadata.db", "checkpoints.db"):
            old_path = Path(SOOTHE_HOME) / f"{db_name}{suffix}"
            new_path = data_dir / f"{db_name}{suffix}"
            if old_path.exists() and not new_path.exists():
                try:
                    shutil.move(str(old_path), str(new_path))
                except Exception:
                    pass


__all__ = [
    # Constants
    "SOOTHE_DATA_DIR",
    "SOOTHE_HOME",
    "DEFAULT_EXECUTE_TIMEOUT",
    "migrate_data_to_subdir",
    # Types
    "CliConfigProtocol",
    "DaemonConfigProtocol",
    "DaemonTransportConfigProtocol",
    "WebSocketConfigProtocol",
]

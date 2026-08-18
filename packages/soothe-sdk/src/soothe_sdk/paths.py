"""Shared filesystem path constants and light config protocols.

Canonical home for ``SOOTHE_HOME`` / ``SOOTHE_DATA_DIR`` and duck-typed config
protocols used by daemon, core, and clients.
"""

import os
from pathlib import Path
from typing import Protocol

# === Constants (from config_constants.py) ===

# Default Soothe home directory
# Overridable via SOOTHE_HOME environment variable
SOOTHE_HOME: Path = Path(os.environ.get("SOOTHE_HOME", str(Path.home() / ".soothe"))).expanduser()

"""Default Soothe home directory. Overridable via `SOOTHE_HOME` env var."""

# Default Soothe data directory for runtime database/history files
# Overridable via SOOTHE_DATA_DIR environment variable
SOOTHE_DATA_DIR: str = os.environ.get("SOOTHE_DATA_DIR", str(SOOTHE_HOME / "data"))

"""Default Soothe data directory. Overridable via `SOOTHE_DATA_DIR` env var."""

# SQLite purpose databases under databases/. Hard cut: no legacy flat paths.
SQLITE_DATABASES_SUBDIR: str = "databases"


def resolve_databases_dir() -> Path:
    """Return ``$SOOTHE_DATA_DIR/databases`` (creates nothing)."""
    return Path(SOOTHE_DATA_DIR) / SQLITE_DATABASES_SUBDIR


def resolve_sqlite_db_path(purpose: str) -> Path:
    """Return ``$SOOTHE_DATA_DIR/databases/{purpose}.db``.

    Args:
        purpose: Logical store name (e.g. ``checkpoints``, ``persist``).
    """
    name = purpose.strip().removesuffix(".db")
    return resolve_databases_dir() / f"{name}.db"


def resolve_checkpoints_db_path() -> Path:
    """StrangeLoop / loop checkpoints SQLite path."""
    return resolve_sqlite_db_path("checkpoints")


def resolve_context_db_path() -> Path:
    """Context Engine SQLite path."""
    return resolve_sqlite_db_path("context")


def resolve_display_db_path() -> Path:
    """Display card ledger SQLite path."""
    return resolve_sqlite_db_path("display")


def resolve_cron_db_path() -> Path:
    """Cron job store SQLite path."""
    return resolve_sqlite_db_path("cron")


def resolve_identity_db_path() -> Path:
    """Identity service SQLite path."""
    return resolve_sqlite_db_path("identity")


def resolve_metadata_db_path() -> Path:
    """ThreadInfo / durability metadata SQLite path."""
    return resolve_sqlite_db_path("metadata")


def resolve_persist_db_path() -> Path:
    """Persist KV SQLite path."""
    return resolve_sqlite_db_path("persist")


def resolve_vectors_db_path() -> Path:
    """Vector store (sqlite-vec) SQLite path."""
    return resolve_sqlite_db_path("vectors")


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
    "SOOTHE_DATA_DIR",
    "SOOTHE_HOME",
    "DEFAULT_EXECUTE_TIMEOUT",
    "SQLITE_DATABASES_SUBDIR",
    "resolve_checkpoints_db_path",
    "resolve_context_db_path",
    "resolve_cron_db_path",
    "resolve_databases_dir",
    "resolve_display_db_path",
    "resolve_identity_db_path",
    "resolve_metadata_db_path",
    "resolve_persist_db_path",
    "resolve_sqlite_db_path",
    "resolve_vectors_db_path",
    # Types
    "CliConfigProtocol",
    "DaemonConfigProtocol",
    "DaemonTransportConfigProtocol",
    "WebSocketConfigProtocol",
]

"""Resolved paths for unified runtime SQLite stores under ``SOOTHE_DATA_DIR``."""

from __future__ import annotations

from pathlib import Path


def resolve_metadata_db_path() -> Path:
    """Return the ThreadInfo metadata database path."""
    from soothe_sdk.client.config import SOOTHE_DATA_DIR

    return Path(SOOTHE_DATA_DIR) / "metadata.db"


def resolve_checkpoint_db_path() -> Path:
    """Return the shared LangGraph + StrangeLoop checkpoints database path."""
    from soothe_sdk.client.config import SOOTHE_DATA_DIR

    return Path(SOOTHE_DATA_DIR) / "soothe_checkpoints.db"


def resolve_context_engine_db_path() -> Path:
    """Return the shared ContextEngine SQLite database path."""
    from soothe_sdk.client.config import SOOTHE_DATA_DIR

    return Path(SOOTHE_DATA_DIR) / "context_engine.db"


def resolve_display_db_path() -> Path:
    """Return the shared display card ledger SQLite database path."""
    from soothe_sdk.client.config import SOOTHE_DATA_DIR

    return Path(SOOTHE_DATA_DIR) / "display.db"


__all__ = [
    "resolve_checkpoint_db_path",
    "resolve_context_engine_db_path",
    "resolve_display_db_path",
    "resolve_metadata_db_path",
]

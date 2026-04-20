"""Cleanse deprecated persistence files from ~/.soothe/.

Removes:
- sessions.db (empty, deprecated)
- soothe.db (replaced by metadata.db + checkpoints.db)
- threads/ directory (JsonPersistStore replaced by thread_history.jsonl)
"""

from __future__ import annotations

import shutil
from pathlib import Path

from soothe_sdk.client.config import SOOTHE_HOME


def cleanse_deprecated_files() -> None:
    """Remove deprecated files from ~/.soothe/.

    Removes:
    - sessions.db (empty, deprecated)
    - soothe.db (replaced by metadata.db + checkpoints.db)
    - threads/ directory (JsonPersistStore replaced by thread_history.jsonl)
    """
    soothe_db = Path(SOOTHE_HOME) / "soothe.db"
    sessions_db = Path(SOOTHE_HOME) / "sessions.db"
    threads_dir = Path(SOOTHE_HOME) / "threads"

    print("→ Cleansing deprecated persistence files...")

    # Remove sessions.db
    if sessions_db.exists():
        try:
            sessions_db.unlink()
            print("  ✓ Removed deprecated sessions.db")
        except Exception as exc:
            print(f"  ⚠ Failed to remove sessions.db: {exc}")

    # Remove soothe.db (replaced by split databases)
    if soothe_db.exists():
        try:
            soothe_db.unlink()
            print("  ✓ Removed deprecated soothe.db")
        except Exception as exc:
            print(f"  ⚠ Failed to remove soothe.db: {exc}")

    # Remove threads/ directory (JsonPersistStore replaced by thread_history.jsonl)
    if threads_dir.exists():
        try:
            shutil.rmtree(threads_dir)
            print("  ✓ Removed deprecated threads/ directory")
        except Exception as exc:
            print(f"  ⚠ Failed to remove threads/ directory: {exc}")

    print("✓ Deprecated file cleansing completed")


if __name__ == "__main__":
    cleanse_deprecated_files()

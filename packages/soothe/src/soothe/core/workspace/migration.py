"""One-time migration of workspace directories (RFC-621 directory separation).

Moves persisted workspace directories from ``$SOOTHE_HOME/workspaces/`` to
``$SOOTHE_HOME/data/workspaces/``, freeing ``$SOOTHE_HOME/workspaces/`` to
serve as the Docker volume mount target for client paths.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def migrate_workspaces_to_data_dir() -> None:
    """Migrate persisted workspaces from ``workspaces/`` to ``data/workspaces/``.

    Moves ``anonymous/`` and user directories (containing ``ws_*`` entries)
    from ``$SOOTHE_HOME/workspaces/`` to ``$SOOTHE_HOME/data/workspaces/``.

    Skips migration when:
    - ``$SOOTHE_HOME/workspaces/`` does not exist
    - ``$SOOTHE_HOME/data/workspaces/`` already exists (migration already done)
    - ``$SOOTHE_HOME/workspaces/`` appears to be a Docker mount (contains
      files/dirs not matching persisted workspace patterns)
    """
    from soothe.config import SOOTHE_HOME

    home = Path(SOOTHE_HOME)
    old_dir = home / "workspaces"
    new_dir = home / "data" / "workspaces"

    if not old_dir.exists():
        return

    if new_dir.exists():
        return  # migration already done

    # Check if old_dir is a Docker mount — it would contain host content
    # that doesn't match workspace patterns (ws_* subdirs or anonymous/)
    try:
        entries = list(old_dir.iterdir())
    except OSError:
        return

    has_non_workspace = False
    workspace_dirs: list[Path] = []
    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name == "anonymous" or _is_user_workspace_dir(entry):
            workspace_dirs.append(entry)
        else:
            has_non_workspace = True

    if has_non_workspace:
        logger.info(
            "workspaces/ contains non-workspace content (likely Docker mount); "
            "skipping migration of %d persisted dirs",
            len(workspace_dirs),
        )
        # Still move identifiable workspace dirs if they coexist with mount content
        if not workspace_dirs:
            return

    if not workspace_dirs:
        return

    new_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for src in workspace_dirs:
        dest = new_dir / src.name
        if dest.exists():
            logger.debug("Skipping %s — already exists at %s", src.name, dest)
            continue
        try:
            shutil.move(str(src), str(dest))
            moved += 1
            logger.info("Migrated workspace directory: %s -> %s", src, dest)
        except OSError as e:
            logger.warning("Failed to migrate %s: %s", src, e)

    if moved:
        logger.info("Migrated %d workspace directories to %s", moved, new_dir)


def _is_user_workspace_dir(path: Path) -> bool:
    """Check if a directory is a user workspace dir (contains ws_* entries)."""
    try:
        return any(child.is_dir() and child.name.startswith("ws_") for child in path.iterdir())
    except OSError:
        return False

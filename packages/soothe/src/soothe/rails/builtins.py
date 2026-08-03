"""Rail discovery helpers for built-in and user/project rails.

Precedence (low → high, last wins on duplicate ``id``):

1. Package ``soothe/rails/builtin_rails/``
2. ``$SOOTHE_HOME/rails/`` (typically ``~/.soothe/rails/``)
3. ``<workspace>/.soothe/rails/`` when a workspace is provided
"""

from __future__ import annotations

from pathlib import Path

_BUILTIN_RAILS_DIR_NAME = "builtin_rails"


def get_builtin_rails_dir() -> Path:
    """Return the package-bundled ``builtin_rails/`` directory."""
    return Path(__file__).resolve().parent / _BUILTIN_RAILS_DIR_NAME


def get_rails_paths(workspace: str | None = None) -> list[Path]:
    """Return rail directories in precedence order (low → high).

    Missing directories are omitted. Drafts under ``drafts/`` are not roots;
    only the parent ``rails/`` directories are returned for catalog loading.

    Args:
        workspace: Optional workspace directory for project-local rails.

    Returns:
        ``[builtin_rails/, $SOOTHE_HOME/rails/, <workspace>/.soothe/rails/]``
        (only existing dirs).
    """
    from soothe.config import SOOTHE_HOME

    candidates: list[Path] = [
        get_builtin_rails_dir(),
        Path(SOOTHE_HOME).expanduser() / "rails",
    ]
    if workspace:
        candidates.append(Path(workspace).expanduser().resolve() / ".soothe" / "rails")

    return [path for path in candidates if path.is_dir()]

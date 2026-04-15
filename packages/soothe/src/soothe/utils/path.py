"""Path expansion and resolution utilities."""

from __future__ import annotations

import os
from pathlib import Path


def expand_path(path: str | Path) -> Path:
    """Expand and resolve a filesystem path.

    Handles:
    - Home directory expansion (~ and ~user)
    - Environment variable expansion ($VAR and ${VAR})
    - Relative path resolution to absolute path
    - Symlink resolution

    Args:
        path: Path string or Path object to expand.

    Returns:
        Expanded and resolved absolute Path.

    Examples:
        >>> expand_path("~/.soothe")
        PosixPath('/Users/xiamingchen/.soothe')

        >>> expand_path("${HOME}/project")
        PosixPath('/Users/xiamingchen/project')

        >>> expand_path("./relative")
        PosixPath('/current/working/dir/relative')
    """
    # Convert to string if Path object
    path_str = str(path)

    # Expand environment variables first (handles $HOME, ${HOME}, etc.)
    expanded = os.path.expandvars(path_str)

    # Expand home directory (~ and ~user) and convert to Path
    expanded_path = Path(expanded).expanduser()

    # Resolve to absolute path
    return expanded_path.resolve()

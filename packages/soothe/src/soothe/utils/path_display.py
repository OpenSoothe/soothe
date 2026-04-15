"""Unified path display conversion for deepagents workspace paths.

This module handles the conversion between deepagents' workspace-rooted paths
(where `/` represents the workspace root) and actual OS paths for display.

The deepagents convention:
- `/` = workspace root (not filesystem root)
- `/foo/bar` = workspace_root/foo/bar

This module provides utilities to convert these paths to user-friendly display
format while being future-proof for supporting file access outside the workspace.
"""

from __future__ import annotations

from pathlib import Path

# Cached workspace root (set during runner/CLI initialization)
_workspace_root: str | None = None


def set_workspace_root(path: str | None) -> None:
    """Set the workspace root for path conversion.

    Should be called during runner or CLI initialization to enable
    proper path display conversion.

    Args:
        path: Absolute path to the workspace root, or None to clear.
    """
    global _workspace_root
    _workspace_root = path


def get_workspace_root() -> str | None:
    """Get the currently configured workspace root.

    Returns:
        The workspace root path, or None if not set.
    """
    return _workspace_root


def convert_display_path(path: str) -> str:
    """Convert deepagents workspace path to OS display path.

    Deepagents convention:
    - `/` = workspace root
    - `/foo/bar` = workspace_root/foo/bar

    Future-proof for absolute paths outside workspace:
    - Paths matching real OS patterns (e.g., /Users/..., /home/...) are passed through

    Args:
        path: Path from deepagents tool call

    Returns:
        Converted path for display (OS absolute or original if no conversion needed)

    Examples:
        >>> set_workspace_root("/Users/dev/myproject")
        >>> convert_display_path("/")
        '/Users/dev/myproject'
        >>> convert_display_path("/src/main.py")
        '/Users/dev/myproject/src/main.py'
        >>> convert_display_path("/Users/dev/other/file.txt")
        '/Users/dev/other/file.txt'  # Real OS path, passed through
    """
    if not path:
        return path

    # Detect real OS absolute paths (not workspace-relative)
    # These are actual filesystem paths that should be passed through unchanged.
    # macOS: /Users/..., /Applications/..., /System/..., /Library/..., /Volumes/...
    # Linux: /home/..., /usr/..., /etc/..., /var/..., /opt/...
    # Common: /tmp/..., /private/...
    os_root_prefixes = (
        # macOS
        "/Users/",
        "/Applications/",
        "/System/",
        "/Library/",
        "/Volumes/",
        "/private/",
        # Linux
        "/home/",
        "/usr/",
        "/etc/",
        "/var/",
        "/opt/",
        "/bin/",
        "/sbin/",
        "/lib/",
        "/lib64/",
        "/root/",
        "/srv/",
        "/mnt/",
        "/media/",
        "/proc/",
        "/sys/",
        "/dev/",
        "/run/",
        "/snap/",
        # Common
        "/tmp/",  # noqa: S108
    )
    if any(path.startswith(p) for p in os_root_prefixes):
        return path  # Real OS path, pass through

    # Workspace-rooted path: convert to OS absolute
    if _workspace_root and path.startswith("/"):
        if path == "/":
            return _workspace_root
        # Join workspace root with the relative path (strip leading /)
        return str(Path(_workspace_root) / path.lstrip("/"))

    return path


def is_path_argument(arg_key: str) -> bool:
    """Check if an argument key typically contains a path value.

    Used to determine which tool arguments should have path conversion applied.

    Args:
        arg_key: The argument key name (e.g., "path", "file_path", "directory")

    Returns:
        True if this argument likely contains a path value.
    """
    path_arg_keys = {
        "path",
        "file_path",
        "filepath",
        "file",
        "directory",
        "dir",
        "folder",
        "image_path",
        "video_path",
        "audio_path",
        "source_path",
        "dest_path",
        "target_path",
        "base_path",
        "root_path",
        "working_directory",
        "workdir",
        "cwd",
    }
    return arg_key.lower() in path_arg_keys


def abbreviate_path(path: str, max_length: int = 40) -> str:
    """Abbreviate a long path for display while keeping key context.

    Format: /prefix/some/.../file.md
    - Keeps the first 2 path segments (or 1 for very short paths)
    - Shows "..." for omitted middle segments
    - Always shows the final filename

    Args:
        path: The path to abbreviate (should be an absolute or relative path string).
        max_length: Maximum desired length (not strictly enforced for very long filenames).

    Returns:
        Abbreviated path string.

    Examples:
        >>> abbreviate_path("/Users/dev/project/src/components/ui/Button.tsx")
        '/Users/dev/.../Button.tsx'
        >>> abbreviate_path("/short/path/file.md")
        '/short/path/file.md'
        >>> abbreviate_path("file.md")
        'file.md'
    """
    if not path or len(path) <= max_length:
        return path

    # Split into parts
    parts = Path(path).parts
    if len(parts) <= 3:  # noqa: PLR2004
        # Path is short enough, no need to abbreviate
        return path

    # Determine how many leading segments to keep
    # For paths like /Users/dev/long/path/.../file.md, keep /Users/dev
    # For paths like /a/b/c/d/e/file.md, keep /a/b
    if parts[0] == "/":
        # Unix absolute path: parts[0] is "/", so parts[1] is first segment
        if len(parts) >= 6:  # noqa: PLR2004
            # Keep "/" + first segment + "..." + last two segments
            # e.g., /Users/.../Workspace/Soothe
            abbreviated = "/" + parts[1] + "/.../" + parts[-2] + "/" + parts[-1]
        elif len(parts) >= 5:  # noqa: PLR2004
            # Not enough for 2 tail segments, show first two + "..." + last
            # e.g., /Users/xiamingchen/.../Soothe
            abbreviated = "/" + parts[1] + "/" + parts[2] + "/.../" + parts[-1]
        else:
            # Not long enough to abbreviate meaningfully
            return path
    elif parts[0].endswith(":\\") or (len(parts[0]) == 2 and parts[0][1] == ":"):  # noqa: PLR2004
        # Windows path like "C:\\" - keep drive + first dir + ... + filename
        if len(parts) >= 6:  # noqa: PLR2004
            abbreviated = parts[0] + parts[1] + "\\...\\" + parts[-2] + "\\" + parts[-1]
        elif len(parts) >= 5:  # noqa: PLR2004
            abbreviated = parts[0] + parts[1] + "\\" + parts[2] + "\\...\\" + parts[-1]
        else:
            return path
    # Relative path: keep first segment + ... + filename
    elif len(parts) >= 5:  # noqa: PLR2004
        abbreviated = parts[0] + "/.../" + parts[-2] + "/" + parts[-1]
    elif len(parts) >= 4:  # noqa: PLR2004
        abbreviated = parts[0] + "/" + parts[1] + "/.../" + parts[-1]
    else:
        return path

    return abbreviated


def convert_and_abbreviate_path(path: str, max_length: int = 30) -> str:
    """Convert and abbreviate a path for display.

    Combines convert_display_path() and abbreviate_path() for convenience.

    Args:
        path: Path from deepagents tool call (may be workspace-relative).
        max_length: Maximum desired display length.

    Returns:
        Converted and abbreviated path for display.
    """
    converted = convert_display_path(path)
    return abbreviate_path(converted, max_length)

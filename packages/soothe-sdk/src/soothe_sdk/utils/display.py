"""Display utilities for CLI and daemon formatting.

Utility functions for formatting paths, errors, and other display-related
operations used by both daemon and CLI.

Part of RFC-610 SDK module structure refactoring (IG-185).
"""

from pathlib import Path


def format_cli_error(error: Exception) -> str:
    """Format exception for CLI display.

    Creates user-friendly error message for terminal display.

    Args:
        error: Exception to format.

    Returns:
        Formatted error string suitable for CLI output.
    """
    error_type = type(error).__name__
    error_msg = str(error)

    # Truncate very long error messages
    if len(error_msg) > 500:
        error_msg = error_msg[:500] + "..."

    return f"{error_type}: {error_msg}"


def log_preview(text: str, max_length: int = 100) -> str:
    """Create preview of text for logging.

    Args:
        text: Full text to preview.
        max_length: Maximum preview length.

    Returns:
        Preview string, truncated if necessary.
    """
    if len(text) <= max_length:
        return text

    return text[: max_length - 3] + "..."


def convert_and_abbreviate_path(path: str, base_dir: str | None = None) -> str:
    """Convert and abbreviate path for display.

    Makes paths more readable by abbreviating home directory and base dir.

    Args:
        path: Full path to abbreviate.
        base_dir: Optional base directory to abbreviate.

    Returns:
        Abbreviated path suitable for display.
    """
    if not path:
        return path

    # Convert to Path object
    p = Path(path)

    # Try to abbreviate relative to home
    home = Path.home()
    try:
        if p.is_absolute() and str(p).startswith(str(home)):
            abbrev = "~" + str(p.relative_to(home))
            return abbrev
    except ValueError:
        pass

    # Try to abbreviate relative to base_dir
    if base_dir:
        try:
            base = Path(base_dir)
            if str(p).startswith(str(base)):
                abbrev = "." + str(p.relative_to(base))
                return abbrev
        except ValueError:
            pass

    # Return original if no abbreviation possible
    return str(p)


# Re-export get_tool_display_name from tool_meta (canonical registry)
from soothe_sdk.utils.tool_meta import get_tool_display_name  # noqa: E402, F401, I001 -- re-export after code

__all__ = [
    "format_cli_error",
    "log_preview",
    "convert_and_abbreviate_path",
    "get_tool_display_name",
]


__all__ = [
    "format_cli_error",
    "log_preview",
    "convert_and_abbreviate_path",
    "get_tool_display_name",
]

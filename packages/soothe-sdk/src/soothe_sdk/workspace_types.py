"""Security-related types and constants."""

from typing import Final

# System directories that should never be used as workspace
# Note: /tmp is intentionally included here to prevent using it as a workspace
INVALID_WORKSPACE_DIRS: Final[frozenset[str]] = frozenset(
    {
        "/",
        "/Users",
        "/home",
        "/System",
        "/Library",
        "/Applications",
        "/usr",
        "/var",
        "/tmp",  # noqa: S108
        "/etc",
    }
)


__all__ = ["INVALID_WORKSPACE_DIRS"]

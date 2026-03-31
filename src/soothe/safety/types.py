"""Security-related types and constants."""

from typing import Final

# System directories that should never be used as workspace
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
        "/tmp",
        "/etc",
    }
)

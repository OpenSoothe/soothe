"""Update check functionality (stub implementation from deepagents-cli migration).

This module provides update checking and version notification functionality.
Full implementation should integrate with PyPI/update checking system.
"""

import logging

logger = logging.getLogger(__name__)


def is_update_check_enabled() -> bool:
    """Check if update checking is enabled in user preferences.

    Stub implementation - always returns False.
    Full implementation should check SootheConfig user preferences.

    Returns:
        True if update checking is enabled.
    """
    logger.debug("Update check enabled (stub): returning False")
    return False


async def perform_upgrade() -> None:
    """Perform package upgrade to latest version.

    Stub implementation - logs warning.
    Full implementation should use pip/uv to upgrade package.
    """
    logger.warning("Upgrade functionality not yet implemented (stub)")
    # Stub - no actual upgrade
    pass


def should_show_whats_new() -> bool:
    """Check if 'What's New' notification should be shown.

    Stub implementation - always returns False.
    Full implementation should check version changelog and user preferences.

    Returns:
        True if 'What's New' should be displayed.
    """
    logger.debug("Should show what's new (stub): returning False")
    return False


def mark_version_seen() -> None:
    """Mark current version as seen in user preferences.

    Stub implementation - no action.
    Full implementation should persist to SootheConfig user preferences.
    """
    logger.debug("Mark version seen (stub): no action")
    # Stub - no persistence
    pass


def get_latest_version() -> str | None:
    """Get latest available version from PyPI.

    Stub implementation - returns None.
    Full implementation should query PyPI API.

    Returns:
        Latest version string, or None if unable to check.
    """
    logger.debug("Get latest version (stub): returning None")
    return None


def get_current_version() -> str:
    """Get current installed version.

    Returns:
        Current version string.
    """
    from importlib.metadata import version

    try:
        return version("soothe")
    except Exception:
        logger.debug("Could not get current version")
        return "unknown"

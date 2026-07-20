"""Browser runtime utilities - local implementations for community plugins.

These are simplified versions of soothe.utils.runtime functions,
allowing browser_use plugin to run without soothe daemon dependency.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from soothe_nano.config import SOOTHE_HOME

logger = logging.getLogger(__name__)


def _browser_runtime_base() -> Path:
    """Return browser runtime base directory (resolved at call time for testability)."""
    return SOOTHE_HOME / "agents" / "browser"


def get_browser_runtime_dir() -> Path:
    """Get browser runtime directory.

    Returns:
        Path to browser runtime directory.
    """
    base = _browser_runtime_base()
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_browser_downloads_dir() -> Path:
    """Get browser downloads directory.

    Returns:
        Path to browser downloads directory.
    """
    downloads = get_browser_runtime_dir() / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    return downloads


def get_browser_extensions_dir() -> Path:
    """Get browser extensions directory.

    Returns:
        Path to browser extensions directory.
    """
    extensions = get_browser_runtime_dir() / "extensions"
    extensions.mkdir(parents=True, exist_ok=True)
    return extensions


def get_browser_user_data_dir(profile_name: str | None = None) -> Path:
    """Get browser user data directory.

    Args:
        profile_name: Optional profile name suffix.

    Returns:
        Path to browser user data directory.
    """
    if profile_name:
        user_data = get_browser_runtime_dir() / "profiles" / profile_name
    else:
        user_data = get_browser_runtime_dir() / "profiles" / "default"
    user_data.mkdir(parents=True, exist_ok=True)
    return user_data


def cleanup_browser_temp_files() -> int:
    """Clean up browser temporary files.

    Returns:
        Number of files/directories cleaned up.
    """
    cleaned = 0
    runtime_dir = get_browser_runtime_dir()

    # Clean downloads older than 24h
    downloads = runtime_dir / "downloads"
    if downloads.exists():
        for f in downloads.iterdir():
            try:
                # Simple cleanup - remove all
                if f.is_file():
                    f.unlink()
                    cleaned += 1
                elif f.is_dir():
                    shutil.rmtree(f)
                    cleaned += 1
            except Exception:
                logger.debug("Failed to clean %s", f)

    return cleaned


def cleanup_stale_chrome(user_data_dir: str | Path) -> int:
    """Clean up stale Chrome processes using the user data directory.

    Args:
        user_data_dir: Chrome user data directory path.

    Returns:
        Number of processes killed.
    """
    from soothe_nano.utils.browser_cdp import cleanup_stale_chrome as _cleanup_stale_chrome

    return _cleanup_stale_chrome(str(user_data_dir))


__all__ = [
    "get_browser_runtime_dir",
    "get_browser_downloads_dir",
    "get_browser_extensions_dir",
    "get_browser_user_data_dir",
    "cleanup_browser_temp_files",
    "cleanup_stale_chrome",
]

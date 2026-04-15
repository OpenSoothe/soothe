"""Runtime directory management for Soothe subagents."""

from __future__ import annotations

import contextvars
import shutil
from pathlib import Path

from soothe.config import SOOTHE_HOME

# Minimum length for UUID-like suffix in directory names
_UUID_SUFFIX_MIN_LENGTH = 8

current_run_dir: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "current_run_dir", default=None
)


def get_subagent_runtime_dir(subagent_name: str) -> Path:
    """Get runtime directory for a subagent under SOOTHE_HOME/agents/<name>/.

    Args:
        subagent_name: Lowercase subagent name (e.g., "browser", "planner").

    Returns:
        Path to subagent runtime directory.
    """
    runtime_dir = Path(SOOTHE_HOME) / "agents" / subagent_name.lower()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def get_browser_runtime_dir() -> Path:
    """Get browser runtime directory under SOOTHE_HOME/agents/browser/."""
    return get_subagent_runtime_dir("browser")


def get_browser_downloads_dir() -> Path:
    """Get browser downloads directory."""
    downloads_dir = get_browser_runtime_dir() / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    return downloads_dir


def get_browser_user_data_dir(profile_name: str = "default") -> Path:
    """Get browser profile directory.

    Args:
        profile_name: Browser profile name (default: "default").

    Returns:
        Path to browser profile directory.
    """
    user_data_dir = get_browser_runtime_dir() / "profiles" / profile_name
    user_data_dir.mkdir(parents=True, exist_ok=True)
    return user_data_dir


def get_browser_extensions_dir() -> Path:
    """Get browser extensions directory."""
    extensions_dir = get_browser_runtime_dir() / "extensions"
    extensions_dir.mkdir(parents=True, exist_ok=True)
    return extensions_dir


def cleanup_browser_temp_files(session_id: str | None = None) -> None:
    """Clean up temporary browser files from completed sessions.

    Args:
        session_id: Optional specific session ID to clean up.
            If None, cleans up old temporary files.
    """
    downloads_dir = get_browser_downloads_dir()
    runtime_dir = get_browser_runtime_dir()

    # Remove temp user-data-dir directories
    # These are created with UUID suffixes by browser-use
    if session_id:
        # Clean up specific session files
        for subdir in downloads_dir.iterdir():
            if session_id in subdir.name:
                shutil.rmtree(subdir, ignore_errors=True)
    else:
        # Clean up old temp directories (keep profiles and extensions)
        for parent in [downloads_dir, runtime_dir / "tmp"]:
            if parent.exists():
                for subdir in parent.iterdir():
                    # Check if it's a temp directory (is a directory with UUID-like suffix)
                    is_temp_dir = (
                        subdir.is_dir()
                        and "-" in subdir.name
                        and len(subdir.name.split("-")[-1]) >= _UUID_SUFFIX_MIN_LENGTH
                    )
                    if is_temp_dir:
                        shutil.rmtree(subdir, ignore_errors=True)

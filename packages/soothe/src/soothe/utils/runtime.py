"""Runtime directory management for Soothe subagents.

IG-405: Uses virtual home when virtual_mode=True for workspace isolation.
"""

from __future__ import annotations

import contextvars
import shutil
from pathlib import Path

# Minimum length for UUID-like suffix in directory names
_UUID_SUFFIX_MIN_LENGTH = 8

current_run_dir: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "current_run_dir", default=None
)


def _get_virtual_home() -> Path:
    """Get virtual home or host SOOTHE_HOME based on current context (IG-405).

    Returns:
        Path to virtual /.soothe when virtual_mode=True, else host SOOTHE_HOME.
    """
    from soothe.foundation.workspace import get_virtual_home

    return get_virtual_home()


def _ensure_dir_with_backend(path: Path) -> Path:
    """Ensure directory exists, using backend when virtual mode (IG-405).

    Args:
        path: Path to directory to create.

    Returns:
        The created/existing directory path.
    """
    from soothe.foundation.workspace import get_virtual_home_relative_path, get_virtual_mode

    virtual_mode = get_virtual_mode()
    if virtual_mode:
        # In virtual mode, use backend for directory creation
        from soothe.foundation.workspace import FrameworkFilesystem

        backend = FrameworkFilesystem.get()
        if backend is not None:
            virtual_path = get_virtual_home_relative_path(path)
            if virtual_path is not None:
                try:
                    backend.mkdir(virtual_path, recursive=True)
                except Exception:
                    # Fallback to direct mkdir if backend fails
                    path.mkdir(parents=True, exist_ok=True)
    # Always ensure directory exists (fallback or non-virtual mode)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_subagent_runtime_dir(subagent_name: str) -> Path:
    """Get runtime directory for a subagent under virtual home or SOOTHE_HOME.

    Args:
        subagent_name: Lowercase subagent name (e.g., "browser", "planner").

    Returns:
        Path to subagent runtime directory.
    """
    runtime_dir = _get_virtual_home() / "agents" / subagent_name.lower()
    return _ensure_dir_with_backend(runtime_dir)


def get_browser_runtime_dir() -> Path:
    """Get browser runtime directory under virtual home or SOOTHE_HOME."""
    return get_subagent_runtime_dir("browser")


def get_browser_downloads_dir() -> Path:
    """Get browser downloads directory."""
    downloads_dir = get_browser_runtime_dir() / "downloads"
    return _ensure_dir_with_backend(downloads_dir)


def get_browser_user_data_dir(profile_name: str = "default") -> Path:
    """Get browser profile directory.

    Args:
        profile_name: Browser profile name (default: "default").

    Returns:
        Path to browser profile directory.
    """
    user_data_dir = get_browser_runtime_dir() / "profiles" / profile_name
    return _ensure_dir_with_backend(user_data_dir)


def get_browser_extensions_dir() -> Path:
    """Get browser extensions directory."""
    extensions_dir = get_browser_runtime_dir() / "extensions"
    return _ensure_dir_with_backend(extensions_dir)


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

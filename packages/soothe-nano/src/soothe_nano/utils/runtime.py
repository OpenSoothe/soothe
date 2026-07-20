"""Runtime directory management for Soothe subagents.

IG-405: Uses virtual home when virtual_mode=True for workspace isolation.
"""

from __future__ import annotations

import contextvars
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeAlias

# Minimum length for UUID-like suffix in directory names
_UUID_SUFFIX_MIN_LENGTH = 8

current_run_dir: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "current_run_dir", default=None
)
_StreamModelToken: TypeAlias = contextvars.Token[tuple[str, dict[str, Any]] | None]
_StreamProfileToken: TypeAlias = contextvars.Token[str | None]

_stream_model_override: contextvars.ContextVar[tuple[str, dict[str, Any]] | None] = (
    contextvars.ContextVar(
        "soothe_stream_model_override",
        default=None,
    )
)
_stream_router_profile: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "soothe_stream_router_profile",
    default=None,
)


def _get_virtual_home() -> Path:
    """Get virtual home or host SOOTHE_HOME based on current context (IG-405).

    Returns:
        Path to virtual /.soothe when virtual_mode=True, else host SOOTHE_HOME.
    """
    from soothe_nano.workspace import get_virtual_home

    return get_virtual_home()


def attach_stream_model_override(
    spec: str | None,
    params: dict[str, Any] | None,
) -> _StreamModelToken:
    """Attach model override for the current asyncio task."""
    if not spec:
        return _stream_model_override.set(None)
    return _stream_model_override.set((spec.strip(), dict(params or {})))


def reset_stream_model_override(token: _StreamModelToken) -> None:
    """Restore previous model override for this task."""
    _stream_model_override.reset(token)


def get_stream_model_override() -> tuple[str, dict[str, Any]] | None:
    """Return ``(spec, params)`` when a stream model override is active."""
    return _stream_model_override.get()


def attach_stream_router_profile(name: str | None) -> _StreamProfileToken:
    """Attach a router profile for the current asyncio task."""
    if not name or not str(name).strip():
        return _stream_router_profile.set(None)
    return _stream_router_profile.set(str(name).strip())


def reset_stream_router_profile(token: _StreamProfileToken) -> None:
    """Restore the previous stream router profile."""
    _stream_router_profile.reset(token)


def get_stream_router_profile() -> str | None:
    """Return active stream router profile name, if any."""
    return _stream_router_profile.get()


@contextmanager
def stream_turn_overrides(
    *,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    router_profile: str | None = None,
) -> Iterator[None]:
    """Attach per-turn stream model/profile overrides; always reset on exit."""
    model_token = attach_stream_model_override(model, model_params)
    profile_token = attach_stream_router_profile(router_profile)
    try:
        yield
    finally:
        reset_stream_router_profile(profile_token)
        reset_stream_model_override(model_token)


def _ensure_dir_with_backend(path: Path) -> Path:
    """Ensure directory exists, using backend when virtual mode (IG-405).

    Args:
        path: Path to directory to create.

    Returns:
        The created/existing directory path.
    """
    from soothe_nano.workspace import get_virtual_home_relative_path, get_virtual_mode

    virtual_mode = get_virtual_mode()
    if virtual_mode:
        # In virtual mode, use backend for directory creation
        from soothe_nano.workspace import FrameworkFilesystem

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


def get_workspace_subagent_output_dir(subagent_name: str) -> Path:
    """Get subagent output directory, preferring ``<workspace>/.soothe/agents/<name>/``.

    Falls back to ``SOOTHE_HOME/agents/<name>/`` when no workspace is active.
    """
    from soothe_nano.workspace.workspace_runtime import get_workspace_context

    ctx = get_workspace_context()
    if ctx.workspace is not None:
        target = ctx.workspace / ".soothe" / "agents" / subagent_name.lower()
    else:
        target = _get_virtual_home() / "agents" / subagent_name.lower()
    return _ensure_dir_with_backend(target)


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

"""Backend-aware file operations for internal toolkits (IG-405).

Provides helper functions for file operations under SOOTHE_HOME (virtual home).

Architecture note:
- Workspace-relative files: Use resolve_toolkit_local_path → direct Path ops (already works)
- SOOTHE_HOME-relative files (cache, logs, etc.): Use this module's backend ops

When virtual_mode=True, SOOTHE_HOME becomes /.soothe (virtual absolute under workspace).
Operations under virtual home must route through the backend for proper isolation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _should_use_backend(config: Any) -> bool:
    """Check if we should use backend for file operations.

    Args:
        config: SootheConfig or None.

    Returns:
        True if virtual mode is enabled, False otherwise.
    """
    if config is None:
        return False

    from soothe_nano.workspace import get_virtual_mode

    return get_virtual_mode()


def _get_backend() -> Any:
    """Get the current filesystem backend.

    Returns:
        FilesystemBackend or None if not available.
    """
    from soothe_nano.workspace import FrameworkFilesystem

    return FrameworkFilesystem.get()


def _to_virtual_home_path(host_path: Path) -> str | None:
    """Convert host path under virtual home to virtual path for backend operations.

    Note: This only works for paths under /.soothe (virtual home), not workspace-relative paths.

    Args:
        host_path: Host-absolute path under virtual home.

    Returns:
        Virtual path string (e.g., "/.soothe/data/...") or None if not under virtual home.
    """
    from soothe_nano.workspace import get_virtual_home_relative_path

    return get_virtual_home_relative_path(host_path)


def backend_read_file(path: Path, config: Any = None) -> str:
    """Read file content, using backend when virtual mode.

    Args:
        path: Resolved host path to file.
        config: SootheConfig for virtual mode detection.

    Returns:
        File content as string.

    Raises:
        OSError: If file cannot be read.
    """
    if _should_use_backend(config):
        backend = _get_backend()
        virtual_path = _to_virtual_home_path(path)
        if backend is not None and virtual_path is not None:
            try:
                result = backend.read(virtual_path)
                if isinstance(result, str):
                    return result
                if getattr(result, "error", None):
                    raise OSError(result.error)
                file_data = getattr(result, "file_data", None)
                if file_data is not None:
                    return str(file_data.get("content", ""))
                return ""
            except Exception as e:
                logger.debug("Backend read failed for %s, falling back: %s", virtual_path, e)

    # Fallback or non-virtual mode
    return path.read_text(encoding="utf-8", errors="ignore")


def backend_write_file(path: Path, content: str, config: Any = None) -> None:
    """Write file content, using backend when virtual mode.

    Args:
        path: Resolved host path to file.
        content: Content to write.
        config: SootheConfig for virtual mode detection.

    Raises:
        OSError: If file cannot be written.
    """
    if _should_use_backend(config):
        backend = _get_backend()
        virtual_path = _to_virtual_home_path(path)
        if backend is not None and virtual_path is not None:
            try:
                backend.write(virtual_path, content)
                return
            except Exception as e:
                logger.debug("Backend write failed for %s, falling back: %s", virtual_path, e)

    # Fallback or non-virtual mode
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def backend_mkdir(path: Path, config: Any = None) -> Path:
    """Create directory, using backend when virtual mode.

    Args:
        path: Resolved host path to directory.
        config: SootheConfig for virtual mode detection.

    Returns:
        The created/existing directory path.
    """
    if _should_use_backend(config):
        backend = _get_backend()
        virtual_path = _to_virtual_home_path(path)
        if backend is not None and virtual_path is not None:
            try:
                backend.mkdir(virtual_path, recursive=True)
            except Exception as e:
                logger.debug("Backend mkdir failed for %s, falling back: %s", virtual_path, e)

    # Always ensure directory exists
    path.mkdir(parents=True, exist_ok=True)
    return path


def backend_file_exists(path: Path, config: Any = None) -> bool:
    """Check if file exists, using backend when virtual mode.

    Args:
        path: Resolved host path to file.
        config: SootheConfig for virtual mode detection.

    Returns:
        True if file exists, False otherwise.
    """
    if _should_use_backend(config):
        backend = _get_backend()
        virtual_path = _to_virtual_home_path(path)
        if backend is not None and virtual_path is not None:
            try:
                return backend.exists(virtual_path)
            except Exception as e:
                logger.debug(
                    "Backend exists check failed for %s, falling back: %s", virtual_path, e
                )

    # Fallback or non-virtual mode
    return path.exists()


def backend_file_stat(path: Path, config: Any = None) -> dict[str, Any]:
    """Get file metadata, using backend when virtual mode.

    Args:
        path: Resolved host path to file.
        config: SootheConfig for virtual mode detection.

    Returns:
        Dict with size_bytes, mtime, is_file, is_dir.

    Raises:
        OSError: If file cannot be accessed.
    """
    if _should_use_backend(config):
        backend = _get_backend()
        virtual_path = _to_virtual_home_path(path)
        if backend is not None and virtual_path is not None:
            try:
                # Backend doesn't have stat method, check existence first
                if not backend.exists(virtual_path):
                    raise OSError(f"File not found: {virtual_path}")
                # Use backend.ls_info for metadata
                # Note: ls_info works on directories, not files directly
                # Fallback to direct stat for now
                pass
            except Exception as e:
                logger.debug("Backend stat failed for %s, falling back: %s", virtual_path, e)

    # Fallback or non-virtual mode
    stat = path.stat()
    return {
        "size_bytes": stat.st_size,
        "mtime": stat.st_mtime,
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
    }


def backend_delete_file(path: Path, config: Any = None) -> None:
    """Delete file, using backend when virtual mode.

    Args:
        path: Resolved host path to file.
        config: SootheConfig for virtual mode detection.
    """
    if _should_use_backend(config):
        backend = _get_backend()
        virtual_path = _to_virtual_home_path(path)
        if backend is not None and virtual_path is not None:
            try:
                backend.delete(virtual_path)
                return
            except Exception as e:
                logger.debug("Backend delete failed for %s, falling back: %s", virtual_path, e)

    # Fallback or non-virtual mode
    if path.exists():
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            import shutil

            shutil.rmtree(path, ignore_errors=True)

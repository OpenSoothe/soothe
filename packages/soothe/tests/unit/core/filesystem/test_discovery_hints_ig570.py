"""Tests for filesystem discovery hints."""

from __future__ import annotations

from pathlib import Path

from deepagents.backends import FilesystemBackend

from soothe.foundation.core.filesystem.discovery_hints import (
    GLOB_DISCOVERY_FALLBACK_HINT,
    GLOB_TOOL_DESCRIPTION,
    format_glob_timeout_error,
)
from soothe.middleware.filesystem import SootheFilesystemMiddleware


def test_glob_tool_description_includes_discovery_fallback() -> None:
    assert "grep" in GLOB_TOOL_DESCRIPTION
    assert GLOB_DISCOVERY_FALLBACK_HINT in GLOB_TOOL_DESCRIPTION


def test_format_glob_timeout_error_includes_fallback() -> None:
    message = format_glob_timeout_error(30.0)
    assert "timed out after 30s" in message
    assert "grep" in message


def test_soothe_filesystem_middleware_glob_has_discovery_description(tmp_path: Path) -> None:
    backend = FilesystemBackend(root_dir=str(tmp_path))
    middleware = SootheFilesystemMiddleware(backend=backend)
    glob_tool = next(t for t in middleware.tools if t.name == "glob")
    assert GLOB_DISCOVERY_FALLBACK_HINT in glob_tool.description
    assert glob_tool.args_schema is not None

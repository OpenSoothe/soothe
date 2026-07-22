"""Tests for shared resolution core (RFC-621)."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe.workspace.core_resolution import (
    WorkspacePrecedence,
    resolve_workspace,
)


def test_loop_precedence_with_client_workspace(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = resolve_workspace(
        WorkspacePrecedence.LOOP,
        loop_id="loop-1",
        client_workspace=str(project),
    )
    assert result.source == "client_workspace"
    assert Path(result.path) == project.resolve()


def test_loop_precedence_missing_client_path_uses_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import soothe.config as cfg

    monkeypatch.setattr(cfg, "SOOTHE_HOME", str(tmp_path))
    missing = tmp_path / "missing-host-path"
    result = resolve_workspace(
        WorkspacePrecedence.LOOP,
        loop_id="loop-1",
        client_workspace=str(missing),
        soothe_home=tmp_path,
    )
    assert result.source == "persisted"
    assert "data/workspaces/anonymous/ws_" in result.path


def test_loop_precedence_persisted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import soothe.config as cfg

    monkeypatch.setattr(cfg, "SOOTHE_HOME", str(tmp_path))
    result = resolve_workspace(
        WorkspacePrecedence.LOOP,
        loop_id="loop-1",
        user_id="alice",
        soothe_home=tmp_path,
    )
    assert result.source == "persisted"
    assert "data/workspaces/alice/ws_" in result.path


def test_stream_precedence_explicit() -> None:
    result = resolve_workspace(
        WorkspacePrecedence.STREAM,
        explicit="/explicit/path",
    )
    assert result.source == "explicit"


def test_stream_precedence_cwd_fallback() -> None:
    result = resolve_workspace(WorkspacePrecedence.STREAM)
    assert result.source == "cwd"


def test_tool_execution_precedence_with_fallback() -> None:
    result = resolve_workspace(
        WorkspacePrecedence.TOOL_EXECUTION,
        fallback="/fallback/path",
    )
    assert result.source == "tool_execution"
    assert Path(result.path) == Path("/fallback/path")


def test_invalid_precedence_raises() -> None:
    from enum import Enum

    class FakePrecedence(Enum):
        FAKE = "fake"

    with pytest.raises(ValueError, match="Unknown precedence"):
        resolve_workspace(FakePrecedence.FAKE)

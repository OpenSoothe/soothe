"""Tests for unified WorkspaceContext (RFC-621)."""

from __future__ import annotations

from pathlib import Path

from soothe_nano.workspace.workspace_runtime import (
    get_workspace_context,
    reset_workspace_context,
    set_workspace_context,
)


def test_default_context() -> None:
    ctx = get_workspace_context()
    assert ctx.workspace is None
    assert ctx.virtual_mode is False
    assert ctx.virtual_home is None


def test_set_and_get_context() -> None:
    token = set_workspace_context(workspace=Path("/project"), virtual_mode=False)
    ctx = get_workspace_context()
    assert ctx.workspace == Path("/project")
    assert ctx.virtual_mode is False
    assert ctx.virtual_home is None
    reset_workspace_context(token)


def test_set_with_virtual_mode() -> None:
    token = set_workspace_context(workspace=Path("/project"), virtual_mode=True)
    ctx = get_workspace_context()
    assert ctx.workspace == Path("/project")
    assert ctx.virtual_mode is True
    assert ctx.virtual_home == Path("/project/.soothe")
    reset_workspace_context(token)


def test_reset_restores_previous() -> None:
    token1 = set_workspace_context(workspace=Path("/first"), virtual_mode=False)
    token2 = set_workspace_context(workspace=Path("/second"), virtual_mode=True)

    ctx = get_workspace_context()
    assert ctx.workspace == Path("/second")

    reset_workspace_context(token2)
    ctx = get_workspace_context()
    assert ctx.workspace == Path("/first")

    reset_workspace_context(token1)


def test_reset_without_token_clears() -> None:
    set_workspace_context(workspace=Path("/project"), virtual_mode=True)
    reset_workspace_context()
    ctx = get_workspace_context()
    assert ctx.workspace is None
    assert ctx.virtual_mode is False

"""Tests for workspace path normalization (IG-300)."""

from pathlib import Path

import pytest

from soothe.core.workspace.path_normalization import strict_workspace_path


def test_strict_workspace_accepts_under_root(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    target = root / "a" / "b.txt"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    p = strict_workspace_path(str(target), workspace=root)
    assert p == target.resolve()


def test_strict_workspace_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError, match="outside workspace"):
        strict_workspace_path(str(outside / "secret.txt"), workspace=root)


def test_strict_workspace_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        strict_workspace_path("  ", workspace=Path("/tmp").resolve())

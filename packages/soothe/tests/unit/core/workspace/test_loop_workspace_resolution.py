"""Tests for per-loop daemon workspace resolution (IG-300)."""

from pathlib import Path

import pytest

import soothe.config as soothe_config


def test_resolve_loop_daemon_workspace_creates_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", str(tmp_path))
    from soothe.core.workspace.resolution import resolve_loop_daemon_workspace

    loop_id = "019dd9ca-f295-7f71-bf54-bf47f2c7a68b"
    p = resolve_loop_daemon_workspace(loop_id)
    expected = (tmp_path / "Workspace" / loop_id).resolve()
    assert p == expected
    assert p.is_dir()


def test_resolve_loop_daemon_workspace_rejects_unsafe_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", str(tmp_path))
    from soothe.core.workspace.resolution import resolve_loop_daemon_workspace

    with pytest.raises(ValueError):
        resolve_loop_daemon_workspace("../etc")

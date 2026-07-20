"""Tests for loop workspace resolution (LoopRunRequest + daemon bind)."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe.foundation.workspace.loop_workspace import (
    _workspace_mount_from_config,
    compute_scoped_workspace_dir_name,
    normalize_user_id,
    resolve_loop_workspace,
    resolve_persisted_loop_workspace,
    user_id_for_hash,
)
from soothe.protocols.runner import LoopRunRequest


def test_normalize_user_id_anonymous() -> None:
    assert normalize_user_id(None) == "anonymous"
    assert normalize_user_id("") == "anonymous"
    assert normalize_user_id("   ") == "anonymous"


def test_normalize_user_id_sanitizes() -> None:
    assert normalize_user_id("alice@corp") == "alice@corp"
    assert normalize_user_id("bob/smith") == "bob_smith"


def test_user_id_for_hash_empty_when_anonymous() -> None:
    assert user_id_for_hash(None) == ""
    assert user_id_for_hash("") == ""


def test_compute_scoped_workspace_dir_name_deterministic() -> None:
    a = compute_scoped_workspace_dir_name("alice", "scope-a")
    b = compute_scoped_workspace_dir_name("alice", "scope-a")
    c = compute_scoped_workspace_dir_name("alice", "scope-b")
    d = compute_scoped_workspace_dir_name(None, "scope-a")

    assert a == b
    assert a.startswith("ws_")
    assert c != a
    assert d.startswith("ws_")
    assert d != a


def test_resolve_loop_workspace_uses_client_path_directly(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    ws = resolve_loop_workspace(loop_id="loop-1", client_workspace=str(project))
    assert ws == project.resolve()


def test_resolve_loop_workspace_falls_back_when_client_path_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("soothe_nano.config.SOOTHE_HOME", str(tmp_path))
    missing = tmp_path / "host-only-path"
    loop_id = "loop-missing-ws"
    ws = resolve_loop_workspace(loop_id=loop_id, client_workspace=str(missing))
    expected_name = compute_scoped_workspace_dir_name(None, loop_id)
    assert ws == tmp_path / "data" / "workspaces" / "anonymous" / expected_name


def test_resolve_loop_workspace_persisted_with_user_and_workspace_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("soothe_nano.config.SOOTHE_HOME", str(tmp_path))
    ws = resolve_loop_workspace(
        loop_id="loop-abc",
        user_id="alice",
        client_workspace_id="my-app",
        soothe_home=tmp_path,
    )
    expected_name = compute_scoped_workspace_dir_name("alice", "my-app")
    assert ws == tmp_path / "data" / "workspaces" / "alice" / expected_name
    assert ws.is_dir()


def test_resolve_loop_workspace_persisted_anonymous_uses_loop_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("soothe_nano.config.SOOTHE_HOME", str(tmp_path))
    loop_id = "019e4e5f-3f09-70f3-8246-b34fe2bc0e66"
    ws = resolve_persisted_loop_workspace(
        loop_id=loop_id,
        user_id=None,
        soothe_home=tmp_path,
    )
    expected_name = compute_scoped_workspace_dir_name(None, loop_id)
    assert ws == tmp_path / "data" / "workspaces" / "anonymous" / expected_name


def test_loop_run_request_resolve_workspace_path(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    req = LoopRunRequest(
        loop_id="loop-1",
        thread_id="thread-1",
        user_input="hi",
        client_workspace=str(project),
    )
    assert Path(req.resolve_workspace_path()) == project.resolve()


def test_resolve_loop_workspace_uses_workspace_mapping_from_metadata(
    tmp_path: Path,
) -> None:
    host_root = tmp_path / "host"
    container_root = tmp_path / "container"
    project = host_root / "demo"
    project.mkdir(parents=True)
    mapped = container_root / "demo"
    mapped.mkdir(parents=True)

    ws = resolve_loop_workspace(
        loop_id="loop-1",
        client_workspace=str(project),
        workspace_mapping={
            "host_root": str(host_root),
            "container_root": str(container_root),
        },
    )
    assert ws == mapped.resolve()


def test_workspace_mount_from_config_returns_none_when_config_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_config = tmp_path / "missing-config.yml"
    monkeypatch.setattr("soothe_nano.config.DEFAULT_CONFIG_PATH", missing_config)
    assert _workspace_mount_from_config() == (None, None)


def test_workspace_mount_from_config_reads_config_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        "workspace_mount:\n  host_root: /host/work\n  container_root: /container/work\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("soothe_nano.config.DEFAULT_CONFIG_PATH", config_path)
    assert _workspace_mount_from_config() == ("/host/work", "/container/work")

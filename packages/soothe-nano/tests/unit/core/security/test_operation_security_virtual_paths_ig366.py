"""IG-366: virtual_mode path strings align with operation security checks."""

from __future__ import annotations

from pathlib import Path

from soothe_sdk.protocols.operation_security import OperationSecurityContext

from soothe_nano.config.models import SecurityConfig
from soothe_nano.security.operation_guard import WorkspaceToolOperationSecurity


def test_virtual_absolute_readme_under_workspace(tmp_path: Path) -> None:
    """``/README.md`` maps under workspace when sandboxed; policy allows."""
    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / "README.md").write_text("# hi", encoding="utf-8")

    sec = SecurityConfig(allow_paths_outside_workspace=False)
    ctx = OperationSecurityContext(
        thread_id="t1",
        workspace=str(ws),
        security_config=sec,
    )
    ev = WorkspaceToolOperationSecurity()
    d = ev._check_filesystem(ctx, "/README.md")
    assert d.verdict == "allow"


def test_virtual_root_ls_under_workspace(tmp_path: Path) -> None:
    """Virtual ``/`` resolves to workspace root for boundary check."""
    ws = tmp_path / "repo"
    ws.mkdir()

    sec = SecurityConfig(allow_paths_outside_workspace=False)
    ctx = OperationSecurityContext(
        thread_id="t1",
        workspace=str(ws),
        security_config=sec,
    )
    ev = WorkspaceToolOperationSecurity()
    d = ev._check_filesystem(ctx, "/")
    assert d.verdict == "allow"


def test_explicit_posix_tmp_outside_workspace_not_virtualized_for_policy(tmp_path: Path) -> None:
    """Host ``/tmp/...`` outside the workspace is not remapped into the workspace (IG-300)."""
    ws = tmp_path / "proj"
    ws.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    sec = SecurityConfig(allow_paths_outside_workspace=False)
    ctx = OperationSecurityContext(
        thread_id="t1",
        workspace=str(ws),
        security_config=sec,
    )
    ev = WorkspaceToolOperationSecurity()
    d = ev._check_filesystem(ctx, str(other))
    assert d.verdict == "deny"
    assert "outside workspace" in d.reason


def test_host_absolute_file_inside_workspace_when_sandboxed(tmp_path: Path) -> None:
    """Host-absolute paths inside the workspace still pass when sandboxed (IG-300)."""
    ws = tmp_path / "repo"
    ws.mkdir()
    target = ws / "nested" / "a.txt"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")

    sec = SecurityConfig(allow_paths_outside_workspace=False)
    ctx = OperationSecurityContext(
        thread_id="t1",
        workspace=str(ws),
        security_config=sec,
    )
    ev = WorkspaceToolOperationSecurity()
    d = ev._check_filesystem(ctx, str(target.resolve()))
    assert d.verdict == "allow"

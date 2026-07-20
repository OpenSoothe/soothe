"""Tests for shell-command virtual-path translation in execution toolkit."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from soothe_nano.toolkits.execution import (
    _translate_virtual_paths_in_command,
    _virtual_mode_from_security,
)


def test_virtual_mode_from_security_handles_none() -> None:
    assert _virtual_mode_from_security(None) is False


def test_virtual_mode_from_security_reads_flag() -> None:
    assert _virtual_mode_from_security(SimpleNamespace(allow_paths_outside_workspace=False)) is True
    assert _virtual_mode_from_security(SimpleNamespace(allow_paths_outside_workspace=True)) is False


def test_translate_skipped_when_virtual_mode_off(tmp_path: Path) -> None:
    cmd = "find / -type f"
    assert _translate_virtual_paths_in_command(cmd, str(tmp_path), virtual_mode=False) == cmd


def test_translate_skipped_when_no_workspace() -> None:
    cmd = "find / -type f"
    assert _translate_virtual_paths_in_command(cmd, None, virtual_mode=True) == cmd


def test_translate_bare_root_to_workspace(tmp_path: Path) -> None:
    ws = str(tmp_path.resolve())
    out = _translate_virtual_paths_in_command("find / -type f", ws, virtual_mode=True)
    assert out == f"find {ws} -type f"


def test_translate_virtual_file_path(tmp_path: Path) -> None:
    ws = str(tmp_path.resolve())
    out = _translate_virtual_paths_in_command("cat /CHANGELOG.md", ws, virtual_mode=True)
    assert out == f"cat {ws}/CHANGELOG.md"


def test_translate_virtual_nested_path(tmp_path: Path) -> None:
    ws = str(tmp_path.resolve())
    out = _translate_virtual_paths_in_command("ls /packages/soothe/src", ws, virtual_mode=True)
    assert out == f"ls {ws}/packages/soothe/src"


def test_host_root_etc_is_not_translated(tmp_path: Path) -> None:
    """``/etc`` and other UNIX host roots must pass through untouched."""
    ws = str(tmp_path.resolve())
    cmd = "cat /etc/passwd"
    assert _translate_virtual_paths_in_command(cmd, ws, virtual_mode=True) == cmd


def test_host_root_tmp_is_not_translated(tmp_path: Path) -> None:
    ws = str(tmp_path.resolve())
    cmd = "ls /tmp/output"
    assert _translate_virtual_paths_in_command(cmd, ws, virtual_mode=True) == cmd


def test_host_root_users_is_not_translated(tmp_path: Path) -> None:
    ws = str(tmp_path.resolve())
    cmd = "ls /Users/someone"
    assert _translate_virtual_paths_in_command(cmd, ws, virtual_mode=True) == cmd


def test_redirect_to_devnull_is_not_translated(tmp_path: Path) -> None:
    ws = str(tmp_path.resolve())
    cmd = "command >/dev/null 2>&1"
    assert _translate_virtual_paths_in_command(cmd, ws, virtual_mode=True) == cmd


def test_url_with_slash_path_is_not_translated(tmp_path: Path) -> None:
    """``https://host/path`` is one token; ``/path`` is mid-token, not a path."""
    ws = str(tmp_path.resolve())
    cmd = "curl https://example.com/api/v1"
    assert _translate_virtual_paths_in_command(cmd, ws, virtual_mode=True) == cmd


def test_path_inside_double_quoted_string_is_not_translated(tmp_path: Path) -> None:
    """Don't rewrite path-shaped tokens that are clearly inside a string literal."""
    ws = str(tmp_path.resolve())
    cmd = 'echo "Hello /world"'
    assert _translate_virtual_paths_in_command(cmd, ws, virtual_mode=True) == cmd


def test_workspace_internal_host_absolute_passes_through(tmp_path: Path) -> None:
    """A host-absolute path that already resolves inside the workspace is left alone."""
    ws = tmp_path.resolve()
    target = ws / "src" / "main.py"
    target.parent.mkdir(parents=True)
    target.write_text("", encoding="utf-8")
    cmd = f"cat {target}"
    # ``/Users/...`` first segment is in the host-root set; the translator must
    # not double-prefix it.
    out = _translate_virtual_paths_in_command(cmd, str(ws), virtual_mode=True)
    assert out == cmd


def test_translate_pipeline_with_virtual_root(tmp_path: Path) -> None:
    ws = str(tmp_path.resolve())
    out = _translate_virtual_paths_in_command("find / -type f | head -5", ws, virtual_mode=True)
    assert out == f"find {ws} -type f | head -5"

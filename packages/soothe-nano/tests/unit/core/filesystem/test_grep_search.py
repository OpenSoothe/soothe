"""Tests for ag/rg-backed grep search."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from soothe_nano.filesystem.grep_search import (
    GREP_UNAVAILABLE_ERROR,
    get_ag_bin,
    get_rg_bin,
    is_grep_available,
    reset_grep_backend_cache,
    run_grep,
)
from soothe_nano.filesystem.local import LocalFilesystem
from soothe_nano.filesystem.protocol import GrepResult

_AG_BIN = "/usr/bin/ag"
_RG_BIN = "/usr/bin/rg"


@pytest.fixture(autouse=True)
def _reset_grep_cache() -> None:
    reset_grep_backend_cache()


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


@contextmanager
def _ag_patch(fake_run: Callable[[list[str]], Any]) -> Iterator[None]:
    def _wrapped(cmd: list[str], *, backend: str, timeout_s: float) -> Any:  # noqa: ARG001
        return fake_run(cmd)

    with (
        patch("soothe_nano.filesystem.grep_search.get_ag_bin", return_value=_AG_BIN),
        patch(
            "soothe_nano.filesystem.grep_search._run_grep_subprocess",
            side_effect=_wrapped,
        ),
    ):
        yield


@contextmanager
def _rg_patch(fake_run: Callable[[list[str]], Any]) -> Iterator[None]:
    def _wrapped(cmd: list[str], *, backend: str, timeout_s: float) -> Any:  # noqa: ARG001
        return fake_run(cmd)

    with (
        patch("soothe_nano.filesystem.grep_search.get_ag_bin", return_value=None),
        patch("soothe_nano.filesystem.grep_search.get_rg_bin", return_value=_RG_BIN),
        patch(
            "soothe_nano.filesystem.grep_search._run_grep_subprocess",
            side_effect=_wrapped,
        ),
    ):
        yield


def test_is_grep_available_reflects_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOOTHE_AG_PATH", raising=False)
    monkeypatch.delenv("SOOTHE_RG_PATH", raising=False)
    monkeypatch.setattr("soothe_nano.filesystem.grep_search.shutil.which", lambda _: None)
    monkeypatch.setattr("soothe_nano.filesystem.grep_search._AG_COMMON_PATHS", ())
    monkeypatch.setattr("soothe_nano.filesystem.grep_search._RG_COMMON_PATHS", ())
    reset_grep_backend_cache()
    assert is_grep_available() is False

    monkeypatch.setattr(
        "soothe_nano.filesystem.grep_search.shutil.which",
        lambda name: "/usr/bin/ag" if name == "ag" else None,
    )
    monkeypatch.setattr(
        "soothe_nano.filesystem.grep_search._normalize_executable",
        lambda path: path if path == "/usr/bin/ag" else None,
    )
    reset_grep_backend_cache()
    assert is_grep_available() is True
    assert get_ag_bin() == "/usr/bin/ag"


def test_resolve_ag_prefers_soothe_ag_path_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    custom_ag = tmp_path / "custom-ag"
    custom_ag.write_text("stub\n")
    custom_ag.chmod(0o755)
    monkeypatch.setenv("SOOTHE_AG_PATH", str(custom_ag))
    monkeypatch.setattr("soothe_nano.filesystem.grep_search.shutil.which", lambda _: "/usr/bin/ag")
    reset_grep_backend_cache()
    assert get_ag_bin() == str(custom_ag.resolve())


def test_get_ag_bin_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def counting_which(name: str) -> str | None:
        nonlocal calls
        calls += 1
        return "/usr/bin/ag" if name == "ag" else None

    monkeypatch.delenv("SOOTHE_AG_PATH", raising=False)
    monkeypatch.setattr("soothe_nano.filesystem.grep_search.shutil.which", counting_which)
    monkeypatch.setattr(
        "soothe_nano.filesystem.grep_search._normalize_executable", lambda path: path
    )
    reset_grep_backend_cache()
    assert get_ag_bin() == "/usr/bin/ag"
    assert get_ag_bin() == "/usr/bin/ag"
    assert calls == 1


def test_run_grep_content_mode(tmp_path: Path) -> None:
    (tmp_path / "search.txt").write_text("line one\nhello world\n")

    def fake_run(cmd: list[str]) -> MagicMock:
        output = "search.txt\n" if "-l" in cmd else "search.txt:2:5:hello world\n"
        return _completed(0, stdout=output)

    with _ag_patch(fake_run):
        result = run_grep(
            workspace=tmp_path,
            search_path=tmp_path,
            pattern="hello",
            glob="*.txt",
            output_mode="content",
        )

    assert isinstance(result, GrepResult)
    assert len(result.matches) == 1
    assert result.matches[0].path == "search.txt"
    assert result.matches[0].line_number == 2


def test_run_grep_content_mode_single_file(tmp_path: Path) -> None:
    search_file = tmp_path / "search.txt"
    search_file.write_text("hello world\n")

    def fake_run(cmd: list[str]) -> MagicMock:
        return _completed(0, stdout="search.txt:1:1:hello world\n")

    with _ag_patch(fake_run):
        result = run_grep(
            workspace=tmp_path,
            search_path=search_file,
            pattern="hello",
            glob=None,
            output_mode="content",
        )

    assert isinstance(result, GrepResult)
    assert len(result.matches) == 1


def test_run_grep_files_with_matches(tmp_path: Path) -> None:
    def fake_run(cmd: list[str]) -> MagicMock:
        return _completed(0, stdout="a.txt\nb.txt\n")

    with _ag_patch(fake_run):
        result = run_grep(
            workspace=tmp_path,
            search_path=tmp_path,
            pattern="hello",
            glob=None,
            output_mode="files_with_matches",
        )

    assert result == ["a.txt", "b.txt"]


def test_grep_with_rg_files_with_matches(tmp_path: Path) -> None:
    def fake_run(cmd: list[str]) -> MagicMock:
        assert "rg" in cmd[0] or cmd[0] == _RG_BIN
        return _completed(0, stdout="a.txt\n")

    with _rg_patch(fake_run):
        result = run_grep(
            workspace=tmp_path,
            search_path=tmp_path,
            pattern="hello",
            glob=None,
            output_mode="files_with_matches",
        )

    assert result == ["a.txt"]


def test_local_grep_delegates_to_run_grep(tmp_path: Path) -> None:
    fs = LocalFilesystem(workspace=tmp_path, virtual_mode=True)
    fs.write("needle.txt", "find the needle here")

    with (
        patch("soothe_nano.filesystem.local.is_grep_available", return_value=True),
        patch("soothe_nano.filesystem.local.run_grep", return_value=["needle.txt"]) as mock_ag,
    ):
        result = fs.grep("needle", output_mode="files_with_matches")

    assert result == ["needle.txt"]
    mock_ag.assert_called_once()


def test_local_grep_errors_when_backend_unavailable(tmp_path: Path) -> None:
    fs = LocalFilesystem(workspace=tmp_path, virtual_mode=True)
    fs.write("needle.txt", "find the needle here")

    with patch("soothe_nano.filesystem.local.is_grep_available", return_value=False):
        result = fs.grep("needle", output_mode="files_with_matches")

    assert isinstance(result, GrepResult)
    assert result.matches == []
    assert result.error == GREP_UNAVAILABLE_ERROR


@pytest.mark.asyncio
async def test_agrep_runs_in_thread(tmp_path: Path) -> None:
    fs = LocalFilesystem(workspace=tmp_path, virtual_mode=True)
    fs.write("async.txt", "async needle")

    with (
        patch("soothe_nano.filesystem.local.is_grep_available", return_value=True),
        patch("soothe_nano.filesystem.local.run_grep", return_value=["async.txt"]),
    ):
        result = await fs.agrep("needle", output_mode="files_with_matches")

    assert result == ["async.txt"]


def test_run_grep_count_mode(tmp_path: Path) -> None:
    def fake_run(cmd: list[str]) -> MagicMock:
        assert "--stats" in cmd
        return _completed(0, stdout="matches found: 3\n")

    with _ag_patch(fake_run):
        result = run_grep(
            workspace=tmp_path,
            search_path=tmp_path,
            pattern="needle",
            glob=None,
            output_mode="count",
        )

    assert result == "3"


def test_run_grep_passes_glob_as_ag_file_regex(tmp_path: Path) -> None:
    captured: list[list[str]] = []

    def fake_run(cmd: list[str]) -> MagicMock:
        captured.append(cmd)
        return _completed(1, stdout="")

    with _ag_patch(fake_run):
        run_grep(
            workspace=tmp_path,
            search_path=tmp_path,
            pattern="needle",
            glob="*.py",
            output_mode="files_with_matches",
        )

    assert captured
    cmd = captured[0]
    assert "-G" in cmd
    assert "--glob" not in cmd


def test_run_grep_returns_none_on_failure(tmp_path: Path) -> None:
    def fake_run(cmd: list[str]) -> MagicMock:  # noqa: ARG001
        return _completed(2, stdout="", stderr="ag: bad pattern")

    with _ag_patch(fake_run):
        result = run_grep(
            workspace=tmp_path,
            search_path=tmp_path,
            pattern="needle",
            glob=None,
            output_mode="files_with_matches",
        )

    assert result is None


def test_directory_content_mode_issues_list_then_content_ag_calls(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("line one\nneedle here\n")
    ag_calls: list[list[str]] = []

    def fake_run(cmd: list[str]) -> MagicMock:
        ag_calls.append(cmd)
        if "-l" in cmd:
            return _completed(0, stdout="a.txt\n")
        return _completed(0, stdout="a.txt:2:7:needle here\n")

    with _ag_patch(fake_run):
        result = run_grep(
            workspace=tmp_path,
            search_path=tmp_path,
            pattern="needle",
            glob=None,
            output_mode="content",
        )

    assert len(ag_calls) == 2
    assert isinstance(result, GrepResult)
    assert result.total_matches == 1


def test_local_grep_single_file_large_log_via_ag(tmp_path: Path) -> None:
    """Single-file grep routes through ag/rg (no 1MB Python cap)."""
    ws = tmp_path / "repo"
    ws.mkdir()
    log_file = tmp_path / "soothe.log"
    log_file.write_text(("executor:1186 line\n" * 200_000), encoding="utf-8")

    def fake_run(cmd: list[str]) -> MagicMock:
        assert str(log_file.resolve()) in cmd
        return _completed(0, stdout=f"{log_file.resolve()}:1:1:executor:1186 line\n")

    fs = LocalFilesystem(workspace=ws, virtual_mode=True)
    with _ag_patch(fake_run):
        result = fs.grep("executor:1186", path=str(log_file.resolve()), output_mode="content")

    assert isinstance(result, GrepResult)
    assert result.total_matches == 1


def test_grep_host_absolute_file_outside_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "repo"
    ws.mkdir()
    log_file = tmp_path / "soothe.log"
    log_file.write_text("executor:1186 [Ledger]\n", encoding="utf-8")

    def fake_run(cmd: list[str]) -> MagicMock:
        return _completed(0, stdout=f"{log_file.resolve()}:1:1:executor:1186 [Ledger]\n")

    fs = LocalFilesystem(workspace=ws, virtual_mode=True)
    with _ag_patch(fake_run):
        result = fs.grep("executor:1186", path=str(log_file.resolve()), output_mode="content")

    assert isinstance(result, GrepResult)
    assert result.total_matches == 1
    assert "executor:1186" in result.matches[0].line_content


def test_grep_write_rejects_host_absolute_outside_workspace(tmp_path: Path) -> None:
    from soothe_nano.filesystem.exceptions import FilesystemError

    ws = tmp_path / "repo"
    ws.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("original\n", encoding="utf-8")

    fs = LocalFilesystem(workspace=ws, virtual_mode=True)
    with pytest.raises(FilesystemError):
        fs.write(str(outside.resolve()), "mutated\n")


def test_normalized_backend_grep_via_ag(tmp_path: Path) -> None:
    from soothe_nano.workspace.workspace_filesystem import NormalizedPathBackend

    (tmp_path / "needle.txt").write_text("find AgentLoop here\n")

    def fake_run(cmd: list[str]) -> MagicMock:
        if "-l" in cmd:
            return _completed(0, stdout="needle.txt\n")
        return _completed(0, stdout="needle.txt:1:6:find AgentLoop here\n")

    backend = NormalizedPathBackend(root_dir=tmp_path, virtual_mode=True)
    with (
        patch("soothe_nano.filesystem.local.is_grep_available", return_value=True),
        _ag_patch(fake_run),
    ):
        result = backend.grep("AgentLoop", path=".", output_mode="content")

    assert result.error is None
    assert result.matches is not None
    assert len(result.matches) == 1


@pytest.mark.skipif(get_ag_bin() is None and get_rg_bin() is None, reason="ag/rg not installed")
def test_local_grep_content_mode_with_real_backend(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# AgentLoop migration\n")

    fs = LocalFilesystem(workspace=tmp_path, virtual_mode=True)
    result = fs.grep("AgentLoop", path=".", output_mode="content")

    assert isinstance(result, GrepResult)
    assert result.total_matches >= 1

"""Tests for ag-backed grep search."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from soothe.foundation.core.filesystem.grep_search import (
    get_ag_bin,
    grep_with_ag,
    is_ag_available,
    reset_ag_availability_cache,
)
from soothe.foundation.core.filesystem.local import LocalFilesystem
from soothe.foundation.core.filesystem.protocol import GrepMatch, GrepResult

_AG_BIN = "/usr/bin/ag"


@pytest.fixture(autouse=True)
def _reset_ag_cache() -> None:
    reset_ag_availability_cache()


@contextmanager
def _ag_patch(fake_run: Callable[..., Any]) -> Iterator[None]:
    """Patch ``ag`` binary resolution and subprocess runner for grep tests."""
    with (
        patch(
            "soothe.foundation.core.filesystem.grep_search.get_ag_bin",
            return_value=_AG_BIN,
        ),
        patch(
            "soothe.foundation.core.filesystem.grep_search.subprocess.run",
            side_effect=fake_run,
        ),
    ):
        yield


def _write_stdout(stdout: Any, text: str) -> None:
    if stdout is not None and hasattr(stdout, "write"):
        stdout.write(text)


def test_is_ag_available_reflects_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOOTHE_AG_PATH", raising=False)
    monkeypatch.setattr(
        "soothe.foundation.core.filesystem.grep_search.shutil.which", lambda _: None
    )
    monkeypatch.setattr(
        "soothe.foundation.core.filesystem.grep_search._AG_COMMON_PATHS",
        (),
    )
    reset_ag_availability_cache()
    assert is_ag_available() is False

    monkeypatch.setattr(
        "soothe.foundation.core.filesystem.grep_search.shutil.which",
        lambda name: "/usr/bin/ag" if name == "ag" else None,
    )
    monkeypatch.setattr(
        "soothe.foundation.core.filesystem.grep_search._normalize_ag_executable",
        lambda path: path if path == "/usr/bin/ag" else None,
    )
    reset_ag_availability_cache()
    assert is_ag_available() is True
    assert get_ag_bin() == "/usr/bin/ag"


def test_resolve_ag_prefers_soothe_ag_path_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    custom_ag = tmp_path / "custom-ag"
    custom_ag.write_text("stub\n")
    custom_ag.chmod(0o755)

    monkeypatch.setenv("SOOTHE_AG_PATH", str(custom_ag))
    monkeypatch.setattr(
        "soothe.foundation.core.filesystem.grep_search.shutil.which",
        lambda _: "/usr/bin/ag",
    )
    reset_ag_availability_cache()

    assert get_ag_bin() == str(custom_ag.resolve())


def test_resolve_ag_falls_back_to_common_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fallback_ag = tmp_path / "opt-homebrew-bin-ag"
    fallback_ag.write_text("stub\n")
    fallback_ag.chmod(0o755)

    monkeypatch.delenv("SOOTHE_AG_PATH", raising=False)
    monkeypatch.setattr(
        "soothe.foundation.core.filesystem.grep_search.shutil.which", lambda _: None
    )
    monkeypatch.setattr(
        "soothe.foundation.core.filesystem.grep_search._AG_COMMON_PATHS",
        (str(fallback_ag),),
    )
    reset_ag_availability_cache()

    assert get_ag_bin() == str(fallback_ag.resolve())


def test_get_ag_bin_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def counting_which(name: str) -> str | None:
        nonlocal calls
        calls += 1
        return "/usr/bin/ag" if name == "ag" else None

    monkeypatch.delenv("SOOTHE_AG_PATH", raising=False)
    monkeypatch.setattr(
        "soothe.foundation.core.filesystem.grep_search.shutil.which", counting_which
    )
    monkeypatch.setattr(
        "soothe.foundation.core.filesystem.grep_search._normalize_ag_executable",
        lambda path: path,
    )
    reset_ag_availability_cache()

    assert get_ag_bin() == "/usr/bin/ag"
    assert get_ag_bin() == "/usr/bin/ag"
    assert calls == 1


def test_grep_with_ag_content_mode(tmp_path: Path) -> None:
    workspace = tmp_path
    search_file = tmp_path / "search.txt"
    search_file.write_text("line one\nhello world\n")

    def fake_run(cmd, stdout=None, **kwargs):  # noqa: ANN001, ARG001
        output = "search.txt\n" if "-l" in cmd else "search.txt:2:5:hello world\n"
        if stdout is not None and hasattr(stdout, "write"):
            stdout.write(output)
        return MagicMock(returncode=0, stderr="")

    with (
        patch(
            "soothe.foundation.core.filesystem.grep_search.shutil.which",
            return_value="/usr/bin/ag",
        ),
        patch("soothe.foundation.core.filesystem.grep_search.subprocess.run", side_effect=fake_run),
    ):
        result = grep_with_ag(
            workspace=workspace,
            search_path=tmp_path,
            pattern="hello",
            glob="*.txt",
            output_mode="content",
        )

    assert isinstance(result, GrepResult)
    assert len(result.matches) == 1
    assert result.matches[0].path == "search.txt"
    assert result.matches[0].line_number == 2
    assert result.matches[0].line_content == "hello world"


def test_grep_with_ag_content_mode_single_file(tmp_path: Path) -> None:
    workspace = tmp_path
    search_file = tmp_path / "search.txt"
    search_file.write_text("hello world\n")

    def fake_run(cmd, stdout=None, **kwargs):  # noqa: ANN001, ARG001
        if stdout is not None and hasattr(stdout, "write"):
            stdout.write("search.txt:1:1:hello world\n")
        return MagicMock(returncode=0, stderr="")

    with (
        patch(
            "soothe.foundation.core.filesystem.grep_search.shutil.which",
            return_value="/usr/bin/ag",
        ),
        patch("soothe.foundation.core.filesystem.grep_search.subprocess.run", side_effect=fake_run),
    ):
        result = grep_with_ag(
            workspace=workspace,
            search_path=search_file,
            pattern="hello",
            glob=None,
            output_mode="content",
        )

    assert isinstance(result, GrepResult)
    assert len(result.matches) == 1
    assert result.matches[0].path == "search.txt"


def test_grep_with_ag_files_with_matches(tmp_path: Path) -> None:
    workspace = tmp_path
    search_path = tmp_path

    def fake_run(cmd, stdout=None, **kwargs):  # noqa: ANN001, ARG001
        if stdout is not None and hasattr(stdout, "write"):
            stdout.write("a.txt\nb.txt\n")
        return MagicMock(returncode=0, stderr="")

    with (
        patch(
            "soothe.foundation.core.filesystem.grep_search.shutil.which",
            return_value="/usr/bin/ag",
        ),
        patch("soothe.foundation.core.filesystem.grep_search.subprocess.run", side_effect=fake_run),
    ):
        result = grep_with_ag(
            workspace=workspace,
            search_path=search_path,
            pattern="hello",
            glob=None,
            output_mode="files_with_matches",
        )

    assert result == ["a.txt", "b.txt"]


def test_local_grep_prefers_ag_when_available(tmp_path: Path) -> None:
    fs = LocalFilesystem(workspace=tmp_path, virtual_mode=True)
    fs.write("needle.txt", "find the needle here")

    with (
        patch(
            "soothe.foundation.core.filesystem.local.is_ag_available",
            return_value=True,
        ),
        patch(
            "soothe.foundation.core.filesystem.local.grep_with_ag",
            return_value=["needle.txt"],
        ) as mock_ag,
    ):
        result = fs.grep("needle", output_mode="files_with_matches")

    assert result == ["needle.txt"]
    mock_ag.assert_called_once()


def test_local_grep_falls_back_when_ag_unavailable(tmp_path: Path) -> None:
    fs = LocalFilesystem(workspace=tmp_path, virtual_mode=True)
    fs.write("needle.txt", "find the needle here")

    with patch(
        "soothe.foundation.core.filesystem.local.is_ag_available",
        return_value=False,
    ):
        result = fs.grep("needle", output_mode="files_with_matches")

    assert result == ["needle.txt"]


@pytest.mark.asyncio
async def test_agrep_runs_in_thread(tmp_path: Path) -> None:
    fs = LocalFilesystem(workspace=tmp_path, virtual_mode=True)
    fs.write("async.txt", "async needle")

    with patch(
        "soothe.foundation.core.filesystem.local.is_ag_available",
        return_value=False,
    ):
        result = await fs.agrep("needle", output_mode="files_with_matches")

    assert result == ["async.txt"]


def test_normalized_backend_grep_content_mode(tmp_path: Path) -> None:
    """Content-mode ``GrepResult`` from the filesystem must reach deepagents matches."""
    from soothe.foundation.workspace.normalized_backend import NormalizedPathBackend

    (tmp_path / "needle.txt").write_text("find AgentLoop here\n")

    backend = NormalizedPathBackend(root_dir=tmp_path, virtual_mode=True)
    with patch(
        "soothe.foundation.core.filesystem.local.is_ag_available",
        return_value=False,
    ):
        result = backend.grep("AgentLoop", path=".", output_mode="content")

    assert result.error is None
    assert result.matches is not None
    assert len(result.matches) == 1
    assert result.matches[0]["path"] == "needle.txt"
    assert result.matches[0]["line"] == 1
    assert "AgentLoop" in result.matches[0]["text"]


def test_grep_with_ag_count_mode(tmp_path: Path) -> None:
    workspace = tmp_path

    def fake_run(cmd, stdout=None, **kwargs):  # noqa: ANN001, ARG001
        assert "--stats" in cmd
        _write_stdout(stdout, "matches found: 3\n")
        return MagicMock(returncode=0, stderr="")

    with _ag_patch(fake_run):
        result = grep_with_ag(
            workspace=workspace,
            search_path=tmp_path,
            pattern="needle",
            glob=None,
            output_mode="count",
        )

    assert result == "3"


def test_grep_with_ag_passes_glob_as_ag_file_regex(tmp_path: Path) -> None:
    captured_cmds: list[list[str]] = []

    def fake_run(cmd, stdout=None, **kwargs):  # noqa: ANN001, ARG001
        captured_cmds.append(cmd)
        _write_stdout(stdout, "")
        return MagicMock(returncode=1, stderr="")

    with _ag_patch(fake_run):
        grep_with_ag(
            workspace=tmp_path,
            search_path=tmp_path,
            pattern="needle",
            glob="*.py",
            output_mode="files_with_matches",
        )

    assert captured_cmds
    cmd = captured_cmds[0]
    assert "-G" in cmd
    assert "--glob" not in cmd
    g_index = cmd.index("-G")
    assert ".py" in cmd[g_index + 1]


def test_grep_with_ag_returns_none_on_ag_failure_exit_code(tmp_path: Path) -> None:
    def fake_run(cmd, stdout=None, **kwargs):  # noqa: ANN001, ARG001
        return MagicMock(returncode=2, stdout="", stderr="ag: bad pattern")

    with _ag_patch(fake_run):
        result = grep_with_ag(
            workspace=tmp_path,
            search_path=tmp_path,
            pattern="needle",
            glob=None,
            output_mode="files_with_matches",
        )

    assert result is None


def test_grep_with_ag_returns_none_on_subprocess_error(tmp_path: Path) -> None:
    def fake_run(cmd, stdout=None, **kwargs):  # noqa: ANN001, ARG001
        raise OSError("ag spawn failed")

    with _ag_patch(fake_run):
        result = grep_with_ag(
            workspace=tmp_path,
            search_path=tmp_path,
            pattern="needle",
            glob=None,
            output_mode="files_with_matches",
        )

    assert result is None


def test_directory_content_mode_issues_list_then_content_ag_calls(tmp_path: Path) -> None:
    workspace = tmp_path
    (tmp_path / "a.txt").write_text("line one\nneedle here\n")
    ag_calls: list[list[str]] = []

    def fake_run(cmd, stdout=None, **kwargs):  # noqa: ANN001, ARG001
        ag_calls.append(cmd)
        if "-l" in cmd:
            _write_stdout(stdout, "a.txt\n")
        else:
            _write_stdout(stdout, "a.txt:2:7:needle here\n")
        return MagicMock(returncode=0, stderr="")

    with _ag_patch(fake_run):
        result = grep_with_ag(
            workspace=workspace,
            search_path=tmp_path,
            pattern="needle",
            glob=None,
            output_mode="content",
        )

    assert len(ag_calls) == 2
    assert "-l" in ag_calls[0]
    assert "-n" in ag_calls[1]
    assert str((tmp_path / "a.txt").resolve()) in ag_calls[1]
    assert isinstance(result, GrepResult)
    assert result.total_matches == 1
    assert result.matches[0].line_content == "needle here"


def test_grep_with_ag_no_matches_returns_empty_content_result(tmp_path: Path) -> None:
    def fake_run(cmd, stdout=None, **kwargs):  # noqa: ANN001, ARG001
        _write_stdout(stdout, "")
        return MagicMock(returncode=1, stderr="")

    with _ag_patch(fake_run):
        result = grep_with_ag(
            workspace=tmp_path,
            search_path=tmp_path,
            pattern="missing",
            glob=None,
            output_mode="content",
        )

    assert isinstance(result, GrepResult)
    assert result.matches == []
    assert result.total_matches == 0


def test_local_grep_content_mode_delegates_to_ag(tmp_path: Path) -> None:
    fs = LocalFilesystem(workspace=tmp_path, virtual_mode=True)
    fs.write("needle.txt", "find AgentLoop here\n")
    ag_result = GrepResult(
        matches=[
            GrepMatch(
                path="needle.txt",
                line_number=1,
                line_content="find AgentLoop here",
                match_start=5,
                match_end=14,
            )
        ],
        total_matches=1,
    )

    with (
        patch("soothe.foundation.core.filesystem.local.is_ag_available", return_value=True),
        patch(
            "soothe.foundation.core.filesystem.local.grep_with_ag",
            return_value=ag_result,
        ) as mock_ag,
    ):
        result = fs.grep("AgentLoop", output_mode="content")

    mock_ag.assert_called_once()
    assert isinstance(result, GrepResult)
    assert result.total_matches == 1
    assert result.matches[0].path == "needle.txt"


def test_local_grep_falls_back_when_ag_returns_none(tmp_path: Path) -> None:
    fs = LocalFilesystem(workspace=tmp_path, virtual_mode=True)
    fs.write("needle.txt", "find the needle here\n")

    with (
        patch("soothe.foundation.core.filesystem.local.is_ag_available", return_value=True),
        patch("soothe.foundation.core.filesystem.local.grep_with_ag", return_value=None),
    ):
        result = fs.grep("needle", output_mode="files_with_matches")

    assert result == ["needle.txt"]


@pytest.mark.asyncio
async def test_agrep_delegates_to_ag_when_available(tmp_path: Path) -> None:
    fs = LocalFilesystem(workspace=tmp_path, virtual_mode=True)
    fs.write("async.txt", "async needle")

    with (
        patch("soothe.foundation.core.filesystem.local.is_ag_available", return_value=True),
        patch(
            "soothe.foundation.core.filesystem.local.grep_with_ag",
            return_value=["async.txt"],
        ) as mock_ag,
    ):
        result = await fs.agrep("needle", output_mode="files_with_matches")

    mock_ag.assert_called_once()
    assert result == ["async.txt"]


def test_normalized_backend_grep_files_with_matches_via_ag(tmp_path: Path) -> None:
    from soothe.foundation.workspace.normalized_backend import NormalizedPathBackend

    (tmp_path / "needle.txt").write_text("needle here\n")
    (tmp_path / "other.txt").write_text("nothing\n")

    def fake_run(cmd, stdout=None, **kwargs):  # noqa: ANN001, ARG001
        _write_stdout(stdout, "needle.txt\n")
        return MagicMock(returncode=0, stderr="")

    backend = NormalizedPathBackend(root_dir=tmp_path, virtual_mode=True)
    with (
        patch("soothe.foundation.core.filesystem.local.is_ag_available", return_value=True),
        _ag_patch(fake_run),
    ):
        result = backend.grep("needle", path=".", output_mode="files_with_matches")

    assert result.error is None
    assert result.matches is not None
    assert len(result.matches) == 1
    assert result.matches[0]["path"] == "needle.txt"
    assert result.matches[0]["line"] == 0


def test_normalized_backend_grep_content_via_ag_two_phase(tmp_path: Path) -> None:
    from soothe.foundation.workspace.normalized_backend import NormalizedPathBackend

    (tmp_path / "needle.txt").write_text("find AgentLoop here\n")

    def fake_run(cmd, stdout=None, **kwargs):  # noqa: ANN001, ARG001
        if "-l" in cmd:
            _write_stdout(stdout, "needle.txt\n")
        else:
            _write_stdout(stdout, "needle.txt:1:6:find AgentLoop here\n")
        return MagicMock(returncode=0, stderr="")

    backend = NormalizedPathBackend(root_dir=tmp_path, virtual_mode=True)
    with (
        patch("soothe.foundation.core.filesystem.local.is_ag_available", return_value=True),
        _ag_patch(fake_run),
    ):
        result = backend.grep("AgentLoop", path=".", output_mode="content")

    assert result.error is None
    assert result.matches is not None
    assert len(result.matches) == 1
    assert result.matches[0]["path"] == "needle.txt"
    assert result.matches[0]["line"] == 1
    assert "AgentLoop" in result.matches[0]["text"]


@pytest.mark.skipif(get_ag_bin() is None, reason="ag not installed")
def test_local_grep_content_mode_with_real_ag(tmp_path: Path) -> None:
    """Integration: builtin grep content mode should use real ``ag`` when installed."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# AgentLoop migration\n")
    (tmp_path / "docs" / "other.md").write_text("no hits\n")

    fs = LocalFilesystem(workspace=tmp_path, virtual_mode=True)
    result = fs.grep("AgentLoop", path=".", output_mode="content")

    assert isinstance(result, GrepResult)
    assert result.total_matches >= 1
    assert any("AgentLoop" in m.line_content for m in result.matches)


@pytest.mark.skipif(get_ag_bin() is None, reason="ag not installed")
def test_local_grep_files_with_matches_with_real_ag(tmp_path: Path) -> None:
    (tmp_path / "match.txt").write_text("AgentLoop here\n")
    (tmp_path / "skip.txt").write_text("nothing\n")

    fs = LocalFilesystem(workspace=tmp_path, virtual_mode=True)
    result = fs.grep("AgentLoop", output_mode="files_with_matches")

    assert result == ["match.txt"]


@pytest.mark.skipif(get_ag_bin() is None, reason="ag not installed")
def test_run_ag_subprocess_captures_stdout_via_tempfile(tmp_path: Path) -> None:
    """``_run_ag_subprocess`` must capture ``ag`` stdout (temp file, not PIPE)."""
    from soothe.foundation.core.filesystem.grep_search import _run_ag_subprocess

    ag_bin = get_ag_bin()
    assert ag_bin is not None
    (tmp_path / "probe.txt").write_text("probe-token\n")

    completed = _run_ag_subprocess(
        [ag_bin, "-l", "probe-token", str(tmp_path)],
        timeout_s=30,
    )

    assert completed is not None
    assert completed.returncode in (0, 1)
    assert "probe.txt" in completed.stdout


@pytest.mark.skipif(get_ag_bin() is None, reason="ag not installed")
def test_grep_with_ag_real_directory_content_two_phase(tmp_path: Path) -> None:
    """Real ``ag``: directory content search lists files then reads line content."""
    (tmp_path / "a.py").write_text("class AgentLoop:\n    pass\n")
    (tmp_path / "b.py").write_text("print('ok')\n")

    result = grep_with_ag(
        workspace=tmp_path,
        search_path=tmp_path,
        pattern="AgentLoop",
        glob="*.py",
        output_mode="content",
    )

    assert isinstance(result, GrepResult)
    assert result.total_matches == 1
    assert result.matches[0].path == "a.py"
    assert "AgentLoop" in result.matches[0].line_content

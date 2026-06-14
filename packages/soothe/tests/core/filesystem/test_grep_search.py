"""Tests for ag-backed grep search."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from soothe.foundation.core.filesystem.grep_search import (
    grep_with_ag,
    is_ag_available,
    reset_ag_availability_cache,
)
from soothe.foundation.core.filesystem.local import LocalFilesystem
from soothe.foundation.core.filesystem.protocol import GrepResult


@pytest.fixture(autouse=True)
def _reset_ag_cache() -> None:
    reset_ag_availability_cache()


def test_is_ag_available_reflects_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "soothe.foundation.core.filesystem.grep_search.shutil.which", lambda _: None
    )
    reset_ag_availability_cache()
    assert is_ag_available() is False

    monkeypatch.setattr(
        "soothe.foundation.core.filesystem.grep_search.shutil.which",
        lambda name: "/usr/bin/ag" if name == "ag" else None,
    )
    reset_ag_availability_cache()
    assert is_ag_available() is True


def test_grep_with_ag_files_with_matches(tmp_path: Path) -> None:
    workspace = tmp_path
    search_path = tmp_path

    def fake_run(cmd, **kwargs):  # noqa: ANN001, ARG001
        assert cmd[0] == "/usr/bin/ag"
        assert "-l" in cmd
        return MagicMock(returncode=0, stdout="a.txt\nb.txt\n", stderr="")

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


def test_grep_with_ag_content_mode(tmp_path: Path) -> None:
    workspace = tmp_path
    search_path = tmp_path

    def fake_run(cmd, **kwargs):  # noqa: ANN001, ARG001
        return MagicMock(
            returncode=0,
            stdout="search.txt:2:5:hello world\n",
            stderr="",
        )

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
            glob="*.txt",
            output_mode="content",
        )

    assert isinstance(result, GrepResult)
    assert len(result.matches) == 1
    assert result.matches[0].path == "search.txt"
    assert result.matches[0].line_number == 2
    assert result.matches[0].line_content == "hello world"


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

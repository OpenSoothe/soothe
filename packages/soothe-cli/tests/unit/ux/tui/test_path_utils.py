"""Tests for safe TUI path probes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from soothe_cli.tui.input import _resolve_existing_pasted_path, parse_pasted_path_payload
from soothe_cli.tui.path_utils import path_exists, path_is_dir, path_is_file


def test_path_exists_returns_false_on_oserror() -> None:
    path = MagicMock(spec=Path)
    path.exists.side_effect = OSError(63, "File name too long", "/bad/path")
    assert path_exists(path) is False


def test_path_is_file_returns_false_on_oserror() -> None:
    path = MagicMock(spec=Path)
    path.is_file.side_effect = OSError(63, "File name too long", "/bad/path")
    assert path_is_file(path) is False


def test_path_is_dir_returns_false_on_oserror() -> None:
    path = MagicMock(spec=Path)
    path.is_dir.side_effect = OSError(63, "File name too long", "/bad/path")
    assert path_is_dir(path) is False


def test_resolve_existing_pasted_path_handles_name_too_long() -> None:
    path = MagicMock(spec=Path)
    path.expanduser.return_value = path
    path.resolve.return_value = path
    path.exists.side_effect = OSError(63, "File name too long", "/bad/path")

    assert _resolve_existing_pasted_path(path) is None


def test_parse_pasted_path_payload_handles_leading_long_path(tmp_path: Path) -> None:
    long_name = "y" * 400
    candidate = tmp_path / long_name
    text = f"{candidate} what is this?"

    path = MagicMock(spec=Path)
    path.expanduser.return_value = path
    path.resolve.return_value = path
    path.exists.side_effect = OSError(63, "File name too long", str(candidate))

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(
            "soothe_cli.tui.input.normalize_pasted_path",
            lambda _text: path,
        )
        assert parse_pasted_path_payload(text, allow_leading_path=True) is None

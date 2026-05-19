"""Tests for TUI media path handling."""

from __future__ import annotations

import pathlib
from unittest.mock import patch

from soothe_cli.tui.media_utils import (
    IMAGE_EXTENSIONS,
    get_image_from_path,
    get_media_from_path,
)


def test_get_image_from_path_skips_non_image_extensions(tmp_path: pathlib.Path) -> None:
    log_file = tmp_path / "daemon.log"
    log_file.write_text("not an image\n", encoding="utf-8")

    assert get_image_from_path(log_file) is None
    assert get_media_from_path(log_file) is None


def test_get_image_from_path_returns_none_when_pillow_missing(
    tmp_path: pathlib.Path,
) -> None:
    png_file = tmp_path / "photo.png"
    png_file.write_bytes(b"\x89PNG\r\n\x1a\n")

    with patch("soothe_cli.tui.media_utils._import_pil", return_value=None):
        assert get_image_from_path(png_file) is None


def test_image_extensions_cover_common_suffixes() -> None:
    assert ".png" in IMAGE_EXTENSIONS
    assert ".log" not in IMAGE_EXTENSIONS

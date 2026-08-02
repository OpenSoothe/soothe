"""Tests for OS clipboard image paste into the TUI input."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from soothe_cli.tui.input import MediaTracker
from soothe_cli.tui.media_utils import (
    ImageData,
    get_image_from_clipboard,
    image_data_from_bytes,
)


def _tiny_png_bytes() -> bytes:
    """Return a minimal valid PNG payload via Pillow."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2, 2), color=(10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def test_image_data_from_bytes_round_trips_png() -> None:
    raw = _tiny_png_bytes()
    data = image_data_from_bytes(raw, fallback_format="png")
    assert data is not None
    assert data.format == "png"
    assert data.base64_data
    assert data.placeholder == "[image]"


def test_image_data_from_bytes_rejects_garbage() -> None:
    assert image_data_from_bytes(b"not-an-image") is None


def test_image_data_from_bytes_rejects_oversized() -> None:
    raw = _tiny_png_bytes()
    with patch("soothe_cli.tui.media_utils.MAX_MEDIA_BYTES", 8):
        assert image_data_from_bytes(raw) is None


def test_get_image_from_clipboard_returns_none_when_empty() -> None:
    with patch(
        "soothe_cli.tui.media_utils._read_clipboard_image_bytes",
        return_value=None,
    ):
        assert get_image_from_clipboard() is None


def test_get_image_from_clipboard_wraps_raw_bytes() -> None:
    raw = _tiny_png_bytes()
    with patch(
        "soothe_cli.tui.media_utils._read_clipboard_image_bytes",
        return_value=raw,
    ):
        data = get_image_from_clipboard()
    assert data is not None
    assert data.format == "png"


@pytest.mark.asyncio
async def test_attach_clipboard_image_inserts_placeholder() -> None:
    from soothe_cli.tui.widgets.chat_input import ChatInput

    tracker = MediaTracker()
    chat = ChatInput.__new__(ChatInput)
    chat._image_tracker = tracker
    text_area = MagicMock()
    chat._text_area = text_area

    media = ImageData(base64_data="abc", format="png", placeholder="[image]")
    with (
        patch.object(ChatInput, "app", new_callable=PropertyMock) as mock_app,
        patch(
            "soothe_cli.tui.media_utils.get_image_from_clipboard",
            return_value=media,
        ),
    ):
        app = MagicMock()
        mock_app.return_value = app
        ok = await chat.attach_clipboard_image(notify_if_empty=True)

    assert ok is True
    assert tracker.get_images()
    assert tracker.get_images()[0].placeholder == "[image 1]"
    text_area.insert.assert_called_once_with("[image 1] ")
    app.notify.assert_not_called()


@pytest.mark.asyncio
async def test_attach_clipboard_image_notifies_when_empty() -> None:
    from soothe_cli.tui.widgets.chat_input import ChatInput

    chat = ChatInput.__new__(ChatInput)
    chat._image_tracker = MediaTracker()
    chat._text_area = MagicMock()

    with (
        patch.object(ChatInput, "app", new_callable=PropertyMock) as mock_app,
        patch(
            "soothe_cli.tui.media_utils.get_image_from_clipboard",
            return_value=None,
        ),
    ):
        app = MagicMock()
        mock_app.return_value = app
        ok = await chat.attach_clipboard_image(notify_if_empty=True)

    assert ok is False
    app.notify.assert_called_once()
    assert "No image" in app.notify.call_args.args[0]


def test_paste_command_registered() -> None:
    from soothe_cli.tui.command_registry import COMMANDS, SIDE_EFFECT_FREE

    names = {cmd.name for cmd in COMMANDS}
    assert "/paste" in names
    assert "/paste" in SIDE_EFFECT_FREE

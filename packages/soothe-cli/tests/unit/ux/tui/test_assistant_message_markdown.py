"""Tests for AssistantMessage markdown streaming and flush behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.tui.widgets.messages import AssistantMessage


@pytest.mark.asyncio
async def test_stop_stream_finalizes_markdown_stream() -> None:
    msg = AssistantMessage(id="asst-test")
    stream = MagicMock()
    stream.stop = AsyncMock()
    msg._stream = stream
    msg._content = "Hello"
    msg._streaming_active = True
    md = MagicMock()
    md.update = AsyncMock()
    msg._markdown = md

    await msg.stop_stream()

    stream.stop.assert_awaited_once()
    assert msg._stream is None
    md.update.assert_awaited_once_with("Hello")


@pytest.mark.asyncio
async def test_stop_stream_skips_full_markdown_refresh_without_stream() -> None:
    msg = AssistantMessage(id="asst-test")
    msg._stream = None
    msg._content = "Hello"
    md = MagicMock()
    md.update = AsyncMock()
    msg._markdown = md

    await msg.stop_stream()

    md.update.assert_not_called()


@pytest.mark.asyncio
async def test_flush_does_not_replace_streamed_markdown_with_repaired_text() -> None:
    from soothe_cli.runtime.presentation.renderer_base import RendererBase
    from soothe_cli.tui.textual_adapter import _flush_assistant_text_ns

    raw = "```python\ndef foo3():\n    pass\n```"
    repaired = RendererBase.repair_concatenated_output(raw)
    assert repaired != raw

    msg = AssistantMessage(id="asst-test")
    msg.set_content = AsyncMock()  # type: ignore[method-assign]
    msg.stop_stream = AsyncMock()  # type: ignore[method-assign]
    msg._content = raw

    adapter = MagicMock()
    adapter._sync_message_content = MagicMock()

    await _flush_assistant_text_ns(
        adapter,
        raw,
        (),
        {(): msg},
    )

    msg.stop_stream.assert_awaited_once()
    msg.set_content.assert_not_awaited()
    assert msg._content == repaired

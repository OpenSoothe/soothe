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

    await msg.stop_stream()

    stream.stop.assert_awaited_once()
    assert msg._stream is None


@pytest.mark.asyncio
async def test_flush_does_not_replace_streamed_markdown_with_repaired_text() -> None:
    from soothe_cli.tui.textual_adapter import _turn_helpers

    raw = "```python\ndef foo3():\n    pass\n```"
    repaired = _turn_helpers.RendererBase.repair_concatenated_output(raw)
    assert repaired != raw

    msg = AssistantMessage(id="asst-test")
    msg.set_content = AsyncMock()  # type: ignore[method-assign]
    msg.stop_stream = AsyncMock()  # type: ignore[method-assign]
    msg._content = raw

    adapter = MagicMock()
    adapter._sync_message_content = MagicMock()

    await _turn_helpers._flush_assistant_text_ns(
        adapter,
        raw,
        (),
        {(): msg},
    )

    msg.stop_stream.assert_awaited_once()
    msg.set_content.assert_not_awaited()
    assert msg._content == repaired

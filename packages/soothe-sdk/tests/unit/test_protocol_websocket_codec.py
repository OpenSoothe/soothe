"""Tests for WebSocket JSON helpers (compact text frames)."""

from __future__ import annotations

from soothe_sdk.wire.protocol import decode_websocket_text, encode_websocket_text


def test_encode_websocket_text_compact_and_roundtrip() -> None:
    msg = {"type": "loop_input", "loop_id": "x", "content": "hi"}
    text = encode_websocket_text(msg)
    assert ": " not in text  # default json spacing omitted
    assert "\n" not in text
    assert decode_websocket_text(text) == msg


def test_decode_websocket_text_strips_and_rejects_empty() -> None:
    assert decode_websocket_text("  \n  ") is None
    assert decode_websocket_text('{"type":"x"}') == {"type": "x"}

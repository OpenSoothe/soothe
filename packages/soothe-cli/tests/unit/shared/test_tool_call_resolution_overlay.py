"""Tests for streaming tool-call args overlay (TUI / daemon client)."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessageChunk

from soothe_cli.shared.tool_call_resolution import build_streaming_args_overlay


@pytest.fixture
def chunk_mid() -> AIMessageChunk:
    """Non-terminal stream chunk (args may still grow)."""
    return AIMessageChunk(content="")


@pytest.fixture
def chunk_last() -> AIMessageChunk:
    return AIMessageChunk(content="", chunk_position="last")


def test_streaming_overlay_reflects_latest_parsed_json(
    chunk_mid: AIMessageChunk,
    chunk_last: AIMessageChunk,
) -> None:
    """``args_str`` can grow across chunks; overlay must not freeze on first parse."""
    pending: dict[str, Any] = {
        "t2": {
            "name": "read_file",
            "args_str": '{"path":"/short"}',
            "emitted": False,
            "is_main": True,
        },
    }
    o1 = build_streaming_args_overlay(chunk_mid, pending)
    assert o1["t2"]["path"] == "/short"
    pending["t2"]["args_str"] = '{"path":"/short","offset":10}'
    o2 = build_streaming_args_overlay(chunk_last, pending)
    assert o2["t2"]["path"] == "/short"
    assert o2["t2"].get("offset") == 10


def test_streaming_overlay_omits_empty_parsed_dict(chunk_last: AIMessageChunk) -> None:
    """IG-300: parsed ``{}`` must not appear in the overlay (no mergeable kwargs)."""
    pending: dict[str, Any] = {
        "g1": {
            "name": "glob",
            "args_str": "{}",
            "emitted": False,
            "is_main": True,
        },
    }
    o = build_streaming_args_overlay(chunk_last, pending)
    assert "g1" not in o

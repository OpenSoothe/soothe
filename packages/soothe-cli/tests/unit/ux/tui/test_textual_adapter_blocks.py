"""Tests for TUI AI message block extraction (CLI parity)."""

from unittest.mock import create_autospec

from langchain_core.messages import AIMessage, AIMessageChunk

from soothe_cli.tui.textual_adapter import _tui_effective_ai_blocks


def test_string_content_fallback_when_no_content_blocks_root() -> None:
    """Daemon-style AIMessage with only ``content`` must yield a text block."""
    msg = AIMessage(content="Hello from daemon wire format")
    blocks = _tui_effective_ai_blocks(msg, ns_key=(), direct_subagent_turn=False)
    assert blocks == [{"type": "text", "text": "Hello from daemon wire format"}]


def test_string_content_when_subagent_routed() -> None:
    """Subgraph streams may omit blocks; allow when ``direct_subagent_turn``."""
    msg = AIMessage(content="Subagent reply")
    blocks = _tui_effective_ai_blocks(msg, ns_key=("graphs", "n1"), direct_subagent_turn=True)
    assert blocks == [{"type": "text", "text": "Subagent reply"}]


def test_plain_string_suppressed_for_nested_without_direct_route() -> None:
    """Task sidecar subgraph: do not invent text blocks (main agent summarizes)."""
    msg = create_autospec(AIMessage, instance=True)
    msg.content = "hidden"
    msg.content_blocks = []
    blocks = _tui_effective_ai_blocks(msg, ns_key=("graphs", "n1"), direct_subagent_turn=False)
    assert blocks == []


def test_prefers_content_blocks_when_present() -> None:
    msg = AIMessage(
        content="ignored when blocks present",
        content_blocks=[{"type": "text", "text": "from blocks"}],
    )
    blocks = _tui_effective_ai_blocks(msg, ns_key=(), direct_subagent_turn=False)
    assert blocks == [{"type": "text", "text": "from blocks"}]


def test_chunk_string_fallback() -> None:
    msg = AIMessageChunk(content="partial")
    blocks = _tui_effective_ai_blocks(msg, ns_key=(), direct_subagent_turn=False)
    assert blocks == [{"type": "text", "text": "partial"}]

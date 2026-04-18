"""Tests for TUI AI message block extraction (CLI parity)."""

from unittest.mock import create_autospec

from langchain_core.messages import AIMessage, AIMessageChunk

from soothe_cli.tui.textual_adapter import (
    _merge_streaming_tool_extra_into_blocks,
    _tui_effective_ai_blocks,
)


def test_merge_streaming_tool_extra_replaces_empty_tool_call_args() -> None:
    """Placeholder tool_calls with empty args must accept chunk-accumulated args."""
    blocks = [
        {"type": "tool_call", "name": "read_file", "id": "c1", "args": {}},
    ]
    extra = [
        {
            "type": "tool_call",
            "name": "read_file",
            "id": "c1",
            "args": {"path": "/README.md"},
        }
    ]
    merged = _merge_streaming_tool_extra_into_blocks(blocks, extra)
    assert merged[0]["args"] == {"path": "/README.md"}


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


def test_dict_payload_with_aimessage_type_string_yields_tool_blocks() -> None:
    """Wire dicts may use ``type: \"AIMessage\"``; must still yield tool blocks."""
    msg = {
        "type": "AIMessage",
        "content": "",
        "tool_calls": [
            {
                "name": "read_file",
                "args": {"file_path": "x.txt"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    }
    blocks = _tui_effective_ai_blocks(msg, ns_key=(), direct_subagent_turn=False)
    assert any(b.get("type") == "tool_call" for b in blocks)


def test_tool_calls_attr_without_content_blocks() -> None:
    """LangChain often sets ``tool_calls`` only — TUI must still build tool blocks."""
    msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "read_file",
                "args": {"file_path": "x.txt"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    blocks = _tui_effective_ai_blocks(msg, ns_key=(), direct_subagent_turn=False)
    assert blocks == [
        {
            "type": "tool_call",
            "name": "read_file",
            "args": {"file_path": "x.txt"},
            "id": "call-1",
        }
    ]


def test_nonstandard_tool_use_expands_to_tool_call() -> None:
    """Anthropic-style ``tool_use`` is wrapped as ``non_standard`` by LangChain."""
    msg = AIMessage(
        content=[
            {
                "type": "non_standard",
                "value": {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "read_file",
                    "input": {"file_path": "README.md"},
                },
            }
        ]
    )
    blocks = _tui_effective_ai_blocks(msg, ns_key=(), direct_subagent_turn=False)
    assert blocks == [
        {
            "type": "tool_call",
            "name": "read_file",
            "id": "toolu_1",
            "args": {"file_path": "README.md"},
        }
    ]


def test_tool_calls_visible_on_nested_namespace_without_direct_route() -> None:
    """Subgraph text is suppressed but tool cards from ``tool_calls`` must render."""
    msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "task",
                "args": {"description": "sub"},
                "id": "call-sub",
                "type": "tool_call",
            }
        ],
    )
    blocks = _tui_effective_ai_blocks(
        msg, ns_key=("graphs", "n1"), direct_subagent_turn=False
    )
    assert blocks == [
        {
            "type": "tool_call",
            "name": "task",
            "args": {"description": "sub"},
            "id": "call-sub",
        }
    ]

"""Tests for TUI AI message block extraction (CLI parity)."""

from unittest.mock import create_autospec

from langchain_core.messages import AIMessage, AIMessageChunk

from soothe_cli.shared.tool_call_resolution import materialize_ai_blocks_with_resolved_tools
from soothe_cli.tui.textual_adapter import (
    _defer_first_tool_card_mount_until_final_stream_chunk,
    _defer_tool_card_for_empty_streaming_args,
    _expand_nonstandard_tool_blocks,
    _repair_concatenated_output_text,
    _tui_effective_ai_blocks,
)


def test_materialize_merges_tool_calls_over_empty_content_block() -> None:
    """Empty block args + ``tool_calls`` on the same chunk → merged kwargs."""
    msg = AIMessageChunk(
        content="",
        content_blocks=[
            {"type": "tool_call", "name": "read_file", "id": "c1", "args": {}},
        ],
        tool_calls=[
            {"name": "read_file", "id": "c1", "args": {"file_path": "/README.md"}},
        ],
    )
    raw = _expand_nonstandard_tool_blocks(
        [b for b in (msg.content_blocks or []) if isinstance(b, dict)]
    )
    merged = materialize_ai_blocks_with_resolved_tools(raw, msg, streaming_overlay=None)
    assert merged[0]["args"] == {"file_path": "/README.md"}


def test_materialize_applies_streaming_overlay() -> None:
    """Streaming overlay fills empty block args for matching id."""
    msg = AIMessageChunk(
        content="",
        content_blocks=[{"type": "tool_call", "id": "c1", "name": "read_file", "args": {}}],
    )
    blocks = [{"type": "tool_call", "name": "read_file", "id": "c1", "args": {}}]
    merged = materialize_ai_blocks_with_resolved_tools(
        blocks,
        msg,
        streaming_overlay={"c1": {"path": "/README.md"}},
    )
    assert merged[0]["args"] == {"path": "/README.md"}


def test_defer_empty_tool_args_until_last_stream_chunk() -> None:
    """Empty args on mid-stream chunks defer tool card finalization elsewhere."""
    mid = AIMessageChunk(content="")
    assert _defer_tool_card_for_empty_streaming_args(mid) is True

    last = AIMessageChunk(content="", chunk_position="last")
    assert _defer_tool_card_for_empty_streaming_args(last) is False

    full = AIMessage(content="")
    assert _defer_tool_card_for_empty_streaming_args(full) is False


def test_defer_first_tool_mount_only_on_explicit_nonfinal_chunk() -> None:
    """First tool card mount waits until ``chunk_position == last`` for marked mid-stream chunks.

    LangChain typically only validates ``last``; other markers use ``model_construct``.
    """
    mid = AIMessageChunk.model_construct(content="", chunk_position="partial")
    assert _defer_first_tool_card_mount_until_final_stream_chunk(mid) is True

    last = AIMessageChunk(content="", chunk_position="last")
    assert _defer_first_tool_card_mount_until_final_stream_chunk(last) is False

    unknown = AIMessageChunk(content="")
    assert _defer_first_tool_card_mount_until_final_stream_chunk(unknown) is False

    full = AIMessage(content="")
    assert _defer_first_tool_card_mount_until_final_stream_chunk(full) is False


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
    blocks = _tui_effective_ai_blocks(msg, ns_key=("graphs", "n1"), direct_subagent_turn=False)
    assert blocks == [
        {
            "type": "tool_call",
            "name": "task",
            "args": {"description": "sub"},
            "id": "call-sub",
        }
    ]


def test_repair_concatenated_output_text_common_artifacts() -> None:
    raw = (
        "# Report##1. Objective and Methodology first10 lines."
        " Read file- **Content Type**\n```1# Soothe\n23<div>```"
    )
    fixed = _repair_concatenated_output_text(raw)
    assert "## 1. Objective" in fixed or "##1. Objective" in fixed
    assert "first 10 lines" in fixed
    assert "Read file\n- **Content Type**" in fixed
    assert "```1\n# Soothe" in fixed or "```\n1\n# Soothe" in fixed
    assert "23\n<div>" in fixed

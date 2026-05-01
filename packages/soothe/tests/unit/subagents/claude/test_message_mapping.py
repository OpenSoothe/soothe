"""Tests for Claude SDK -> LangChain message translators (IG-335)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from soothe.subagents.claude.message_mapping import (
    ClaudeToolCorrelator,
    translate_assistant_text_final,
    translate_error,
    translate_system,
    translate_text_chunk,
    translate_thinking,
    translate_tool_result,
    translate_tool_use,
)


# Lightweight shims so tests don't depend on claude-agent-sdk being installed.
@dataclass
class _ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class _ToolResultBlock:
    tool_use_id: str
    content: Any = None
    is_error: bool | None = None


@dataclass
class _ThinkingBlock:
    thinking: str
    signature: str = "sig"


@dataclass
class _SystemMessage:
    subtype: str
    data: dict[str, Any]


class TestTextTranslation:
    def test_text_chunk_produces_aimessagechunk_with_id(self) -> None:
        chunk = translate_text_chunk("mid-1", "hello world")
        assert isinstance(chunk, AIMessageChunk)
        assert chunk.id == "mid-1"
        assert chunk.content == "hello world"

    def test_text_final_produces_aimessage_with_id(self) -> None:
        final = translate_assistant_text_final("mid-1", "hello world")
        assert isinstance(final, AIMessage)
        assert final.id == "mid-1"
        assert final.content == "hello world"


class TestToolUseTranslation:
    def test_tool_use_produces_aimessage_with_tool_calls(self) -> None:
        block = _ToolUseBlock(
            id="tu-abc",
            name="Read",
            input={"file_path": "/tmp/x.md"},
        )
        msg = translate_tool_use("aid-7", block)
        assert isinstance(msg, AIMessage)
        assert msg.id == "aid-7"
        assert msg.content == ""
        assert len(msg.tool_calls) == 1
        tc = msg.tool_calls[0]
        assert tc["id"] == "tu-abc"
        assert tc["name"] == "Read"
        assert tc["args"] == {"file_path": "/tmp/x.md"}
        assert tc["type"] == "tool_call"

    def test_tool_use_handles_missing_input_dict(self) -> None:
        block = _ToolUseBlock(id="tu-1", name="Bash", input=None)  # type: ignore[arg-type]
        msg = translate_tool_use("aid-1", block)
        assert msg.tool_calls[0]["args"] == {}


class TestToolResultTranslation:
    def test_tool_result_pairs_with_correlator(self) -> None:
        correlator = ClaudeToolCorrelator()
        use = _ToolUseBlock(id="tu-1", name="Glob", input={"pattern": "*"})
        correlator.register(use)

        result = _ToolResultBlock(tool_use_id="tu-1", content="found 3 files")
        msg = translate_tool_result(result, name_lookup=correlator.as_lookup())
        assert isinstance(msg, ToolMessage)
        assert msg.tool_call_id == "tu-1"
        assert msg.name == "Glob"
        assert msg.content == "found 3 files"
        assert msg.status == "success"

    def test_tool_result_error_status(self) -> None:
        result = _ToolResultBlock(tool_use_id="tu-2", content="ENOENT", is_error=True)
        msg = translate_tool_result(result, name_lookup={"tu-2": "Read"})
        assert msg.status == "error"
        assert msg.name == "Read"

    def test_tool_result_unknown_id_falls_back_to_generic_name(self) -> None:
        result = _ToolResultBlock(tool_use_id="tu-orphan", content="x")
        msg = translate_tool_result(result, name_lookup={})
        assert msg.name == "tool"
        assert msg.tool_call_id == "tu-orphan"

    def test_tool_result_list_content_joined(self) -> None:
        result = _ToolResultBlock(
            tool_use_id="tu-3",
            content=[
                {"type": "text", "text": "line one"},
                {"type": "text", "text": "line two"},
            ],
        )
        msg = translate_tool_result(result, name_lookup={"tu-3": "Read"})
        assert "line one" in msg.content
        assert "line two" in msg.content

    def test_tool_result_none_content_yields_empty_string(self) -> None:
        result = _ToolResultBlock(tool_use_id="tu-4", content=None)
        msg = translate_tool_result(result, name_lookup={"tu-4": "X"})
        assert msg.content == ""


class TestThinkingTranslation:
    def test_thinking_produces_content_blocks(self) -> None:
        block = _ThinkingBlock(thinking="ponder", signature="sig-1")
        msg = translate_thinking("aid-9", block)
        assert isinstance(msg, AIMessage)
        assert msg.id == "aid-9"
        assert isinstance(msg.content, list)
        assert msg.content[0]["type"] == "thinking"
        assert msg.content[0]["thinking"] == "ponder"
        assert msg.content[0]["signature"] == "sig-1"


class TestSystemTranslation:
    def test_system_event_carries_subtype_and_data(self) -> None:
        sm = _SystemMessage(subtype="task_progress", data={"task_id": "t1", "tool_uses": 3})
        event = translate_system(sm)
        assert event["type"] == "soothe.capability.claude.system.task_progress"
        assert event["subtype"] == "task_progress"
        assert event["data"] == {"task_id": "t1", "tool_uses": 3}


class TestErrorTranslation:
    def test_error_event_default_source(self) -> None:
        event = translate_error(error="rate_limit")
        assert event["type"] == "soothe.capability.claude.error"
        assert event["error"] == "rate_limit"
        assert event["source"] == "assistant_message"


class TestCorrelator:
    def test_register_and_lookup_round_trip(self) -> None:
        correlator = ClaudeToolCorrelator()
        correlator.register(_ToolUseBlock(id="tu-x", name="Edit", input={}))
        assert correlator.lookup("tu-x") == "Edit"

    def test_lookup_missing_id_returns_tool(self) -> None:
        correlator = ClaudeToolCorrelator()
        assert correlator.lookup("never-seen") == "tool"

    def test_register_skips_blocks_without_id(self) -> None:
        correlator = ClaudeToolCorrelator()
        correlator.register(_ToolUseBlock(id="", name="Read", input={}))
        assert correlator.lookup("") == "tool"

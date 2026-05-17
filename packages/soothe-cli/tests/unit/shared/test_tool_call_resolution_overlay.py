"""Tests for streaming tool-call args overlay (TUI / daemon client)."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessageChunk

from soothe_cli.shared.tools.tool_call_resolution import (
    build_streaming_args_overlay,
    merge_tool_display_args,
    resolve_stream_tool_name,
)


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


def test_merge_tool_display_args_prefers_streaming_overlay() -> None:
    """Empty block args still pick up accumulated ``tool_call_chunks`` JSON."""
    pending = {
        "EZJ-07:s:task:0": {
            "name": "task",
            "args_str": ('{"description": "Find autopilot_cmd.py", "subagent_type": "explore"}'),
            "emitted": False,
            "is_main": True,
        },
    }
    overlay = build_streaming_args_overlay(
        AIMessageChunk(content="", chunk_position="last"),
        pending,
    )
    merged = merge_tool_display_args(
        "EZJ-07:s:task:0",
        block_args={},
        streaming_overlay=overlay,
        pending_tool_calls_lc=pending,
    )
    assert merged.get("subagent_type") == "explore"
    assert "autopilot" in str(merged.get("description", ""))


def test_merge_tool_display_args_prefers_message_tool_calls() -> None:
    """Wire dict ``tool_calls`` wins when pending buffer used a legacy provider id."""
    msg = {
        "type": "ai",
        "content": "",
        "tool_calls": [
            {
                "name": "read_file",
                "id": "ABC-01:s:read_file:0",
                "args": {"path": "/full/path/to/file.py"},
            }
        ],
    }
    pending = {
        "functions.read_file:0": {
            "name": "read_file",
            "args_str": '{"path":"/partial"}',
            "emitted": False,
            "is_main": True,
        },
    }
    merged = merge_tool_display_args(
        "ABC-01:s:read_file:0",
        block_args={},
        streaming_overlay={},
        pending_tool_calls_lc=pending,
        message=msg,
        tool_name="read_file",
    )
    assert merged["path"] == "/full/path/to/file.py"


def test_richest_pending_does_not_steal_task_args_for_inner_tool() -> None:
    """Task pending buffer must not supply kwargs to unrelated subgraph tools."""
    from soothe_cli.shared.tools.message_processing import richest_pending_args_for_lookup

    pending = {
        "STEP-01:s:task:0": {
            "name": "task",
            "args_str": (
                '{"description": "Explore the whole repository", "subagent_type": "explore"}'
            ),
            "emitted": False,
            "is_main": True,
        },
        "functions.grep:0": {
            "name": "grep",
            "args_str": '{"pattern": "autopilot"}',
            "emitted": False,
            "is_main": False,
        },
    }
    merged = richest_pending_args_for_lookup(
        pending,
        "STEP-01:t0:grep.0",
        tool_name="grep",
    )
    assert merged.get("pattern") == "autopilot"
    assert "Explore" not in str(merged.get("description", ""))


def test_merge_inner_tool_on_task_card_uses_tool_args_not_task_desc() -> None:
    """Regression: task-card activity rows showed task description for every tool."""
    pending = {
        "STEP-01:s:task:0": {
            "name": "task",
            "args_str": '{"description": "Do everything", "subagent_type": "explore"}',
            "emitted": False,
            "is_main": True,
        },
        "functions.read_file:0": {
            "name": "read_file",
            "args_str": '{"path": "/src/main.py"}',
            "emitted": False,
            "is_main": False,
        },
    }
    merged = merge_tool_display_args(
        "STEP-01:t0:read_file.1",
        block_args={},
        pending_tool_calls_lc=pending,
        tool_name="read_file",
    )
    assert merged.get("path") == "/src/main.py"
    assert merged.get("description") is None


def test_resolve_stream_tool_name_from_pending() -> None:
    """Placeholder chunk name ``tool`` is replaced by pending stream name."""
    tcid = "LEN-02:s:task:0"
    pending = {tcid: {"name": "task", "args_str": "{}", "emitted": False}}
    assert (
        resolve_stream_tool_name(
            tcid,
            chunk_name="tool",
            pending_tool_calls_lc=pending,
        )
        == "task"
    )
    assert (
        resolve_stream_tool_name(
            "LEN-02:s:task:0",
            chunk_name="tool",
            pending_tool_calls_lc=None,
        )
        == "task"
    )

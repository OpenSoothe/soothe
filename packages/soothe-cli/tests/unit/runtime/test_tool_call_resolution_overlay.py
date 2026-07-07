"""Tests for streaming tool-call args overlay (TUI / daemon client)."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessageChunk

from soothe_cli.runtime.parse.tool_call_resolution import (
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
        "EZJ_07:s:task:0": {
            "name": "task",
            "args_str": (
                '{"description": "Find autopilot_cmd.py", "subagent_type": "deep_research"}'
            ),
            "emitted": False,
            "is_main": True,
        },
    }
    overlay = build_streaming_args_overlay(
        AIMessageChunk(content="", chunk_position="last"),
        pending,
    )
    merged = merge_tool_display_args(
        "EZJ_07:s:task:0",
        block_args={},
        streaming_overlay=overlay,
        pending_tool_calls_lc=pending,
    )
    assert merged.get("subagent_type") == "deep_research"
    assert "autopilot" in str(merged.get("description", ""))


def test_merge_tool_display_args_combines_overlay_and_pending() -> None:
    """Partial overlay must not hide fuller pending JSON (same tool_call_id)."""
    pending = {
        "abc:0": {
            "name": "read_file",
            "args_str": '{"path":"/full.py","limit":500}',
            "is_complete_json": True,
            "emitted": False,
            "is_main": True,
        },
    }
    overlay = build_streaming_args_overlay(
        AIMessageChunk(content="", chunk_position="last"),
        pending,
    )
    overlay["abc:0"] = {"path": "/partial"}
    merged = merge_tool_display_args(
        "abc:0",
        block_args={},
        streaming_overlay=overlay,
        pending_tool_calls_lc=pending,
        tool_name="read_file",
    )
    assert merged["path"] == "/full.py"
    assert merged["limit"] == 500


def test_merge_tool_display_args_matches_message_by_tool_name() -> None:
    """Unified lookup id must still read provider ``tool_calls`` on the message."""
    msg = AIMessageChunk(
        content="",
        tool_calls=[
            {
                "name": "grep",
                "id": "functions.grep:0",
                "args": {"pattern": "autopilot", "path": "/src"},
            }
        ],
    )
    merged = merge_tool_display_args(
        "STEP_01:t0:grep:0",
        block_args={},
        streaming_overlay={},
        pending_tool_calls_lc={},
        message=msg,
        tool_name="grep",
    )
    assert merged["pattern"] == "autopilot"
    assert merged["path"] == "/src"


def test_merge_tool_display_args_prefers_message_tool_calls() -> None:
    """Wire dict ``tool_calls`` wins when pending buffer keys match the unified id."""
    msg = {
        "type": "ai",
        "content": "",
        "tool_calls": [
            {
                "name": "read_file",
                "id": "ABC_01:s:read_file:0",
                "args": {"path": "/full/path/to/file.py"},
            }
        ],
    }
    pending = {
        "ABC_01:s:read_file:0": {
            "name": "read_file",
            "args_str": '{"path":"/partial"}',
            "emitted": False,
            "is_main": True,
        },
    }
    merged = merge_tool_display_args(
        "ABC_01:s:read_file:0",
        block_args={},
        streaming_overlay={},
        pending_tool_calls_lc=pending,
        message=msg,
        tool_name="read_file",
    )
    assert merged["path"] == "/full/path/to/file.py"


def test_richest_pending_task_args_scoped_with_placeholder_tool_name() -> None:
    """Placeholder stream name ``tool`` must not match parallel ``task:0`` on another step."""
    from soothe_cli.runtime.parse.message_processing import richest_pending_args_for_lookup

    pending = {
        "AGP_01:s:task:0": {
            "name": "task",
            "args_str": (
                '{"description": "Explore soothe-sdk package", "subagent_type": "deep_research"}'
            ),
            "is_complete_json": True,
            "emitted": False,
            "is_main": True,
        },
        "AGP_02:s:task:0": {
            "name": "task",
            "args_str": (
                '{"description": "Explore soothe-cli package", "subagent_type": "deep_research"}'
            ),
            "is_complete_json": True,
            "emitted": False,
            "is_main": True,
        },
    }
    merged = richest_pending_args_for_lookup(
        pending,
        "AGP_02:s:task:0",
        tool_name="tool",
    )
    assert "soothe-cli" in str(merged.get("description", ""))
    assert "soothe-sdk" not in str(merged.get("description", ""))


def test_richest_pending_same_step_different_task_index() -> None:
    """``task:0`` and ``task:1`` on one step are distinct delegations."""
    from soothe_cli.runtime.parse.message_processing import richest_pending_args_for_lookup

    pending = {
        "WAV_01:s:task:0": {
            "name": "task",
            "args_str": '{"description": "First delegation", "subagent_type": "deep_research"}',
            "is_complete_json": True,
            "emitted": False,
            "is_main": True,
        },
        "WAV_01:s:task:1": {
            "name": "task",
            "args_str": '{"description": "Second delegation", "subagent_type": "deep_research"}',
            "is_complete_json": True,
            "emitted": False,
            "is_main": True,
        },
    }
    merged = richest_pending_args_for_lookup(
        pending,
        "WAV_01:s:task:1",
        tool_name="task",
    )
    assert "Second delegation" in str(merged.get("description", ""))
    assert "First delegation" not in str(merged.get("description", ""))


def test_richest_pending_task_args_scoped_to_execute_step() -> None:
    """Parallel ``task`` spawns must not reuse another step's pending description."""
    from soothe_cli.runtime.parse.message_processing import richest_pending_args_for_lookup

    pending = {
        "AAA_01:s:task:0": {
            "name": "task",
            "args_str": (
                '{"description": "First step explores the repository", "subagent_type": "deep_research"}'
            ),
            "is_complete_json": True,
            "emitted": False,
            "is_main": True,
        },
        "BBB_02:s:task:0": {
            "name": "task",
            "args_str": (
                '{"description": "Second step maps architecture", "subagent_type": "planner"}'
            ),
            "is_complete_json": True,
            "emitted": False,
            "is_main": True,
        },
    }
    merged = richest_pending_args_for_lookup(
        pending,
        "BBB_02:s:task:0",
        tool_name="task",
    )
    assert "Second step" in str(merged.get("description", ""))
    assert "First step" not in str(merged.get("description", ""))


def test_richest_pending_parallel_subgraph_grep_scoped_by_step() -> None:
    """Parallel PGY steps must not cross-match ``grep`` pending buffers."""
    from soothe_cli.runtime.parse.message_processing import richest_pending_args_for_lookup

    pending = {
        "PGY_01:t0:grep:0": {
            "name": "grep",
            "args_str": '{"pattern": "frontend", "path": "packages/frontend"}',
            "emitted": False,
            "is_main": False,
        },
        "PGY_02:t0:grep:0": {
            "name": "grep",
            "args_str": '{"pattern": "backend", "path": "packages/backend"}',
            "emitted": False,
            "is_main": False,
        },
    }
    merged = richest_pending_args_for_lookup(
        pending,
        "PGY_02:t0:grep:0",
        tool_name="grep",
    )
    assert merged.get("pattern") == "backend"
    assert "frontend" not in str(merged.get("path", ""))


def test_richest_pending_does_not_steal_task_args_for_inner_tool() -> None:
    """Task pending buffer must not supply kwargs to unrelated subgraph tools."""
    from soothe_cli.runtime.parse.message_processing import richest_pending_args_for_lookup

    pending = {
        "STEP_01:s:task:0": {
            "name": "task",
            "args_str": (
                '{"description": "Explore the whole repository", "subagent_type": "deep_research"}'
            ),
            "emitted": False,
            "is_main": True,
        },
        "STEP_01:t0:grep:0": {
            "name": "grep",
            "args_str": '{"pattern": "autopilot"}',
            "emitted": False,
            "is_main": False,
        },
    }
    merged = richest_pending_args_for_lookup(
        pending,
        "STEP_01:t0:grep:0",
        tool_name="grep",
    )
    assert merged.get("pattern") == "autopilot"
    assert "Explore" not in str(merged.get("description", ""))


def test_merge_inner_tool_on_task_card_uses_tool_args_not_task_desc() -> None:
    """Regression: task-card activity rows showed task description for every tool."""
    pending = {
        "STEP_01:s:task:0": {
            "name": "task",
            "args_str": '{"description": "Do everything", "subagent_type": "deep_research"}',
            "emitted": False,
            "is_main": True,
        },
        "STEP_01:t0:read_file:1": {
            "name": "read_file",
            "args_str": '{"path": "/src/main.py"}',
            "emitted": False,
            "is_main": False,
        },
    }
    merged = merge_tool_display_args(
        "STEP_01:t0:read_file:1",
        block_args={},
        pending_tool_calls_lc=pending,
        tool_name="read_file",
    )
    assert merged.get("path") == "/src/main.py"
    assert merged.get("description") is None


def test_resolve_stream_tool_name_from_pending() -> None:
    """Placeholder chunk name ``tool`` is replaced by pending stream name."""
    tcid = "LEN_02:s:task:0"
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
            "LEN_02:s:task:0",
            chunk_name="tool",
            pending_tool_calls_lc=None,
        )
        == "task"
    )

"""Golden tests for LangGraph ``astream`` chunk normalization (IG-218)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from soothe.foundation.core.agent._core import _normalize_layer1_input
from soothe.foundation.loop.utils.stream_normalize import (
    GoalCompletionAccumState,
    extract_text_from_message_content,
    iter_messages_for_act_aggregation,
    iter_messages_for_delegate_task_scan,
    iter_namespaced_tool_messages,
    join_text_fragments,
    parse_tuple_stream_chunk,
    resolve_goal_completion_text,
    update_goal_completion_from_message,
)


def test_extract_text_from_message_content_str_and_blocks() -> None:
    assert extract_text_from_message_content("plain") == "plain"
    assert (
        extract_text_from_message_content([{"type": "text", "text": "a"}, "b", {"text": "c"}])
        == "a\nb\nc"
    )
    assert extract_text_from_message_content(None) == ""


def test_join_text_fragments_separates_blocks_with_newline() -> None:
    """Content blocks are joined with newline separators."""
    assert join_text_fragments(["first", "10"]) == "first\n10"
    assert join_text_fragments(["Report", "## Executive"]) == "Report\n## Executive"
    assert join_text_fragments(["1", "# Heading"]) == "1\n# Heading"
    assert join_text_fragments(["23", "<div>"]) == "23\n<div>"


def test_extract_text_from_message_content_separates_blocks_with_newline() -> None:
    """Content blocks are joined with newline separators."""
    content = [{"type": "text", "text": "Report"}, {"type": "text", "text": "## Executive"}]
    assert extract_text_from_message_content(content) == "Report\n## Executive"


def test_parse_tuple_stream_chunk_two_and_three() -> None:
    assert parse_tuple_stream_chunk(("messages", {"x": 1})) == ((), "messages", {"x": 1})
    inner = (AIMessage(content="h"), {})
    t = (("n",), "messages", inner)
    assert parse_tuple_stream_chunk(t) == (("n",), "messages", inner)


def test_iter_messages_act_three_tuple_root_messages() -> None:
    msg = ToolMessage(content="ok", tool_call_id="t1", name="grep")
    chunk = ((), "messages", (msg, {}))
    out = list(iter_messages_for_act_aggregation(chunk))
    assert out == [msg]


def test_iter_messages_act_two_tuple() -> None:
    msg = AIMessage(content="hi")
    chunk = ("messages", (msg, {}))
    assert list(iter_messages_for_act_aggregation(chunk)) == [msg]


def test_iter_messages_skips_subgraph_namespace() -> None:
    msg = AIMessage(content="x")
    chunk = (("sub",), "messages", (msg, {}))
    assert list(iter_messages_for_act_aggregation(chunk)) == []


def test_iter_namespaced_tool_messages_yields_subgraph_tools() -> None:
    tm = ToolMessage(content="hits", tool_call_id="g1", name="glob")
    chunk = (("tools:abc",), "messages", (tm, {}))
    out = list(iter_namespaced_tool_messages(chunk))
    assert len(out) == 1
    assert out[0][0] == ("tools:abc",)
    assert out[0][1] is tm


def test_iter_namespaced_tool_messages_skips_root() -> None:
    tm = ToolMessage(content="root", tool_call_id="r1", name="ls")
    chunk = ((), "messages", (tm, {}))
    assert list(iter_namespaced_tool_messages(chunk)) == []


def test_iter_messages_delegate_scan_finds_namespaced_task_tool() -> None:
    """Explore-style subgraphs may emit the parent ``task`` return under a namespace (IG-355)."""
    msg = ToolMessage(content="explore-final-body", tool_call_id="tc-explore", name="task")
    chunk = (("functions.task:0",), "messages", (msg, {}))
    out = list(iter_messages_for_delegate_task_scan(chunk))
    assert len(out) == 1
    assert out[0].content == "explore-final-body"


def test_iter_messages_dict_model_branch() -> None:
    tm = ToolMessage(content="r", tool_call_id="1", name="t")
    chunk = {"model": {"messages": [tm]}}
    assert list(iter_messages_for_act_aggregation(chunk)) == [tm]


def test_iter_messages_legacy_list_data() -> None:
    msg = ToolMessage(content="z", tool_call_id="2", name="x")
    chunk = ((), "messages", [msg, {}])
    assert list(iter_messages_for_act_aggregation(chunk)) == [msg]


def test_goal_completion_accumulator_prefers_longer_chunk_stream() -> None:
    state = GoalCompletionAccumState()
    update_goal_completion_from_message(state, AIMessageChunk(content="chunk"))
    update_goal_completion_from_message(state, AIMessage(content="short"))
    assert resolve_goal_completion_text(state) == "chunk"


def test_goal_completion_accumulator_prefers_final_when_longer() -> None:
    state = GoalCompletionAccumState()
    update_goal_completion_from_message(state, AIMessageChunk(content="a"))
    update_goal_completion_from_message(state, AIMessage(content="longer final text"))
    assert resolve_goal_completion_text(state) == "longer final text"


def test_goal_completion_accumulator_tracks_chunked_text() -> None:
    state = GoalCompletionAccumState()
    update_goal_completion_from_message(state, AIMessageChunk(content="goal "))
    update_goal_completion_from_message(state, AIMessageChunk(content="completion"))
    assert resolve_goal_completion_text(state) == "goal completion"


def test_resolve_goal_completion_text_normalizes_empty_lines() -> None:
    """Successive empty lines (3+ newlines) should collapse to single empty line."""
    state = GoalCompletionAccumState()
    state.accumulated_chunks = "line1\n\n\n\nline2"  # 2 empty lines between
    state.final_ai_message_text = ""
    result = resolve_goal_completion_text(state)
    assert result == "line1\n\nline2"  # collapsed to 1 empty line


def test_resolve_goal_completion_text_preserves_single_empty_line() -> None:
    """Single empty line (2 newlines) should be preserved."""
    state = GoalCompletionAccumState()
    state.accumulated_chunks = "line1\n\nline2"
    state.final_ai_message_text = ""
    result = resolve_goal_completion_text(state)
    assert result == "line1\n\nline2"  # unchanged


def test_resolve_goal_completion_text_handles_leading_empty_lines() -> None:
    """Leading empty lines should be normalized."""
    state = GoalCompletionAccumState()
    state.accumulated_chunks = "\n\n\n\nline1"  # 3 leading empty lines
    state.final_ai_message_text = ""
    result = resolve_goal_completion_text(state)
    assert result == "\n\nline1"  # collapsed to 1 empty line


def test_resolve_goal_completion_text_handles_trailing_empty_lines() -> None:
    """Trailing empty lines should be normalized."""
    state = GoalCompletionAccumState()
    state.accumulated_chunks = "line1\n\n\n\n"  # 3 trailing empty lines
    state.final_ai_message_text = ""
    result = resolve_goal_completion_text(state)
    assert result == "line1\n\n"  # collapsed to 1 empty line


def test_normalize_layer1_input_wraps_string() -> None:
    out = _normalize_layer1_input("hello")
    assert isinstance(out, dict)
    assert len(out["messages"]) == 1
    assert out["messages"][0].content == "hello"


def test_normalize_layer1_input_passes_through_dict() -> None:
    d = {"messages": [], "extra": 1}
    assert _normalize_layer1_input(d) is d

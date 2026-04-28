"""Golden tests for LangGraph ``astream`` chunk normalization (IG-218)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from soothe.cognition.agent_loop.utils.stream_normalize import (
    GoalCompletionAccumState,
    extract_text_from_message_content,
    iter_messages_for_act_aggregation,
    join_text_fragments,
    parse_tuple_stream_chunk,
    resolve_goal_completion_text,
    update_goal_completion_from_message,
)
from soothe.core.agent._core import _normalize_layer1_input


def test_extract_text_from_message_content_str_and_blocks() -> None:
    assert extract_text_from_message_content("plain") == "plain"
    assert (
        extract_text_from_message_content([{"type": "text", "text": "a"}, "b", {"text": "c"}])
        == "abc"
    )
    assert extract_text_from_message_content(None) == ""


def test_join_text_fragments_preserves_common_boundaries() -> None:
    assert join_text_fragments(["first", "10"]) == "first 10"
    assert join_text_fragments(["Report", "## Executive"]) == "Report\n## Executive"
    assert join_text_fragments(["1", "# Heading"]) == "1\n# Heading"
    assert join_text_fragments(["23", "<div>"]) == "23\n<div>"


def test_extract_text_from_message_content_repairs_fragment_boundaries() -> None:
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


def test_normalize_layer1_input_wraps_string() -> None:
    out = _normalize_layer1_input("hello")
    assert isinstance(out, dict)
    assert len(out["messages"]) == 1
    assert out["messages"][0].content == "hello"


def test_normalize_layer1_input_passes_through_dict() -> None:
    d = {"messages": [], "extra": 1}
    assert _normalize_layer1_input(d) is d

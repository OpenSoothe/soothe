"""Parallel execute records RFC-214 ledger rows for Plan-assess (IG-374)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from soothe.foundation.loop.engine.executor import (
    LAST_TOOL_RESULT_HEAD_CHARS,
    Executor,
    _last_tool_result_block,
)
from soothe.foundation.loop.state.schemas import LoopState, StepAction, StepResult


def test_append_parallel_wave_ledger_success_and_exception() -> None:
    mock_agent = object()
    ex = Executor(mock_agent, max_parallel_steps=4)
    state = LoopState(goal="count readmes", thread_id="t1", iteration=1, max_iterations=8)
    steps = [
        StepAction(id="s1", description="glob READMEs", expected_output="paths"),
        StepAction(id="s2", description="count them", expected_output="n"),
    ]
    ok = (
        [],
        StepResult(
            step_id="s1",
            success=True,
            outcome={"type": "generic"},
            duration_ms=10,
            thread_id="t1",
            tool_call_count=2,
        ),
        [AIMessageChunk(content="found: "), AIMessage(content="a.md b.md")],
        "",
    )
    gather_results: list = [
        ok,
        RuntimeError("disk full"),
    ]

    ex._append_parallel_wave_ledger(state, steps, gather_results)

    assert len(state.loop_messages) == 4
    h0, a0, h1, a1 = state.loop_messages
    assert h0.content == "Execute: glob READMEs"
    assert getattr(h0, "step_id", None) == "s1"
    assert "a.md b.md" in (a0.content or "")
    assert h1.content == "Execute: count them"
    assert "disk full" in (a1.content or "")


def test_append_parallel_wave_ledger_delegate_fallback() -> None:
    mock_agent = object()
    ex = Executor(mock_agent, max_parallel_steps=4)
    state = LoopState(goal="g", thread_id="t1", iteration=0, max_iterations=8)
    steps = [StepAction(id="only", description="delegate work", expected_output="x")]
    tup = (
        [],
        StepResult(
            step_id="only",
            success=True,
            outcome={"type": "generic"},
            duration_ms=1,
            thread_id="t1",
            tool_call_count=0,
        ),
        [],
        "answer from task tool only",
    )
    ex._append_parallel_wave_ledger(state, steps, [tup])
    assert len(state.loop_messages) == 2
    assert state.loop_messages[1].content == "answer from task tool only"


def test_last_tool_result_block_empty_when_no_tool_messages() -> None:
    assert _last_tool_result_block([]) == ""
    assert _last_tool_result_block([AIMessage(content="hi")]) == ""


def test_last_tool_result_block_uses_most_recent_tool_message() -> None:
    messages = [
        ToolMessage(content="first older", tool_call_id="a", name="glob"),
        AIMessage(content="reasoning"),
        ToolMessage(content="final-count: 50\nmd 33\nyml 8", tool_call_id="b", name="run_python"),
    ]
    block = _last_tool_result_block(messages)
    assert "<LAST_TOOL_RESULT" in block
    assert 'name="run_python"' in block
    assert "final-count: 50" in block
    assert "first older" not in block  # older tool result not included


def test_last_tool_result_block_caps_long_tool_output() -> None:
    long_body = "x" * (LAST_TOOL_RESULT_HEAD_CHARS * 4)
    block = _last_tool_result_block(
        [ToolMessage(content=long_body, tool_call_id="a", name="run_command")]
    )
    assert "<LAST_TOOL_RESULT" in block
    assert f'bytes="{len(long_body)}"' in block
    # CDATA payload must be bounded by the head cap.
    cdata_start = block.index("<![CDATA[") + len("<![CDATA[\n")
    cdata_end = block.index("\n]]>")
    payload = block[cdata_start:cdata_end]
    # preview_first adds a truncation marker; account for marker overhead.
    assert len(payload) <= LAST_TOOL_RESULT_HEAD_CHARS + 50


def test_append_parallel_wave_ledger_attaches_last_tool_result() -> None:
    """plan-assess regression (trace 0e412f): ledger AI body must carry the
    final tool output so the assessor can grade concrete progress."""
    mock_agent = object()
    ex = Executor(mock_agent, max_parallel_steps=4)
    state = LoopState(goal="count files", thread_id="t1", iteration=1, max_iterations=8)
    steps = [StepAction(id="s1", description="count", expected_output="counts")]
    tup = (
        [],
        StepResult(
            step_id="s1",
            success=True,
            outcome={"type": "generic"},
            duration_ms=10,
            thread_id="t1",
            tool_call_count=2,
        ),
        [
            ToolMessage(content="md 33\nyml 8\npy 5", tool_call_id="t1", name="run_python"),
            AIMessage(content="Counted files by extension."),
        ],
        "",
    )
    ex._append_parallel_wave_ledger(state, steps, [tup])
    ai_body = state.loop_messages[1].content or ""
    assert "Counted files by extension." in ai_body
    assert "<LAST_TOOL_RESULT" in ai_body
    assert "md 33" in ai_body

"""Parallel execute records RFC-214 ledger rows for Plan-assess (IG-374)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, AIMessageChunk

from soothe.core.agent_loop.engine.executor import Executor
from soothe.core.agent_loop.state.schemas import LoopState, StepAction, StepResult


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

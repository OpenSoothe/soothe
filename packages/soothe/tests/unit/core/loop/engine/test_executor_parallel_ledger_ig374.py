"""Parallel execute records RFC-214 ledger rows for Plan-assess (IG-374)."""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence
from soothe.foundation.loop.engine.executor import (
    LAST_TOOL_RESULT_HEAD_CHARS,
    Executor,
    _last_tool_result_block,
    _outcome_summary_text,
)
from soothe.foundation.loop.state.schemas import LoopState, StepAction, StepResult


def _make_ce() -> ContextEngine:
    """Create a ContextEngine with sqlite :memory: backend for tests."""
    return ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )


def test_append_parallel_wave_ledger_success_and_exception() -> None:
    mock_agent = object()
    ce = _make_ce()
    ex = Executor(mock_agent, max_parallel_steps=4, context_engine=ce)
    state = LoopState(goal="count readmes", thread_id="t1", iteration=1, max_iterations=8)
    # Bind CE to state so loop_messages property reads from CE ledger
    from soothe.foundation.context.models import GoalNode

    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)

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

    # Check CE ledger directly (state.loop_messages property reads from CE when bound)
    ledger_msgs = ce.ledger.get_messages()
    assert len(ledger_msgs) == 4
    h0, a0, h1, a1 = ledger_msgs
    assert h0.content == "Execute: glob READMEs"
    assert getattr(h0, "step_id", None) == "s1"
    assert "a.md b.md" in (a0.content or "")
    assert h1.content == "Execute: count them"
    assert "disk full" in (a1.content or "")


def test_append_parallel_wave_ledger_delegate_fallback() -> None:
    mock_agent = object()
    ce = _make_ce()
    ex = Executor(mock_agent, max_parallel_steps=4, context_engine=ce)
    state = LoopState(goal="g", thread_id="t1", iteration=0, max_iterations=8)
    # Bind CE to state
    from soothe.foundation.context.models import GoalNode

    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)

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
    # Check CE ledger directly
    ledger_msgs = ce.ledger.get_messages()
    assert len(ledger_msgs) == 2
    assert ledger_msgs[1].content == "answer from task tool only"


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
    """Ledger AI body carries the assistant prose only; tool output is NOT
    injected into the message content."""
    mock_agent = object()
    ce = _make_ce()
    ex = Executor(mock_agent, max_parallel_steps=4, context_engine=ce)
    state = LoopState(goal="count files", thread_id="t1", iteration=1, max_iterations=8)
    # Bind CE to state
    from soothe.foundation.context.models import GoalNode

    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)

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
    # Check CE ledger directly
    ledger_msgs = ce.ledger.get_messages()
    ai_body = ledger_msgs[1].content or ""
    assert "Counted files by extension." in ai_body
    assert "<LAST_TOOL_RESULT" not in ai_body
    assert "md 33" not in ai_body


def test_append_parallel_wave_ledger_uses_outcome_summary_when_no_ai_text() -> None:
    """When assistant text is empty, use execute output summary before placeholder."""
    mock_agent = object()
    ce = _make_ce()
    ex = Executor(mock_agent, max_parallel_steps=4, context_engine=ce)
    state = LoopState(goal="list files", thread_id="t1", iteration=1, max_iterations=8)
    # Bind CE to state
    from soothe.foundation.context.models import GoalNode

    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)

    steps = [StepAction(id="s1", description="list files", expected_output="listing")]
    tup = (
        [],
        StepResult(
            step_id="s1",
            success=True,
            outcome={"type": "generic", "output_summary": "Result: README.md pyproject.toml src/"},
            duration_ms=10,
            thread_id="t1",
            tool_call_count=1,
        ),
        [],
        "",
    )
    ex._append_parallel_wave_ledger(state, steps, [tup])
    # Check CE ledger directly
    ledger_msgs = ce.ledger.get_messages()
    ai_body = ledger_msgs[1].content or ""
    assert "Step completed with no AI text captured" not in ai_body
    assert "Result: README.md pyproject.toml src/" in ai_body


def test_outcome_summary_text_ignores_empty_summary_dict() -> None:
    assert _outcome_summary_text({"output_summary": {"first": "", "last": ""}}) == ""
    assert _outcome_summary_text({"output_summary": {"first": "A", "last": ""}}) == "A"
    assert _outcome_summary_text({"output_summary": {"first": "", "last": "Z"}}) == "Z"
    assert _outcome_summary_text({"output_summary": {"first": "A", "last": "Z"}}) == "A\n...\nZ"

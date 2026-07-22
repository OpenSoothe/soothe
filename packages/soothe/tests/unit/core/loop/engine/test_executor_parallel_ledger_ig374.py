"""Parallel execute records RFC-214 ledger rows for Plan-assess (IG-374).

IG-493: Ledger records only CoreAgent input + final assistant response.
Tool outputs (delegate_final, ToolMessage) are never recorded to ledger.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from soothe.context.engine import ContextEngine
from soothe.context.store_sqlite import SqliteContextPersistence
from soothe.sloop.engine.act_wave_finalize import (
    LAST_TOOL_RESULT_HEAD_CHARS,
    _last_tool_result_block,
    _outcome_summary_text,
)
from soothe.sloop.engine.executor import Executor
from soothe.sloop.engine.step_wave_types import (
    _ExecuteStepResult,
    wave_gather_failed,
    wave_gather_slot,
)
from soothe.sloop.state.schemas import LoopState, StepAction, StepResult


def _make_ce() -> ContextEngine:
    """Create a ContextEngine with sqlite :memory: backend for tests."""
    return ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )


def test_wave_gather_helpers() -> None:
    payloads: list = [_ExecuteStepResult(), RuntimeError("boom")]
    assert wave_gather_slot(payloads, 0) is payloads[0]
    assert wave_gather_slot(payloads, 1) is payloads[1]
    assert wave_gather_slot(payloads, 9) is None
    assert wave_gather_failed(None) is True
    assert wave_gather_failed(RuntimeError("x")) is True
    assert wave_gather_failed(_ExecuteStepResult()) is False


def test_append_parallel_wave_ledger_success_and_exception() -> None:
    mock_agent = object()
    ce = _make_ce()
    ex = Executor(mock_agent, max_parallel_steps=4, context_engine=ce)
    state = LoopState(goal="count readmes", thread_id="t1", iteration=1, max_iterations=8)
    from soothe.context.models import GoalNode

    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)

    steps = [
        StepAction(id="s1", description="glob READMEs", expected_output="paths"),
        StepAction(id="s2", description="count them", expected_output="n"),
    ]
    ok = _ExecuteStepResult(
        events=[],
        step_result=StepResult(
            step_id="s1",
            success=True,
            outcome={"type": "generic"},
            duration_ms=10,
            thread_id="t1",
            tool_call_count=2,
        ),
        messages=[AIMessageChunk(content="found: "), AIMessage(content="a.md b.md")],
        delegate_final="",
        output="a.md b.md",
    )
    gather_results: list = [
        ok,
        RuntimeError("disk full"),
    ]

    ex._append_parallel_wave_ledger(state, steps, gather_results)

    ledger_msgs = ce.ledger.get_messages()
    assert len(ledger_msgs) == 4
    h0, a0, h1, a1 = ledger_msgs
    assert h0.content.startswith("EXECUTION TASK:\n")
    assert "glob READMEs" in h0.content
    assert "EXPECTED OUTPUT:\npaths" in h0.content
    assert getattr(h0, "step_id", None) == "s1"
    assert "a.md b.md" in (a0.content or "")
    assert h1.content.startswith("EXECUTION TASK:\n")
    assert "count them" in h1.content
    assert a1.content == ""


def test_append_parallel_wave_ledger_delegate_fallback() -> None:
    """IG-493: delegate_final is ignored; only final AI response is used."""
    mock_agent = object()
    ce = _make_ce()
    ex = Executor(mock_agent, max_parallel_steps=4, context_engine=ce)
    state = LoopState(goal="g", thread_id="t1", iteration=0, max_iterations=8)
    from soothe.context.models import GoalNode

    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)

    steps = [StepAction(id="only", description="delegate work", expected_output="x")]
    result = _ExecuteStepResult(
        events=[],
        step_result=StepResult(
            step_id="only",
            success=True,
            outcome={"type": "generic"},
            duration_ms=1,
            thread_id="t1",
            tool_call_count=1,
        ),
        messages=[AIMessage(content="", tool_calls=[{"name": "task", "id": "tc1", "args": {}}])],
        delegate_final="answer from task tool only",  # IGNORED per IG-493
        output="",  # Empty output -> empty ledger
    )
    ex._append_parallel_wave_ledger(state, steps, [result])
    ledger_msgs = ce.ledger.get_messages()
    assert len(ledger_msgs) == 2
    # IG-493: Empty AIMessage content + empty output -> empty ledger
    assert ledger_msgs[1].content == ""


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
    assert "first older" not in block


def test_last_tool_result_block_skips_error_tool_messages() -> None:
    messages = [
        ToolMessage(
            content="Error: Command timed out after 60s. The process group was terminated.",
            tool_call_id="a",
            name="run_command",
        ),
        ToolMessage(
            content="found: /Users/me/.soothe/logs/soothe.log", tool_call_id="b", name="glob"
        ),
    ]
    block = _last_tool_result_block(messages)
    assert "<LAST_TOOL_RESULT" in block
    assert "soothe.log" in block
    assert "timed out" not in block


def test_last_tool_result_block_empty_when_only_errors() -> None:
    messages = [
        ToolMessage(
            content="Error: Command timed out after 60s.",
            tool_call_id="a",
            name="run_command",
        ),
    ]
    assert _last_tool_result_block(messages) == ""


def test_last_tool_result_block_caps_long_tool_output() -> None:
    long_body = "x" * (LAST_TOOL_RESULT_HEAD_CHARS * 4)
    block = _last_tool_result_block(
        [ToolMessage(content=long_body, tool_call_id="a", name="run_command")]
    )
    assert "<LAST_TOOL_RESULT" in block
    assert f'bytes="{len(long_body)}"' in block
    cdata_start = block.index("<![CDATA[") + len("<![CDATA[\n")
    cdata_end = block.index("\n]]>")
    payload = block[cdata_start:cdata_end]
    assert len(payload) <= LAST_TOOL_RESULT_HEAD_CHARS + 50


def test_append_parallel_wave_ledger_attaches_last_tool_result() -> None:
    """Ledger AI body carries assistant prose; tool output NOT injected (IG-493)."""
    mock_agent = object()
    ce = _make_ce()
    ex = Executor(mock_agent, max_parallel_steps=4, context_engine=ce)
    state = LoopState(goal="count files", thread_id="t1", iteration=1, max_iterations=8)
    from soothe.context.models import GoalNode

    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)

    steps = [StepAction(id="s1", description="count", expected_output="counts")]
    result = _ExecuteStepResult(
        events=[],
        step_result=StepResult(
            step_id="s1",
            success=True,
            outcome={"type": "generic"},
            duration_ms=10,
            thread_id="t1",
            tool_call_count=2,
        ),
        messages=[
            ToolMessage(content="md 33\nyml 8\npy 5", tool_call_id="t1", name="run_python"),
            AIMessage(content="Counted files by extension."),
        ],
        delegate_final="",
        output="Counted files by extension.",
    )
    ex._append_parallel_wave_ledger(state, steps, [result])
    ledger_msgs = ce.ledger.get_messages()
    ai_body = ledger_msgs[1].content or ""
    assert "Counted files by extension." in ai_body
    assert "<LAST_TOOL_RESULT" not in ai_body
    assert "md 33" not in ai_body


def test_append_parallel_wave_ledger_assistant_response_is_full_not_truncated_ig480() -> None:
    """IG-480: Ledger stores assistant's full response (no truncation)."""
    mock_agent = object()
    ce = _make_ce()
    ex = Executor(mock_agent, max_parallel_steps=4, context_engine=ce)
    state = LoopState(goal="list files", thread_id="t1", iteration=1, max_iterations=8)
    from soothe.context.models import GoalNode

    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)

    steps = [StepAction(id="s1", description="list files", expected_output="listing")]
    result = _ExecuteStepResult(
        events=[],
        step_result=StepResult(
            step_id="s1",
            success=True,
            outcome={"type": "generic"},
            duration_ms=10,
            thread_id="t1",
            tool_call_count=1,
        ),
        messages=[
            AIMessageChunk(content="## Files Found\n\nREADME.md\npyproject.toml\nsrc/\n"),
            AIMessageChunk(content="file_" * 100 + ".py"),
        ],
        delegate_final="",
        output="## Files Found\n\nREADME.md\npyproject.toml\nsrc/\n" + "file_" * 100 + ".py",
    )
    ex._append_parallel_wave_ledger(state, steps, [result])
    ledger_msgs = ce.ledger.get_messages()
    ai_body = ledger_msgs[1].content or ""
    assert "README.md" in ai_body
    assert "file_" in ai_body
    assert "..." not in ai_body


def test_outcome_summary_text_ignores_empty_summary_dict() -> None:
    assert _outcome_summary_text({"output_summary": {"first": "", "last": ""}}) == ""
    assert _outcome_summary_text({"output_summary": {"first": "A", "last": ""}}) == "A"
    assert _outcome_summary_text({"output_summary": {"first": "", "last": "Z"}}) == "Z"
    assert _outcome_summary_text({"output_summary": {"first": "A", "last": "Z"}}) == "A\n...\nZ"


def test_append_parallel_wave_ledger_prioritizes_assistant_response_over_raw_tool_output_ig480() -> (
    None
):
    """IG-480/IG-493: Final assistant response is used, not raw tool output."""
    mock_agent = object()
    ce = _make_ce()
    ex = Executor(mock_agent, max_parallel_steps=4, context_engine=ce)
    state = LoopState(goal="count files", thread_id="t1", iteration=1, max_iterations=8)
    from soothe.context.models import GoalNode

    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)

    steps = [StepAction(id="s1", description="count files", expected_output="counts")]
    result = _ExecuteStepResult(
        events=[],
        step_result=StepResult(
            step_id="s1",
            success=True,
            outcome={"type": "generic"},
            duration_ms=100,
            thread_id="t1",
            tool_call_count=1,
        ),
        messages=[
            AIMessageChunk(content="I'll run a command to count files..."),
            AIMessage(content="", tool_calls=[{"name": "run_command", "id": "tc1", "args": {}}]),
            ToolMessage(content="222437", tool_call_id="tc1", name="run_command"),
            AIMessageChunk(content="## Result\n\n**Total files: 222,437**"),
            AIMessageChunk(content="\n\n### File Types\n\n| py | 119,293 |"),
        ],
        delegate_final="",
        output="I'll run a command to count files...## Result\n\n**Total files: 222,437**\n\n### File Types\n\n| py | 119,293 |",
    )
    ex._append_parallel_wave_ledger(state, steps, [result])
    ledger_msgs = ce.ledger.get_messages()
    ai_body = ledger_msgs[1].content or ""
    assert "222,437" in ai_body
    assert "119,293" in ai_body
    assert ai_body != "222437"


def test_append_parallel_wave_ledger_task_tool_uses_output_fallback_ig493() -> None:
    """IG-493: When messages have no AI text, output is used for ledger."""
    mock_agent = object()
    ce = _make_ce()
    ex = Executor(mock_agent, max_parallel_steps=4, context_engine=ce)
    state = LoopState(goal="count file types", thread_id="t1", iteration=1, max_iterations=8)
    from soothe.context.models import GoalNode

    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)

    steps = [StepAction(id="s1", description="count file types", expected_output="counts")]
    # Simulate: messages only have ToolMessage (no AIMessage), but output has synthesis
    result = _ExecuteStepResult(
        events=[],
        step_result=StepResult(
            step_id="s1",
            success=True,
            outcome={"type": "generic"},
            duration_ms=100,
            thread_id="t1",
            tool_call_count=1,
        ),
        messages=[
            AIMessage(content="", tool_calls=[{"name": "task", "id": "tc1", "args": {}}]),
            ToolMessage(content='{"target":"workspace"}', tool_call_id="tc1", name="task"),
        ],
        delegate_final='{"target":"workspace"}',  # IGNORED
        output="## Result\n\n**Total Files: 312**\n\n| .py | 198 |",  # Used as fallback
    )
    ex._append_parallel_wave_ledger(state, steps, [result])
    ledger_msgs = ce.ledger.get_messages()
    ai_body = ledger_msgs[1].content or ""
    # IG-493: Uses output fallback when messages have no AI text
    assert "## Result" in ai_body
    assert "**Total Files: 312**" in ai_body


def test_append_parallel_wave_ledger_mixed_task_and_tool_uses_core_assistant_text() -> None:
    """Mixed tool usage - uses final assistant text."""
    mock_agent = object()
    ce = _make_ce()
    ex = Executor(mock_agent, max_parallel_steps=4, context_engine=ce)
    state = LoopState(goal="count files", thread_id="t1", iteration=1, max_iterations=8)
    from soothe.context.models import GoalNode

    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)

    steps = [StepAction(id="s1", description="count files", expected_output="counts")]
    result = _ExecuteStepResult(
        events=[],
        step_result=StepResult(
            step_id="s1",
            success=True,
            outcome={"type": "generic"},
            duration_ms=10,
            thread_id="t1",
            tool_call_count=2,
        ),
        messages=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "task", "id": "tc-task", "args": {}},
                    {"name": "run_command", "id": "tc-cmd", "args": {"command": "wc -l"}},
                ],
            ),
            AIMessageChunk(content="Final assistant summary from core agent."),
        ],
        delegate_final="delegate text should be ignored",
        output="Final assistant summary from core agent.",
    )
    ex._append_parallel_wave_ledger(state, steps, [result])

    ai_body = (ce.ledger.get_messages()[1].content or "").strip()
    assert ai_body == "Final assistant summary from core agent."


def test_append_parallel_wave_ledger_none_gather_result_records_error_pair() -> None:
    """Missing gather slot (None) must not crash ledger append."""
    mock_agent = object()
    ce = _make_ce()
    ex = Executor(mock_agent, max_parallel_steps=4, context_engine=ce)
    state = LoopState(goal="count readmes", thread_id="t1", iteration=1, max_iterations=8)
    from soothe.context.models import GoalNode

    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)

    steps = [StepAction(id="s1", description="glob READMEs", expected_output="paths")]
    ex._append_parallel_wave_ledger(state, steps, [None])

    ledger_msgs = ce.ledger.get_messages()
    assert len(ledger_msgs) == 2
    human, ai = ledger_msgs
    assert human.content.startswith("EXECUTION TASK:\n")
    assert ai.content == ""


def test_append_parallel_wave_ledger_none_messages_uses_output_fallback() -> None:
    """Explicit messages=None on result must not crash ledger append."""
    mock_agent = object()
    ce = _make_ce()
    ex = Executor(mock_agent, max_parallel_steps=4, context_engine=ce)
    state = LoopState(goal="count readmes", thread_id="t1", iteration=1, max_iterations=8)
    from soothe.context.models import GoalNode

    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)

    steps = [StepAction(id="s1", description="glob READMEs", expected_output="paths")]
    result = _ExecuteStepResult(
        events=[],
        step_result=StepResult(
            step_id="s1",
            success=True,
            outcome={"type": "generic"},
            duration_ms=10,
            thread_id="t1",
        ),
        messages=None,  # type: ignore[arg-type]
        output="fallback output",
    )
    ex._append_parallel_wave_ledger(state, steps, [result])

    ledger_msgs = ce.ledger.get_messages()
    assert len(ledger_msgs) == 2
    assert "fallback output" in (ledger_msgs[1].content or "")


def test_append_parallel_wave_ledger_empty_final_records_empty_ai() -> None:
    """When no final assistant text exists, ledger stores empty AI content."""
    mock_agent = object()
    ce = _make_ce()
    ex = Executor(mock_agent, max_parallel_steps=4, context_engine=ce)
    state = LoopState(goal="count files", thread_id="t1", iteration=1, max_iterations=8)
    from soothe.context.models import GoalNode

    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)

    steps = [StepAction(id="s1", description="count files", expected_output="counts")]
    result = _ExecuteStepResult(
        events=[],
        step_result=StepResult(
            step_id="s1",
            success=False,
            outcome={"type": "error", "error": "tool failed"},
            error="tool failed",
            duration_ms=10,
            thread_id="t1",
            tool_call_count=1,
        ),
        messages=[
            AIMessage(content="", tool_calls=[{"name": "run_command", "id": "tc1", "args": {}}])
        ],
        delegate_final="",
        output="",
    )
    ex._append_parallel_wave_ledger(state, steps, [result])

    ai_body = ce.ledger.get_messages()[1].content or ""
    assert ai_body == ""


def test_extract_final_assistant_text_module_prefers_chunked_text() -> None:
    """Regression guard for final assistant text extraction."""
    ex = Executor(object(), max_parallel_steps=4, context_engine=_make_ce())
    step_messages = [
        AIMessageChunk(content="Final "),
        AIMessageChunk(content="assistant "),
        AIMessage(content="summary"),
    ]
    assert ex._extract_final_assistant_text_from_step_messages(step_messages) == "Final assistant"


def test_resolve_execute_step_ledger_ai_content_uses_output_fallback_ig493() -> None:
    """IG-493: When messages have no AI text, output is used."""
    ex = Executor(object(), max_parallel_steps=4, context_engine=_make_ce())

    # Messages with AIMessage content - use it
    msgs_with_ai = [
        AIMessage(content="", tool_calls=[{"name": "task", "id": "tc1", "args": {}}]),
        AIMessage(content="## Result\n\nFormatted output"),
    ]
    assert (
        ex._resolve_execute_step_ledger_ai_content(
            step_messages=msgs_with_ai,
            delegate_final='{"raw":"json"}',
            output="fallback output",
        )
        == "## Result\n\nFormatted output"
    )

    # No AIMessage content - use output fallback
    msgs_no_ai = [
        AIMessage(content="", tool_calls=[{"name": "task", "id": "tc1", "args": {}}]),
    ]
    assert (
        ex._resolve_execute_step_ledger_ai_content(
            step_messages=msgs_no_ai,
            delegate_final="delegate final answer",
            output="synthesized output",
        )
        == "synthesized output"
    )

    # No AIMessage content, no output - empty
    assert (
        ex._resolve_execute_step_ledger_ai_content(
            step_messages=msgs_no_ai,
            delegate_final="delegate final answer",
            output="",
        )
        == ""
    )


def test_finalize_execute_step_ledger_ai_content_module() -> None:
    assert Executor._finalize_execute_step_ledger_ai_content("final text") == "final text"
    assert Executor._finalize_execute_step_ledger_ai_content("") == ""

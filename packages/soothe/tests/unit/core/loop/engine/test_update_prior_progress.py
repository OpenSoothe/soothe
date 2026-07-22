"""Unit tests for Executor._update_prior_progress (RFC-227).

Payloads mirror production: ``Executor._stream_and_collect`` returns a
``_ExecuteStepResult`` dataclass containing ``messages`` list with
``AIMessage``/``AIMessageChunk`` only — ``ToolMessage`` instances are routed
into outcome/budget accounting and intentionally excluded from the list.
Tool names therefore come from ``AIMessage.tool_calls``, not from ``ToolMessage`` walks.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from soothe.context.engine import ContextEngine
from soothe.context.store_sqlite import SqliteContextPersistence
from soothe.sloop.engine.executor import Executor, _ExecuteStepResult
from soothe.sloop.state.schemas import LoopState, StepAction, StepExecutionRecord


def _make_ce() -> ContextEngine:
    """Create a ContextEngine with sqlite :memory: backend for tests."""
    return ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )


def _ai_with_tool_calls(
    *,
    text: str = "",
    tool_calls: list[dict] | None = None,
) -> AIMessage:
    return AIMessage(content=text, tool_calls=tool_calls or [])


def _ok_payload(
    *,
    step_id: str = "s1",
    final_text: str = "ok",
    tool_calls: list[dict] | None = None,
    extra_messages: list = None,
    delegate_final: str = "",
) -> _ExecuteStepResult:
    """Build a successful _ExecuteStepResult matching production gather_results shape."""
    messages: list = list(extra_messages or [])
    if tool_calls:
        messages.append(_ai_with_tool_calls(text="", tool_calls=tool_calls))
    messages.append(AIMessage(content=final_text))
    return _ExecuteStepResult(
        events=[],
        step_result=StepExecutionRecord(
            step_id=step_id,
            success=True,
            outcome={"type": "generic"},
            duration_ms=10,
            thread_id="t1",
            tool_call_count=len(tool_calls or []),
        ),
        messages=messages,
        delegate_final=delegate_final,
        output=final_text,
    )


def _failed_payload(step_id: str = "s1", error: str = "boom") -> _ExecuteStepResult:
    return _ExecuteStepResult(
        events=[],
        step_result=StepExecutionRecord(
            step_id=step_id,
            success=False,
            outcome={"type": "error", "error": error},
            error=error,
            error_type="execution",
            duration_ms=1,
            thread_id="t1",
        ),
        messages=[AIMessage(content=f"failed: {error}")],
        delegate_final="",
        output=f"failed: {error}",
    )


def _executor() -> Executor:
    return Executor(object(), max_parallel_steps=4, context_engine=_make_ce())


def test_tool_calls_extracted_from_aimessage_tool_calls() -> None:
    ex = _executor()
    state = LoopState(goal="count", thread_id="t1", iteration=1)
    steps = [
        StepAction(id="s1", description="count py", expected_output="n"),
        StepAction(id="s2", description="count json", expected_output="n"),
    ]
    payloads = [
        _ok_payload(
            step_id="s1",
            final_text="Counted .py: 1139",
            tool_calls=[
                {
                    "name": "run_command",
                    "args": {"command": "find . -name '*.py' | wc -l"},
                    "id": "a",
                }
            ],
        ),
        _ok_payload(
            step_id="s2",
            final_text="Counted .json: 665",
            tool_calls=[{"name": "run_command", "args": {"command": "wc -l *.json"}, "id": "b"}],
        ),
    ]

    ex._update_prior_progress(state, steps, payloads)

    d = state.prior_progress
    assert d is not None
    assert d.steps_completed == 2
    assert [t.name for t in d.tool_calls] == ["run_command", "run_command"]
    assert d.tool_calls[0].head == "find . -name '*.py' | wc -l"
    assert d.tool_calls[1].head == "wc -l *.json"
    assert d.derived_progress_hint == "high"
    assert any("1139" in e for e in d.evidence_excerpts)
    assert len(d.step_summaries) == 2
    assert d.step_summaries[0].step_id == "s1"
    assert d.step_summaries[0].status == "completed"
    assert "1139" in d.step_summaries[0].outcome_preview


def test_tool_call_head_handles_missing_args() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="x", expected_output="y")]
    payloads = [
        _ok_payload(
            final_text="ok",
            tool_calls=[
                {"name": "noop_tool", "args": {}, "id": "a"},
                {"name": "another_tool", "args": {"unused": None}, "id": "b"},
            ],
        )
    ]
    ex._update_prior_progress(state, steps, payloads)
    heads = [(t.name, t.head) for t in state.prior_progress.tool_calls]
    assert heads == [("noop_tool", ""), ("another_tool", "")]


def test_tool_call_head_uses_first_non_empty_arg_value() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="x", expected_output="y")]
    payloads = [
        _ok_payload(
            final_text="ok",
            tool_calls=[
                {
                    "name": "read_file",
                    "args": {"line_offset": None, "path": "src/main.py"},
                    "id": "a",
                }
            ],
        )
    ]
    ex._update_prior_progress(state, steps, payloads)
    assert state.prior_progress.tool_calls[0].head == "src/main.py"


def test_tool_call_head_first_line_only_capped_at_120() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="x", expected_output="y")]
    huge = "x" * 300
    payloads = [
        _ok_payload(
            final_text="ok",
            tool_calls=[
                {"name": "run_command", "args": {"command": "first\nsecond\nthird"}, "id": "a"},
                {"name": "run_command", "args": {"command": huge}, "id": "b"},
            ],
        )
    ]
    ex._update_prior_progress(state, steps, payloads)
    heads = state.prior_progress.tool_calls
    assert heads[0].head == "first"
    assert len(heads[1].head) == 120


def test_tool_calls_capped_at_8_across_steps() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [
        StepAction(id="s1", description="x", expected_output="y"),
        StepAction(id="s2", description="z", expected_output="w"),
    ]
    payloads = [
        _ok_payload(
            final_text="a",
            tool_calls=[
                {"name": f"t{i}", "args": {"command": f"c{i}"}, "id": str(i)} for i in range(6)
            ],
        ),
        _ok_payload(
            final_text="b",
            tool_calls=[
                {"name": f"u{i}", "args": {"command": f"d{i}"}, "id": str(i + 100)}
                for i in range(6)
            ],
        ),
    ]
    ex._update_prior_progress(state, steps, payloads)
    tcs = state.prior_progress.tool_calls
    assert len(tcs) == 8
    assert [t.name for t in tcs] == ["t0", "t1", "t2", "t3", "t4", "t5", "u0", "u1"]


def test_evidence_uses_assistant_prose_when_available() -> None:
    """When ToolMessages and assistant prose are present, evidence uses the prose."""
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="count", expected_output="counts")]
    payloads = [
        _ok_payload(
            final_text="Counted files by extension.",
            tool_calls=[{"name": "run_python", "args": {"code": "len(...)"}, "id": "a"}],
            extra_messages=[
                ToolMessage(content="py 1139\njson 665", tool_call_id="a", name="run_python"),
            ],
        )
    ]
    ex._update_prior_progress(state, steps, payloads)
    excerpt = state.prior_progress.evidence_excerpts[0]
    assert "Counted files by extension." in excerpt


def test_evidence_uses_chunked_assistant_text_when_final_ai_is_empty() -> None:
    """Production single-step case: final AIMessage content is empty; text lives in chunks."""
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="count", expected_output="counts")]
    payloads = [
        _ExecuteStepResult(
            events=[],
            step_result=StepExecutionRecord(
                step_id="s1",
                success=True,
                outcome={"type": "generic"},
                duration_ms=5,
                thread_id="t1",
                tool_call_count=1,
            ),
            messages=[
                _ai_with_tool_calls(
                    tool_calls=[
                        {"name": "run_command", "args": {"command": "wc -l"}, "id": "a"},
                    ],
                ),
                AIMessageChunk(content="The repo has "),
                AIMessageChunk(content="1139 Python files."),
                AIMessage(content=""),
            ],
            delegate_final="",
            output="The repo has 1139 Python files.",
        )
    ]
    ex._update_prior_progress(state, steps, payloads)
    assert state.prior_progress.evidence_excerpts, "expected chunked text to surface as evidence"
    assert "1139 Python files" in state.prior_progress.evidence_excerpts[0]


def test_evidence_falls_back_to_delegate_final() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="delegate", expected_output="x")]
    payloads = [
        _ExecuteStepResult(
            events=[],
            step_result=StepExecutionRecord(
                step_id="s1",
                success=True,
                outcome={"type": "generic"},
                duration_ms=1,
                thread_id="t1",
                tool_call_count=0,
            ),
            messages=[AIMessage(content="")],
            delegate_final="subagent produced: total=42",
            output="",  # Empty output -> delegate_final used for evidence
        )
    ]
    ex._update_prior_progress(state, steps, payloads)
    assert state.prior_progress.evidence_excerpts == ["subagent produced: total=42"]


def test_any_failure_hint_low() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=2)
    steps = [
        StepAction(id="s1", description="x", expected_output="y"),
        StepAction(id="s2", description="z", expected_output="w"),
    ]
    payloads = [
        _ok_payload(
            final_text="Done; total 1234 found",
            tool_calls=[{"name": "run_command", "args": {"command": "wc"}, "id": "a"}],
        ),
        _failed_payload(step_id="s2", error="disk full"),
    ]
    ex._update_prior_progress(state, steps, payloads)
    assert state.prior_progress.steps_completed == 1
    assert state.prior_progress.steps_failed == 1
    assert state.prior_progress.derived_progress_hint == "low"


def test_no_tools_no_text_hint_none() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="silent", expected_output="ok")]
    payloads = [_ok_payload(final_text="", tool_calls=None)]
    ex._update_prior_progress(state, steps, payloads)
    assert state.prior_progress.derived_progress_hint == "none"
    assert state.prior_progress.tool_calls == []
    assert state.prior_progress.evidence_excerpts == []


def test_evidence_excerpts_dedupe_and_cap() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id=f"s{i}", description=f"step {i}", expected_output="y") for i in range(5)]
    shared = "A" * 64 + " shared prefix"
    payloads = [
        _ok_payload(step_id="s0", final_text=shared + " one"),
        _ok_payload(step_id="s1", final_text=shared + " two"),
        _ok_payload(step_id="s2", final_text="B" * 64 + " different two"),
        _ok_payload(step_id="s3", final_text="C" * 64 + " different three"),
        _ok_payload(step_id="s4", final_text="D" * 64 + " different four"),
    ]
    ex._update_prior_progress(state, steps, payloads)
    excerpts = state.prior_progress.evidence_excerpts
    assert len(excerpts) == 3
    assert excerpts[-1].startswith("DDDD")


def test_excerpt_truncated_at_200_chars() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="x", expected_output="y")]
    payloads = [_ok_payload(final_text="Q" * 500, tool_calls=None)]
    ex._update_prior_progress(state, steps, payloads)
    assert len(state.prior_progress.evidence_excerpts[0]) == 200


def test_overwrites_each_wave_and_increments_wave_index_within_iteration() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=1)
    steps = [StepAction(id="s1", description="x", expected_output="y")]
    ex._update_prior_progress(state, steps, [_ok_payload(final_text="first wave 42")])
    assert state.prior_progress.wave_index == 0
    assert "first wave 42" in state.prior_progress.evidence_excerpts[0]
    ex._update_prior_progress(state, steps, [_ok_payload(final_text="second wave 99")])
    assert state.prior_progress.wave_index == 1
    assert "second wave 99" in state.prior_progress.evidence_excerpts[0]
    state.iteration = 2
    ex._update_prior_progress(state, steps, [_ok_payload(final_text="iter2 wave0")])
    assert state.prior_progress.iteration == 2
    assert state.prior_progress.wave_index == 0


def test_exception_in_gather_results_counts_as_failed() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [
        StepAction(id="s1", description="x", expected_output="y"),
        StepAction(id="s2", description="z", expected_output="w"),
    ]
    payloads: list = [
        _ok_payload(
            final_text="ok 5",
            tool_calls=[{"name": "run_command", "args": {"command": "x"}, "id": "a"}],
        ),
        RuntimeError("crashed"),
    ]
    ex._update_prior_progress(state, steps, payloads)
    assert state.prior_progress.steps_completed == 1
    assert state.prior_progress.steps_failed == 1
    assert state.prior_progress.derived_progress_hint == "low"


def test_streamed_aimessage_chunks_resolve_real_tool_name_and_args() -> None:
    """Trace 817c regression: production AIMessageChunks carry per-chunk partial
    ``tool_call_chunks`` (first chunk has name, later chunks have args deltas).
    The aggregator must produce real names and parsed args, not ``"tool"`` with
    empty heads.
    """
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="streamed", expected_output="y")]

    # Single tool call streamed across three chunks. First carries name + id,
    # following chunks carry args deltas. langchain's chunks-to-tool_calls
    # resolver runs at chunk level only, not across chunks — we must aggregate.
    payload = _ExecuteStepResult(
        events=[],
        step_result=StepExecutionRecord(
            step_id="s1",
            success=True,
            outcome={"type": "code_exec"},
            duration_ms=5,
            thread_id="t1",
            tool_call_count=1,
        ),
        messages=[
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "run_command",
                        "args": '{"command":',
                        "id": "call_xyz",
                        "index": 0,
                    }
                ],
            ),
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {"name": None, "args": ' "find . -type f"', "id": None, "index": 0}
                ],
            ),
            AIMessageChunk(
                content="",
                tool_call_chunks=[{"name": None, "args": "}", "id": None, "index": 0}],
            ),
            AIMessageChunk(content="Found 1139 files."),
            AIMessage(content=""),
        ],
        delegate_final="",
        output="Found 1139 files.",
    )
    ex._update_prior_progress(state, steps, [payload])

    d = state.prior_progress
    assert d is not None
    assert [t.name for t in d.tool_calls] == ["run_command"]
    assert d.tool_calls[0].head == "find . -type f"
    assert any("1139" in e for e in d.evidence_excerpts)


def test_streamed_chunks_with_multiple_tool_calls_aggregate_by_index() -> None:
    """Multiple tool calls in one streamed assistant turn: chunks may share
    ids per call, or rely on ``index`` as the only distinguishing key when the
    provider omits ids on continuation chunks."""
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="multi", expected_output="y")]

    payload = _ExecuteStepResult(
        events=[],
        step_result=StepExecutionRecord(
            step_id="s1",
            success=True,
            outcome={"type": "code_exec"},
            duration_ms=5,
            thread_id="t1",
            tool_call_count=2,
        ),
        messages=[
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {"name": "run_command", "args": "", "id": "a", "index": 0},
                    {"name": "read_file", "args": "", "id": "b", "index": 1},
                ],
            ),
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {"name": None, "args": '{"command": "wc -l"}', "id": None, "index": 0},
                    {"name": None, "args": '{"path": "pyproject.toml"}', "id": None, "index": 1},
                ],
            ),
            AIMessage(content=""),
        ],
        delegate_final="",
        output="",
    )
    ex._update_prior_progress(state, steps, [payload])

    d = state.prior_progress
    assert [t.name for t in d.tool_calls] == ["run_command", "read_file"]
    assert d.tool_calls[0].head == "wc -l"
    assert d.tool_calls[1].head == "pyproject.toml"


def test_streamed_chunks_without_ids_fall_back_to_index() -> None:
    """Some providers omit ``id`` on continuation chunks; ``index`` keys the group."""
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="no ids", expected_output="y")]

    payload = _ExecuteStepResult(
        events=[],
        step_result=StepExecutionRecord(
            step_id="s1",
            success=True,
            outcome={"type": "code_exec"},
            duration_ms=5,
            thread_id="t1",
            tool_call_count=1,
        ),
        messages=[
            AIMessageChunk(
                content="",
                tool_call_chunks=[{"name": "read_file", "args": "", "id": None, "index": 0}],
            ),
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {"name": None, "args": '{"path": "README.md"}', "id": None, "index": 0}
                ],
            ),
            AIMessage(content=""),
        ],
        delegate_final="",
        output="",
    )
    ex._update_prior_progress(state, steps, [payload])
    assert state.prior_progress.tool_calls[0].name == "read_file"
    assert state.prior_progress.tool_calls[0].head == "README.md"


def test_called_from_append_parallel_wave_ledger() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="x", expected_output="y")]
    payloads = [
        _ok_payload(
            final_text="found 1234",
            tool_calls=[{"name": "run_command", "args": {"command": "x"}, "id": "a"}],
        )
    ]
    ex._append_parallel_wave_ledger(state, steps, payloads)
    assert state.prior_progress is not None
    assert state.prior_progress.steps_completed == 1
    assert state.prior_progress.tool_calls[0].name == "run_command"


def test_step_summary_truncates_long_full_description() -> None:
    """WaveStepProgress.description is capped at 500 chars (RFC-227 digest)."""
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=1)
    long_brief = "In ws_command_client.py, " + ("detail " * 200)
    assert len(long_brief) > 500
    steps = [
        StepAction(
            id="KBE-02",
            description="short label",
            full_description=long_brief,
            expected_output="done",
        )
    ]
    ex._update_prior_progress(state, steps, [_ok_payload(step_id="KBE-02")])
    assert state.prior_progress is not None
    summary = state.prior_progress.step_summaries[0]
    assert len(summary.description) == 500
    assert summary.description == long_brief[:500]

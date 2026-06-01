"""Unit tests for Executor._update_prior_progress (RFC-227)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from soothe.core.loop.engine.executor import Executor
from soothe.core.loop.state.schemas import LoopState, StepAction, StepResult


def _make_ok_payload(
    *,
    step_id: str = "s1",
    ai_text: str = "ok",
    tool_messages: list[ToolMessage] | None = None,
    delegate_final: str = "",
) -> tuple:
    """Build a successful payload tuple matching gather_results format."""
    messages = list(tool_messages or [])
    messages.append(AIMessage(content=ai_text))
    return (
        [],
        StepResult(
            step_id=step_id,
            success=True,
            outcome={"type": "generic"},
            duration_ms=10,
            thread_id="t1",
            tool_call_count=len(messages),
        ),
        messages,
        delegate_final,
    )


def _make_failed_payload(step_id: str = "s1", error: str = "boom") -> tuple:
    return (
        [],
        StepResult(
            step_id=step_id,
            success=False,
            outcome={"type": "error", "error": error},
            error=error,
            error_type="execution",
            duration_ms=1,
            thread_id="t1",
        ),
        [AIMessage(content=f"failed: {error}")],
        "",
    )


def _executor() -> Executor:
    return Executor(object(), max_parallel_steps=4)


def test_all_success_with_digit_evidence_hint_high() -> None:
    ex = _executor()
    state = LoopState(goal="count", thread_id="t1", iteration=1)
    steps = [
        StepAction(id="s1", description="count py", expected_output="n"),
        StepAction(id="s2", description="count json", expected_output="n"),
    ]
    payloads = [
        _make_ok_payload(
            step_id="s1",
            ai_text="Counted .py files: 1139",
            tool_messages=[ToolMessage(content="1139", tool_call_id="a", name="run_command")],
        ),
        _make_ok_payload(
            step_id="s2",
            ai_text="Counted .json files: 665",
            tool_messages=[ToolMessage(content="665", tool_call_id="b", name="run_command")],
        ),
    ]

    ex._update_prior_progress(state, steps, payloads)

    d = state.prior_progress
    assert d is not None
    assert d.iteration == 1
    assert d.wave_index == 0
    assert d.steps_completed == 2
    assert d.steps_failed == 0
    assert d.derived_progress_hint == "high"
    assert [t.name for t in d.tool_calls] == ["run_command", "run_command"]
    assert d.tool_calls[0].head == "1139"
    assert any("1139" in e for e in d.evidence_excerpts)


def test_all_success_no_signal_hint_medium() -> None:
    ex = _executor()
    state = LoopState(goal="think", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="ponder", expected_output="thoughts")]
    payloads = [
        _make_ok_payload(
            step_id="s1",
            ai_text="ok then continuing onward without specifics here",
            tool_messages=[ToolMessage(content="...", tool_call_id="a", name="run_command")],
        ),
    ]

    ex._update_prior_progress(state, steps, payloads)
    assert state.prior_progress is not None
    assert state.prior_progress.derived_progress_hint == "medium"


def test_any_failure_hint_low() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=2)
    steps = [
        StepAction(id="s1", description="x", expected_output="y"),
        StepAction(id="s2", description="z", expected_output="w"),
    ]
    payloads = [
        _make_ok_payload(
            step_id="s1",
            ai_text="Done; total 1234 found",
            tool_messages=[ToolMessage(content="1234", tool_call_id="a", name="run_command")],
        ),
        _make_failed_payload(step_id="s2", error="disk full"),
    ]
    ex._update_prior_progress(state, steps, payloads)
    assert state.prior_progress is not None
    assert state.prior_progress.steps_completed == 1
    assert state.prior_progress.steps_failed == 1
    assert state.prior_progress.derived_progress_hint == "low"


def test_no_tools_no_text_hint_none() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="nothing happens", expected_output="ok")]
    payloads = [
        _make_ok_payload(step_id="s1", ai_text="", tool_messages=None, delegate_final=""),
    ]
    ex._update_prior_progress(state, steps, payloads)
    assert state.prior_progress is not None
    assert state.prior_progress.derived_progress_hint == "none"
    assert state.prior_progress.tool_calls == []
    assert state.prior_progress.evidence_excerpts == []


def test_tool_heads_capped_at_8() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="many tools", expected_output="x")]
    many_tools = [
        ToolMessage(content=f"line {i}", tool_call_id=f"c{i}", name="run_command")
        for i in range(12)
    ]
    payloads = [_make_ok_payload(step_id="s1", ai_text="ok", tool_messages=many_tools)]
    ex._update_prior_progress(state, steps, payloads)
    assert len(state.prior_progress.tool_calls) == 8
    # First 8 in arrival order
    assert state.prior_progress.tool_calls[0].head == "line 0"
    assert state.prior_progress.tool_calls[7].head == "line 7"


def test_tool_head_first_line_and_truncation() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="x", expected_output="y")]
    long = "first line is here\n" + "extra\n" * 50
    payloads = [
        _make_ok_payload(
            step_id="s1",
            ai_text="ok",
            tool_messages=[ToolMessage(content=long, tool_call_id="a", name="run_command")],
        )
    ]
    ex._update_prior_progress(state, steps, payloads)
    assert state.prior_progress.tool_calls[0].head == "first line is here"

    # 200-char first-line case: caps at 120.
    huge_line = "x" * 300
    state2 = LoopState(goal="g", thread_id="t1", iteration=0)
    payloads2 = [
        _make_ok_payload(
            step_id="s1",
            ai_text="ok",
            tool_messages=[ToolMessage(content=huge_line, tool_call_id="a", name="run_command")],
        )
    ]
    ex._update_prior_progress(state2, steps, payloads2)
    assert len(state2.prior_progress.tool_calls[0].head) == 120


def test_evidence_excerpts_dedupe_and_cap() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id=f"s{i}", description=f"step {i}", expected_output="y") for i in range(5)]
    # First two steps share the same 64-char prefix (dedupe target); last three differ.
    shared = "A" * 64 + " (shared prefix step)"
    payloads = [
        _make_ok_payload(step_id="s0", ai_text=shared + " one"),
        _make_ok_payload(step_id="s1", ai_text=shared + " two"),
        _make_ok_payload(step_id="s2", ai_text="B" * 64 + " different two"),
        _make_ok_payload(step_id="s3", ai_text="C" * 64 + " different three"),
        _make_ok_payload(step_id="s4", ai_text="D" * 64 + " different four"),
    ]
    ex._update_prior_progress(state, steps, payloads)
    # 4 unique prefixes → trimmed to last 3.
    assert len(state.prior_progress.evidence_excerpts) == 3
    # Last entry must be the most recent unique one (s4).
    assert state.prior_progress.evidence_excerpts[-1].startswith("DDDD")


def test_excerpt_truncated_at_200_chars() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="x", expected_output="y")]
    long_ai = "Q" * 500
    payloads = [
        _make_ok_payload(
            step_id="s1",
            ai_text=long_ai,
            tool_messages=[ToolMessage(content="ok", tool_call_id="a", name="run_command")],
        )
    ]
    ex._update_prior_progress(state, steps, payloads)
    assert len(state.prior_progress.evidence_excerpts[0]) == 200


def test_overwrites_each_wave_and_increments_wave_index_within_iteration() -> None:
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=1)
    steps = [StepAction(id="s1", description="x", expected_output="y")]

    ex._update_prior_progress(state, steps, [_make_ok_payload(ai_text="first wave 42")])
    assert state.prior_progress.wave_index == 0
    assert state.prior_progress.evidence_excerpts[0].startswith("first wave 42")

    ex._update_prior_progress(state, steps, [_make_ok_payload(ai_text="second wave 99")])
    assert state.prior_progress.wave_index == 1
    assert state.prior_progress.evidence_excerpts[0].startswith("second wave 99")

    # New iteration resets wave index to 0.
    state.iteration = 2
    ex._update_prior_progress(state, steps, [_make_ok_payload(ai_text="iter2 wave0")])
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
        _make_ok_payload(step_id="s1", ai_text="ok 5"),
        RuntimeError("crashed"),
    ]
    ex._update_prior_progress(state, steps, payloads)
    assert state.prior_progress.steps_completed == 1
    assert state.prior_progress.steps_failed == 1
    assert state.prior_progress.derived_progress_hint == "low"


def test_called_from_append_parallel_wave_ledger() -> None:
    """Smoke test: _append_parallel_wave_ledger ends by populating prior_progress."""
    ex = _executor()
    state = LoopState(goal="g", thread_id="t1", iteration=0)
    steps = [StepAction(id="s1", description="x", expected_output="y")]
    payloads = [_make_ok_payload(ai_text="found 1234")]
    ex._append_parallel_wave_ledger(state, steps, payloads)
    assert state.prior_progress is not None
    assert state.prior_progress.iteration == 0
    assert state.prior_progress.steps_completed == 1

"""Tests for synthesis policy (IG-199, IG-296)."""

from soothe.cognition.agent_loop.policies.synthesis_policy import (
    assemble_assistant_text_from_stream_messages,
    evidence_requires_final_synthesis,
    needs_final_thread_synthesis,
    should_return_goal_completion_directly,
)
from soothe.cognition.agent_loop.state.schemas import LoopState, PlanResult, StepResult


def _plan_done() -> PlanResult:
    return PlanResult(
        status="done",
        evidence_summary="ev",
        goal_progress=1.0,
        confidence=0.9,
        reasoning="",
        next_action="done",
        plan_action="new",
    )


def _heavy_step_results(count: int) -> list[StepResult]:
    """Enough generic outcomes that total evidence length exceeds synthesis threshold."""
    out: list[StepResult] = []
    for i in range(count):
        out.append(
            StepResult(
                step_id=f"s{i}",
                success=True,
                outcome={"type": "unknown", "tool_name": "tool", "size_bytes": 1000},
                duration_ms=1,
                thread_id="t",
            )
        )
    return out


def test_evidence_requires_final_synthesis_heavy_run() -> None:
    """Many successful steps with sufficient total evidence should request synthesis."""
    state = LoopState(
        goal="g",
        thread_id="t",
        step_results=_heavy_step_results(16),
    )
    assert evidence_requires_final_synthesis(state, _plan_done()) is True


def test_evidence_requires_final_synthesis_light_run() -> None:
    """Single-step runs should not satisfy evidence heuristics."""
    state = LoopState(
        goal="g",
        thread_id="t",
        step_results=[
            StepResult(
                step_id="a",
                success=True,
                outcome={"type": "unknown", "tool_name": "tool", "size_bytes": 1},
                duration_ms=1,
                thread_id="t",
            )
        ],
    )
    assert evidence_requires_final_synthesis(state, _plan_done()) is False


def test_needs_final_always_modes() -> None:
    """Config overrides bypass adaptive heuristics."""
    state = LoopState(goal="g", thread_id="t", step_results=[])
    pr = _plan_done()
    assert needs_final_thread_synthesis(state, pr, "always_synthesize") is True
    assert needs_final_thread_synthesis(state, pr, "always_last_execute") is False


def test_needs_final_adaptive_parallel_multi_forces_synthesis() -> None:
    state = LoopState(
        goal="g",
        thread_id="t",
        step_results=[],
        last_execute_wave_parallel_multi_step=True,
        last_execute_assistant_text="from execute",
    )
    assert needs_final_thread_synthesis(state, _plan_done(), "adaptive") is True


def test_needs_final_adaptive_subagent_cap_forces_synthesis() -> None:
    state = LoopState(
        goal="g",
        thread_id="t",
        step_results=[],
        last_wave_hit_subagent_cap=True,
        last_execute_assistant_text="from execute",
    )
    assert needs_final_thread_synthesis(state, _plan_done(), "adaptive") is True


def test_needs_final_adaptive_reuse_when_light_with_assistant() -> None:
    state = LoopState(
        goal="g",
        thread_id="t",
        step_results=[
            StepResult(
                step_id="a",
                success=True,
                outcome={"type": "unknown", "tool_name": "tool", "size_bytes": 1},
                duration_ms=1,
                thread_id="t",
            )
        ],
        last_execute_assistant_text="answer",
        last_execute_wave_parallel_multi_step=False,
        last_wave_hit_subagent_cap=False,
    )
    assert needs_final_thread_synthesis(state, _plan_done(), "adaptive") is False


def test_needs_final_adaptive_empty_assistant_requests_synthesis() -> None:
    state = LoopState(
        goal="g",
        thread_id="t",
        step_results=[
            StepResult(
                step_id="a",
                success=True,
                outcome={"type": "unknown", "tool_name": "tool", "size_bytes": 1},
                duration_ms=1,
                thread_id="t",
            )
        ],
        last_execute_assistant_text=None,
    )
    assert needs_final_thread_synthesis(state, _plan_done(), "adaptive") is True


def test_assemble_assistant_prefers_chunk_stream_over_final_message() -> None:
    from langchain_core.messages import AIMessage, AIMessageChunk

    messages = [
        AIMessageChunk(content="hel"),
        AIMessageChunk(content="lo"),
        AIMessage(content=""),
    ]
    assert assemble_assistant_text_from_stream_messages(messages) == "hello"


def test_direct_goal_completion_prefers_rich_execute_text_even_when_evidence_heavy() -> None:
    state = LoopState(
        goal="g",
        thread_id="t",
        step_results=_heavy_step_results(16),
        last_execute_assistant_text=(
            "## Result\n\n"
            "Here are the first 10 lines:\n\n"
            "```\n"
            "1 line one\n2 line two\n3 line three\n4 line four\n5 line five\n"
            "```\n"
        ),
        last_execute_wave_parallel_multi_step=False,
        last_wave_hit_subagent_cap=False,
    )
    assert (
        should_return_goal_completion_directly(
            state,
            _plan_done(),
            "adaptive",
            response_length_category="standard",
        )
        is True
    )


def test_direct_goal_completion_respects_always_synthesize_mode() -> None:
    state = LoopState(
        goal="g",
        thread_id="t",
        step_results=[],
        last_execute_assistant_text="Ready answer from execute phase.",
    )
    assert (
        should_return_goal_completion_directly(
            state,
            _plan_done(),
            "always_synthesize",
            response_length_category="brief",
        )
        is False
    )


def test_direct_goal_completion_always_last_execute_with_text() -> None:
    """``always_last_execute`` direct-returns whenever Execute text is present."""
    state = LoopState(
        goal="g",
        thread_id="t",
        step_results=_heavy_step_results(16),  # evidence would normally veto
        last_execute_assistant_text="Short note.",
        last_execute_wave_parallel_multi_step=True,  # heuristics would normally veto
        last_wave_hit_subagent_cap=True,
    )
    assert (
        should_return_goal_completion_directly(
            state,
            _plan_done(),
            "always_last_execute",
            response_length_category="comprehensive",
        )
        is True
    )


def test_direct_goal_completion_always_last_execute_empty_text_falls_back() -> None:
    """``always_last_execute`` with no Execute text cannot direct-return; caller uses summary."""
    state = LoopState(
        goal="g",
        thread_id="t",
        step_results=[],
        last_execute_assistant_text=None,
    )
    assert (
        should_return_goal_completion_directly(
            state,
            _plan_done(),
            "always_last_execute",
        )
        is False
    )


def test_direct_goal_completion_vetoes_on_parallel_multi_step_wave() -> None:
    state = LoopState(
        goal="g",
        thread_id="t",
        step_results=_heavy_step_results(16),
        last_execute_assistant_text="Some execute text that looks plausible enough.",
        last_execute_wave_parallel_multi_step=True,
    )
    assert (
        should_return_goal_completion_directly(
            state,
            _plan_done(),
            "adaptive",
            response_length_category="standard",
        )
        is False
    )


def test_direct_goal_completion_vetoes_on_subagent_cap_hit() -> None:
    state = LoopState(
        goal="g",
        thread_id="t",
        step_results=_heavy_step_results(16),
        last_execute_assistant_text="Some execute text that looks plausible enough.",
        last_wave_hit_subagent_cap=True,
    )
    assert (
        should_return_goal_completion_directly(
            state,
            _plan_done(),
            "adaptive",
            response_length_category="standard",
        )
        is False
    )


def test_direct_goal_completion_rejects_short_plain_text_under_evidence_heavy_run() -> None:
    """Short prose without code fences / list structure is insufficient for direct return."""
    state = LoopState(
        goal="g",
        thread_id="t",
        step_results=_heavy_step_results(16),
        last_execute_assistant_text="Task looks done to me.",  # ~6 words, no structure
        last_execute_wave_parallel_multi_step=False,
        last_wave_hit_subagent_cap=False,
    )
    assert (
        should_return_goal_completion_directly(
            state,
            _plan_done(),
            "adaptive",
            response_length_category="standard",  # 300 word floor
        )
        is False
    )


def test_direct_goal_completion_rejects_when_no_overlap_with_plan_output() -> None:
    """If planner full_output shares no substantive tokens with Execute text, veto direct return."""
    plan = PlanResult(
        status="done",
        evidence_summary="ev",
        goal_progress=1.0,
        confidence=0.9,
        reasoning="",
        next_action="done",
        plan_action="new",
        full_output=(
            "Sensor readings have been collected across dormitory rooms and uploaded to "
            "archive cluster Tango for reconciliation with baseline."
        ),
    )
    rich_but_off_topic = " ".join(["apple banana mango pear grape orange berry melon"] * 40)
    state = LoopState(
        goal="g",
        thread_id="t",
        step_results=_heavy_step_results(16),  # heavy → evidence heuristic fires
        last_execute_assistant_text=rich_but_off_topic,
    )
    assert (
        should_return_goal_completion_directly(
            state,
            plan,
            "adaptive",
            response_length_category="standard",
        )
        is False
    )

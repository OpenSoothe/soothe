"""Tests for adaptive AgentLoop final response policy (IG-199)."""

from soothe.cognition.agent_loop.final_response_policy import (
    assemble_assistant_text_from_stream_messages,
    needs_final_thread_synthesis,
)
from soothe.cognition.agent_loop.schemas import LoopState, PlanResult, StepResult
from soothe.cognition.agent_loop.synthesis import evidence_requires_final_synthesis


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

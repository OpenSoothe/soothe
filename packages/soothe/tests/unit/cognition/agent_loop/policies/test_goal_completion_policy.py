"""Unit tests for goal completion hybrid policy (IG-298)."""

from __future__ import annotations

import pytest

from soothe.cognition.agent_loop.policies.goal_completion_policy import (
    _COMPLEX_WAVE_THRESHOLD,
    _heuristic_requires_goal_completion,
    determine_goal_completion_needs,
)
from soothe.cognition.agent_loop.state.schemas import (
    AgentDecision,
    LoopState,
    StepAction,
    StepResult,
)


def mock_loop_state(**kwargs) -> LoopState:
    """Create mock LoopState with default values."""
    defaults = {
        "goal": "test goal",
        "thread_id": "test-thread",
        "iteration": 0,
        "step_results": [],
        "last_execute_wave_parallel_multi_step": False,
        "last_wave_hit_subagent_cap": False,
        "last_execute_assistant_text": "",
        "current_decision": None,
    }
    return LoopState(**{**defaults, **kwargs})


def test_llm_only_mode_true():
    """LLM-only mode should trust LLM decision True."""
    state = mock_loop_state()
    result = determine_goal_completion_needs(llm_decision=True, state=state, mode="llm_only")
    assert result is True


def test_llm_only_mode_false():
    """LLM-only mode should trust LLM decision False."""
    state = mock_loop_state()
    result = determine_goal_completion_needs(llm_decision=False, state=state, mode="llm_only")
    assert result is False


def test_heuristic_only_mode_parallel_multi_step():
    """Heuristic-only mode should check execution complexity."""
    state = mock_loop_state(last_execute_wave_parallel_multi_step=True)
    result = determine_goal_completion_needs(llm_decision=False, state=state, mode="heuristic_only")
    assert result is True


def test_hybrid_mode_llm_true_honored():
    """Hybrid mode should honor LLM=True without checking heuristics."""
    state = mock_loop_state()
    # LLM=True, heuristic would return False (simple execution)
    result = determine_goal_completion_needs(llm_decision=True, state=state, mode="hybrid")
    assert result is True


def test_hybrid_mode_llm_false_heuristic_true():
    """Hybrid mode should use heuristic fallback when LLM=False."""
    state = mock_loop_state(last_execute_wave_parallel_multi_step=True)
    # LLM=False, but heuristic=True due to execution complexity
    result = determine_goal_completion_needs(llm_decision=False, state=state, mode="hybrid")
    assert result is True


def test_hybrid_mode_both_false():
    """Hybrid mode should return False when both LLM and heuristic agree."""
    state = mock_loop_state(
        iteration=0, step_results=[], last_execute_wave_parallel_multi_step=False
    )
    # LLM=False, heuristic=False (simple execution)
    result = determine_goal_completion_needs(llm_decision=False, state=state, mode="hybrid")
    assert result is False


def test_heuristic_parallel_multi_step():
    """Parallel multi-step execution requires synthesis."""
    state = mock_loop_state(last_execute_wave_parallel_multi_step=True)
    result = _heuristic_requires_goal_completion(state)
    assert result is True


def test_heuristic_subagent_cap():
    """Subagent cap hit requires synthesis."""
    state = mock_loop_state(last_wave_hit_subagent_cap=True)
    result = _heuristic_requires_goal_completion(state)
    assert result is True


def test_heuristic_multi_wave():
    """Multi-wave execution (≥2 iterations) requires synthesis."""
    state = mock_loop_state(iteration=_COMPLEX_WAVE_THRESHOLD)
    result = _heuristic_requires_goal_completion(state)
    assert result is True


def test_heuristic_single_wave():
    """Single wave execution does not require synthesis (simple case)."""
    state = mock_loop_state(iteration=1)
    result = _heuristic_requires_goal_completion(state)
    assert result is False


def test_heuristic_many_steps():
    """Many steps (≥3) requires synthesis."""
    step_results = [
        StepResult(step_id="S1", success=True, outcome={}, duration_ms=100, thread_id="t1"),
        StepResult(step_id="S2", success=True, outcome={}, duration_ms=100, thread_id="t1"),
        StepResult(step_id="S3", success=True, outcome={}, duration_ms=100, thread_id="t1"),
    ]
    state = mock_loop_state(step_results=step_results)
    result = _heuristic_requires_goal_completion(state)
    assert result is True


def test_heuristic_few_steps():
    """Few steps (<3) does not require synthesis (simple case)."""
    step_results = [
        StepResult(step_id="S1", success=True, outcome={}, duration_ms=100, thread_id="t1"),
    ]
    state = mock_loop_state(step_results=step_results)
    result = _heuristic_requires_goal_completion(state)
    assert result is False


def test_heuristic_dag_dependencies():
    """DAG dependencies (≥2) requires synthesis."""
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="S1", description="Step 1", dependencies=["S0", "S2"]),  # 2 dependencies
            StepAction(id="S2", description="Step 2", dependencies=[]),
        ],
        execution_mode="dependency",
    )
    state = mock_loop_state(current_decision=decision)
    result = _heuristic_requires_goal_completion(state)
    assert result is True


def test_heuristic_no_dependencies():
    """No DAG dependencies does not require synthesis."""
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="S1", description="Step 1", dependencies=[]),
            StepAction(id="S2", description="Step 2", dependencies=[]),
        ],
        execution_mode="parallel",
    )
    state = mock_loop_state(current_decision=decision)
    result = _heuristic_requires_goal_completion(state)
    assert result is False


def test_heuristic_failed_steps_low_success_rate():
    """Failed steps with low success rate (<70%) requires synthesis."""
    step_results = [
        StepResult(step_id="S1", success=True, outcome={}, duration_ms=100, thread_id="t1"),
        StepResult(
            step_id="S2", success=False, outcome={}, error="Error", duration_ms=100, thread_id="t1"
        ),
    ]
    # Success rate = 50% < 70% threshold
    state = mock_loop_state(step_results=step_results)
    result = _heuristic_requires_goal_completion(state)
    assert result is True


def test_heuristic_failed_steps_high_success_rate():
    """Failed steps with high success rate (≥70%) does not require synthesis."""
    step_results = [
        StepResult(step_id="S1", success=True, outcome={}, duration_ms=100, thread_id="t1"),
        StepResult(step_id="S2", success=True, outcome={}, duration_ms=100, thread_id="t1"),
        StepResult(step_id="S3", success=True, outcome={}, duration_ms=100, thread_id="t1"),
        StepResult(
            step_id="S4", success=False, outcome={}, error="Error", duration_ms=100, thread_id="t1"
        ),
    ]
    # Success rate = 75% ≥ 70% threshold
    state = mock_loop_state(step_results=step_results)
    result = _heuristic_requires_goal_completion(state)
    assert result is False


def test_heuristic_step_diversity():
    """Multiple execution types (≥2) requires synthesis."""
    step_results = [
        StepResult(
            step_id="S1",
            success=True,
            outcome={"type": "file_read"},
            duration_ms=100,
            thread_id="t1",
        ),
        StepResult(
            step_id="S2",
            success=True,
            outcome={"type": "web_search"},
            duration_ms=100,
            thread_id="t1",
        ),
    ]
    # 2 different outcome types
    state = mock_loop_state(step_results=step_results)
    result = _heuristic_requires_goal_completion(state)
    assert result is True


def test_heuristic_single_execution_type():
    """Single execution type does not require synthesis."""
    step_results = [
        StepResult(
            step_id="S1",
            success=True,
            outcome={"type": "file_read"},
            duration_ms=100,
            thread_id="t1",
        ),
        StepResult(
            step_id="S2",
            success=True,
            outcome={"type": "file_read"},
            duration_ms=100,
            thread_id="t1",
        ),
    ]
    # All same outcome type
    state = mock_loop_state(step_results=step_results)
    result = _heuristic_requires_goal_completion(state)
    assert result is False


def test_heuristic_combined_complexity():
    """Combined complexity indicators should trigger synthesis."""
    state = mock_loop_state(
        iteration=2,  # Multi-wave
        last_execute_wave_parallel_multi_step=True,  # Parallel execution
        step_results=[
            StepResult(
                step_id="S1",
                success=True,
                outcome={"type": "file_read"},
                duration_ms=100,
                thread_id="t1",
            ),
            StepResult(
                step_id="S2",
                success=True,
                outcome={"type": "web_search"},
                duration_ms=100,
                thread_id="t1",
            ),
        ],
    )
    # Multiple complexity indicators present
    result = _heuristic_requires_goal_completion(state)
    assert result is True


def test_heuristic_simple_execution():
    """Simple execution (no complexity indicators) should not require synthesis."""
    step_results = [
        StepResult(
            step_id="S1",
            success=True,
            outcome={"type": "file_read"},
            duration_ms=100,
            thread_id="t1",
        ),
    ]
    state = mock_loop_state(
        iteration=0,
        step_results=step_results,
        last_execute_wave_parallel_multi_step=False,
        last_wave_hit_subagent_cap=False,
        current_decision=None,
    )
    # All simple execution indicators
    result = _heuristic_requires_goal_completion(state)
    assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

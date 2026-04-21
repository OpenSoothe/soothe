"""Tests for RFC-200 and RFC-609 multi-goal enhancement models."""

from datetime import UTC, datetime

from soothe.cognition.goal_engine.models import (
    BackoffDecision,
    ContextConstructionOptions,
    EvidenceBundle,
    Goal,
    GoalSubDAGStatus,
)


def test_evidence_bundle_creation():
    """Test EvidenceBundle model creation and validation."""
    evidence = EvidenceBundle(
        structured={"wave_count": 3, "step_count": 12, "error_count": 2},
        narrative="Goal execution failed after 3 waves with authentication errors",
        source="layer2_execute",
    )

    assert evidence.structured["wave_count"] == 3
    assert evidence.structured["step_count"] == 12
    assert evidence.narrative == "Goal execution failed after 3 waves with authentication errors"
    assert evidence.source == "layer2_execute"
    assert evidence.timestamp is not None


def test_backoff_decision_creation():
    """Test BackoffDecision model creation."""
    decision = BackoffDecision(
        backoff_to_goal_id="goal_001",
        reason="Authentication failure suggests dependency goal needs re-execution",
        new_directives=[],
        evidence_summary="Auth dependency failed",
    )

    assert decision.backoff_to_goal_id == "goal_001"
    assert "Authentication" in decision.reason
    assert decision.new_directives == []
    assert decision.evidence_summary == "Auth dependency failed"


def test_goal_sub_dag_status_creation():
    """Test GoalSubDAGStatus model creation."""
    status = GoalSubDAGStatus(
        execution_states={
            "goal_001": "success",
            "goal_002": "failed",
            "goal_003": "pending",
        },
        backoff_points=["goal_001"],
        evidence_annotations={},
    )

    assert status.execution_states["goal_001"] == "success"
    assert status.execution_states["goal_002"] == "failed"
    assert len(status.backoff_points) == 1
    assert status.backoff_points[0] == "goal_001"


def test_context_construction_options_defaults():
    """Test ContextConstructionOptions default values."""
    options = ContextConstructionOptions()

    assert options.include_same_goal_threads == True
    assert options.include_similar_goals == True
    assert options.thread_selection_strategy == "latest"
    assert options.similarity_threshold == 0.7


def test_context_construction_options_validation():
    """Test ContextConstructionOptions field validation."""
    # Test similarity_threshold bounds
    options = ContextConstructionOptions(similarity_threshold=0.85)
    assert options.similarity_threshold == 0.85

    # Test strategy values
    options = ContextConstructionOptions(thread_selection_strategy="all")
    assert options.thread_selection_strategy == "all"

    options = ContextConstructionOptions(thread_selection_strategy="best_performing")
    assert options.thread_selection_strategy == "best_performing"


def test_evidence_bundle_with_goal_failure():
    """Test EvidenceBundle construction from goal execution context."""
    # Simulate Layer 2 execution metrics
    execution_metrics = {
        "wave_count": 4,
        "step_count": 15,
        "subagent_calls": 3,
        "tool_calls": 12,
        "error_count": 1,
        "iteration_number": 2,
    }

    narrative_text = (
        "Goal 'Setup authentication system' failed after 4 waves. "
        "Root cause: Invalid credentials in environment variables. "
        "Dependency goal 'Load environment config' may need re-execution."
    )

    evidence = EvidenceBundle(
        structured=execution_metrics,
        narrative=narrative_text,
        source="layer2_execute",
    )

    assert evidence.structured["wave_count"] == 4
    assert evidence.structured["subagent_calls"] == 3
    assert "Setup authentication system" in evidence.narrative
    assert "Invalid credentials" in evidence.narrative
    assert evidence.source == "layer2_execute"


def test_backoff_decision_with_directives():
    """Test BackoffDecision with goal directives."""
    decision = BackoffDecision(
        backoff_to_goal_id="goal_parent",
        reason="Systemic failure requires parent goal re-planning",
        new_directives=[
            {"action": "create_goal", "description": "Fix environment config"},
            {"action": "adjust_priority", "goal_id": "goal_002", "priority": 80},
        ],
        evidence_summary="Multiple goals failed due to config issue",
    )

    assert decision.backoff_to_goal_id == "goal_parent"
    assert len(decision.new_directives) == 2
    assert decision.new_directives[0]["action"] == "create_goal"
    assert decision.new_directives[1]["action"] == "adjust_priority"
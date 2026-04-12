"""Unit tests for Layer 2 AgentLoop schemas (RFC-0008)."""

from __future__ import annotations

import pytest

from soothe.cognition.agent_loop.schemas import (
    AgentDecision,
    LoopState,
    PlanResult,
    StepAction,
    StepResult,
)


class TestStepAction:
    """Tests for StepAction schema."""

    def test_step_action_creation(self):
        """Test basic StepAction creation."""
        step = StepAction(
            description="Test step",
            expected_output="Test output",
        )

        assert step.description == "Test step"
        assert step.expected_output == "Test output"
        assert step.tools is None
        assert step.subagent is None
        assert step.dependencies is None
        assert len(step.id) == 8  # Auto-generated ID

    def test_step_action_with_tools(self):
        """Test StepAction with tools."""
        step = StepAction(
            description="Use tools",
            tools=["read_file", "write_file"],
            expected_output="File operations complete",
        )

        assert step.tools == ["read_file", "write_file"]

    def test_step_action_with_dependencies(self):
        """Test StepAction with dependencies."""
        step = StepAction(
            id="step_2",
            description="Dependent step",
            expected_output="Result",
            dependencies=["step_1"],
        )

        assert step.dependencies == ["step_1"]


class TestAgentDecision:
    """Tests for AgentDecision schema."""

    def test_single_step_decision(self):
        """Test decision with single step."""
        step = StepAction(
            description="Single step",
            expected_output="Output",
        )
        decision = AgentDecision(
            type="execute_steps",
            steps=[step],
            execution_mode="sequential",
            reasoning="Simple task",
        )

        assert decision.type == "execute_steps"
        assert len(decision.steps) == 1
        assert decision.execution_mode == "sequential"
        assert decision.reasoning == "Simple task"

    def test_multi_step_decision(self):
        """Test decision with multiple steps."""
        steps = [StepAction(description=f"Step {i}", expected_output="Output") for i in range(3)]
        decision = AgentDecision(
            type="execute_steps",
            steps=steps,
            execution_mode="parallel",
            reasoning="Parallel execution",
        )

        assert len(decision.steps) == 3
        assert decision.execution_mode == "parallel"

    def test_decision_validation_no_steps(self):
        """Test that decision without steps raises error."""
        with pytest.raises(ValueError, match="execute_steps requires at least one step"):
            AgentDecision(
                type="execute_steps",
                steps=[],
                execution_mode="sequential",
                reasoning="Invalid",
            )

    def test_has_remaining_steps(self):
        """Test has_remaining_steps method."""
        step1 = StepAction(id="s1", description="Step 1", expected_output="O1")
        step2 = StepAction(id="s2", description="Step 2", expected_output="O2")

        decision = AgentDecision(
            type="execute_steps",
            steps=[step1, step2],
            execution_mode="sequential",
            reasoning="Test",
        )

        # No steps completed
        assert decision.has_remaining_steps(set()) is True

        # One step completed
        assert decision.has_remaining_steps({"s1"}) is True

        # All steps completed
        assert decision.has_remaining_steps({"s1", "s2"}) is False

    def test_get_ready_steps(self):
        """Test get_ready_steps with dependencies."""
        step1 = StepAction(id="s1", description="Step 1", expected_output="O1")
        step2 = StepAction(
            id="s2",
            description="Step 2",
            expected_output="O2",
            dependencies=["s1"],
        )
        step3 = StepAction(id="s3", description="Step 3", expected_output="O3")

        decision = AgentDecision(
            type="execute_steps",
            steps=[step1, step2, step3],
            execution_mode="dependency",
            reasoning="DAG execution",
        )

        # No steps completed - s1 and s3 ready
        ready = decision.get_ready_steps(set())
        assert len(ready) == 2
        ready_ids = {s.id for s in ready}
        assert ready_ids == {"s1", "s3"}

        # s1 completed - s2 becomes ready
        ready = decision.get_ready_steps({"s1"})
        assert len(ready) == 2
        ready_ids = {s.id for s in ready}
        assert ready_ids == {"s2", "s3"}

        # All completed
        ready = decision.get_ready_steps({"s1", "s2", "s3"})
        assert len(ready) == 0


class TestPlanResult:
    """Tests for PlanResult schema."""

    def test_reason_result_done_keep(self) -> None:
        """Test done result with plan_action keep."""
        result = PlanResult(
            status="done",
            plan_action="keep",
            next_action="I've completed the task.",
            goal_progress=1.0,
            confidence=0.95,
            reasoning="Goal achieved",
        )

        assert result.status == "done"
        assert result.goal_progress == 1.0
        assert result.confidence == 0.95
        assert result.is_done() is True

    def test_status_methods(self) -> None:
        """Test status check methods."""
        done = PlanResult(
            status="done",
            plan_action="keep",
            next_action="I'm done.",
            goal_progress=1.0,
            reasoning="Done",
        )
        assert done.is_done() is True
        assert done.should_continue() is False
        assert done.should_replan() is False

        cont = PlanResult(
            status="continue",
            plan_action="new",
            decision=AgentDecision(
                type="execute_steps",
                steps=[StepAction(description="s", expected_output="o")],
                execution_mode="sequential",
                reasoning="x",
            ),
            next_action="I'll continue working.",
            goal_progress=0.5,
            reasoning="Continue",
        )
        assert cont.should_continue() is True
        assert cont.is_done() is False

        replan = PlanResult(
            status="replan",
            plan_action="new",
            decision=AgentDecision(
                type="execute_steps",
                steps=[StepAction(description="s", expected_output="o")],
                execution_mode="sequential",
                reasoning="r",
            ),
            next_action="I'll replan.",
            goal_progress=0.3,
            reasoning="Replan",
        )
        assert replan.should_replan() is True

    def test_plan_action_validation(self) -> None:
        """Keep must not carry a decision; new requires decision when not done."""
        with pytest.raises(ValueError):
            PlanResult(
                status="continue",
                plan_action="keep",
                decision=AgentDecision(
                    type="execute_steps",
                    steps=[StepAction(description="s", expected_output="o")],
                    execution_mode="sequential",
                    reasoning="bad",
                ),
                reasoning="bad",
            )

        with pytest.raises(ValueError):
            PlanResult(
                status="continue",
                plan_action="new",
                decision=None,
                reasoning="bad",
            )

    def test_progress_validation(self) -> None:
        """Test goal_progress validation."""
        PlanResult(
            status="done",
            plan_action="keep",
            goal_progress=0.5,
            reasoning="Test",
        )

        with pytest.raises(ValueError):
            PlanResult(
                status="done",
                plan_action="keep",
                goal_progress=1.5,
                reasoning="Test",
            )


class TestStepResult:
    """Tests for StepResult schema."""

    def test_successful_step_result(self):
        """Test successful step result."""
        result = StepResult(
            step_id="s1",
            success=True,
            outcome={
                "type": "file_read",
                "tool_name": "read_file",
                "tool_call_id": "call_abc123",
                "success_indicators": {"lines": 100},
                "entities": ["file.txt"],
                "size_bytes": 1024,
            },
            duration_ms=150,
            thread_id="thread_1",
        )

        assert result.success is True
        assert result.outcome is not None
        assert result.outcome["type"] == "file_read"
        assert result.error is None

    def test_failed_step_result(self):
        """Test failed step result."""
        result = StepResult(
            step_id="s1",
            success=False,
            outcome={"type": "error", "error": "File not found"},
            error="File not found",
            error_type="execution",
            duration_ms=10,
            thread_id="thread_1",
        )

        assert result.success is False
        assert result.error == "File not found"
        assert result.error_type == "execution"

    def test_to_evidence_string_success(self):
        """Test evidence string for successful step."""
        result = StepResult(
            step_id="s1",
            success=True,
            outcome={
                "type": "file_read",
                "tool_name": "read_file",
                "tool_call_id": "call_abc123",
                "success_indicators": {"lines": 100, "files_found": 1},
                "entities": ["file.txt"],
                "size_bytes": 1024,
            },
            duration_ms=100,
            thread_id="t1",
        )

        evidence = result.to_evidence_string()
        assert "✓" in evidence
        assert "read_file" in evidence

    def test_to_evidence_string_failure(self):
        """Test evidence string for failed step."""
        result = StepResult(
            step_id="s1",
            success=False,
            error="Error occurred",
            duration_ms=10,
            thread_id="t1",
        )

        evidence = result.to_evidence_string()
        assert "✗" in evidence
        assert "Error: Error occurred" in evidence


class TestLoopState:
    """Tests for LoopState schema."""

    def test_loop_state_creation(self):
        """Test basic LoopState creation."""
        state = LoopState(
            goal="Test goal",
            thread_id="thread_1",
        )

        assert state.goal == "Test goal"
        assert state.thread_id == "thread_1"
        assert state.iteration == 0
        assert state.max_iterations == 8
        assert state.current_decision is None
        assert len(state.step_results) == 0

    def test_add_step_result(self):
        """Test adding step results."""
        state = LoopState(goal="Test", thread_id="t1")

        # Add successful result
        result1 = StepResult(
            step_id="s1",
            success=True,
            output="Output",
            duration_ms=100,
            thread_id="t1",
        )
        state.add_step_result(result1)

        assert len(state.step_results) == 1
        assert "s1" in state.completed_step_ids

        # Add failed result
        result2 = StepResult(
            step_id="s2",
            success=False,
            error="Failed",
            duration_ms=10,
            thread_id="t1",
        )
        state.add_step_result(result2)

        assert len(state.step_results) == 2
        assert "s2" not in state.completed_step_ids  # Failed steps not in completed set

    def test_has_remaining_steps(self):
        """Test has_remaining_steps with decision."""
        state = LoopState(goal="Test", thread_id="t1")

        # No decision
        assert state.has_remaining_steps() is False

        # With decision, no steps completed
        step = StepAction(id="s1", description="Step", expected_output="O")
        state.current_decision = AgentDecision(
            type="execute_steps",
            steps=[step],
            execution_mode="sequential",
            reasoning="Test",
        )

        assert state.has_remaining_steps() is True

        # Step completed
        state.completed_step_ids.add("s1")
        assert state.has_remaining_steps() is False

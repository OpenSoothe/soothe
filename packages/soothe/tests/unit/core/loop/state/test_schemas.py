"""Unit tests for Layer 2 StrangeLoop schemas (RFC-0008)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError
from soothe.foundation.sloop.engine.thread_selection import resolve_wire_subagent_for_step
from soothe.foundation.sloop.state import schemas as schemas_mod
from soothe.foundation.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanGenerateStep,
    PlanGeneration,
    PlanResult,
    StepAction,
    StepResult,
    allocate_plan_id,
    apply_step_wire_subagents,
    assign_plan_step_ids,
    composite_step_id,
    max_goal_step_numeric_suffix,
    next_goal_local_step_id_start,
    plan_generate_steps_to_step_actions,
    renumber_decision_local_step_ids_for_goal_continuation,
    resolve_step_wire_subagent,
    trailing_numeric_suffix_from_step_id,
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
        assert step.dependencies is None
        assert len(step.id) == 8  # Auto-generated ID

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
            execution_mode="parallel",
            reasoning="Simple task",
        )

        assert decision.type == "execute_steps"
        assert len(decision.steps) == 1
        assert decision.execution_mode == "parallel"
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
                execution_mode="parallel",
                reasoning="Invalid",
            )

    def test_has_remaining_steps(self):
        """Test has_remaining_steps method."""
        step1 = StepAction(id="s1", description="Step 1", expected_output="O1")
        step2 = StepAction(id="s2", description="Step 2", expected_output="O2")

        decision = AgentDecision(
            type="execute_steps",
            steps=[step1, step2],
            execution_mode="parallel",
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

    def test_composite_step_id_idempotent(self) -> None:
        """Already-scoped ids for the same plan are unchanged."""
        assert composite_step_id("KFA-001", "KFA") == "KFA-001"
        assert composite_step_id("001", "KFA") == "KFA-001"

    def test_assign_plan_step_ids_remaps_dependencies(self) -> None:
        """IG-303: preserve model suffix; in-plan dependency rewrite."""

        d0 = StepAction(
            id="001",
            description="First",
            expected_output="o",
        )
        d1 = StepAction(
            id="002",
            description="Second",
            expected_output="o",
            dependencies=["001"],
        )
        d2 = StepAction(
            id="003",
            description="Third",
            expected_output="o",
            dependencies=["002", "step_001"],
        )
        decision = AgentDecision(
            type="execute_steps",
            steps=[d0, d1, d2],
            execution_mode="parallel",
            reasoning="t",
        )
        out = assign_plan_step_ids(decision, plan_id="KFA")
        assert [s.id for s in out.steps] == ["KFA-001", "KFA-002", "KFA-003"]
        assert out.steps[0].dependencies is None
        assert out.steps[1].dependencies == ["KFA-001"]
        assert out.steps[2].dependencies == ["KFA-002", "step_001"]

    def test_assign_plan_step_ids_digit_alias_dependency_ig379(self) -> None:
        """Numeric dependency string maps to the unique digit-only step id (IG-379)."""
        d0 = StepAction(id="01", description="First", expected_output="o")
        d1 = StepAction(
            id="02",
            description="Second",
            expected_output="o",
            dependencies=["1"],
        )
        decision = AgentDecision(
            type="execute_steps",
            steps=[d0, d1],
            execution_mode="dependency",
            reasoning="t",
        )
        out = assign_plan_step_ids(decision, plan_id="ZZZ")
        assert out.steps[0].id == "ZZZ-01"
        assert out.steps[1].dependencies == ["ZZZ-01"]

    def test_assign_plan_step_ids_ambiguous_digit_dependency_untouched(self, caplog) -> None:
        """Two digit-only ids with the same int value: do not guess; leave dep unchanged."""
        import logging

        from soothe.foundation.sloop.state import schemas as schemas_mod

        d0 = StepAction(id="01", description="a", expected_output="o")
        d1 = StepAction(id="001", description="b", expected_output="o")
        d2 = StepAction(
            id="03",
            description="c",
            expected_output="o",
            dependencies=["1"],
        )
        decision = AgentDecision(
            type="execute_steps",
            steps=[d0, d1, d2],
            execution_mode="dependency",
            reasoning="t",
        )
        with caplog.at_level(logging.WARNING, logger=schemas_mod.logger.name):
            out = assign_plan_step_ids(decision, plan_id="ZZZ")
        assert out.steps[2].dependencies == ["1"]
        assert any("Ambiguous numeric dependency" in r.message for r in caplog.records)

    def test_assign_plan_step_ids_duplicate_composite_raises(self) -> None:
        """Model id 001 and already-scoped KFA-001 collapse under the same plan."""
        d0 = StepAction(id="001", description="a", expected_output="o")
        d1 = StepAction(id="KFA-001", description="b", expected_output="o")
        decision = AgentDecision(
            type="execute_steps",
            steps=[d0, d1],
            execution_mode="parallel",
            reasoning="t",
        )
        with pytest.raises(ValueError, match="duplicate composite"):
            assign_plan_step_ids(decision, plan_id="KFA")

    def test_allocate_plan_id_skips_reserved_composite(self) -> None:
        """First random plan id blocked by reserved composite; second attempt succeeds."""
        decision = AgentDecision(
            type="execute_steps",
            steps=[StepAction(id="001", description="x", expected_output="o")],
            execution_mode="parallel",
            reasoning="r",
        )
        reserved = {"KFA-001"}
        with patch.object(schemas_mod.secrets, "choice", side_effect=list("KFAZZZ")):
            pid = allocate_plan_id(decision, reserved_step_ids=reserved)
        assert pid == "ZZZ"
        scoped = assign_plan_step_ids(decision, plan_id=pid)
        assert scoped.steps[0].id == "ZZZ-001"

    def test_replan_collision_avoids_empty_ready_steps(self) -> None:
        """Scoped id must not equal a completed historical step id."""

        sr = StepResult(
            step_id="1",
            success=True,
            outcome={"type": "generic"},
            duration_ms=1,
            thread_id="t",
        )
        state = LoopState(goal="g", thread_id="t", step_results=[sr])
        new_step = StepAction(id="more", description="More work", expected_output="o")
        decision = AgentDecision(
            type="execute_steps",
            steps=[new_step],
            execution_mode="parallel",
            reasoning="r",
        )
        reserved = set(state.dependency_completion_ids())
        plan_id = allocate_plan_id(decision, reserved_step_ids=reserved)
        normalized = assign_plan_step_ids(decision, plan_id=plan_id)
        ready = normalized.get_ready_steps(state.dependency_completion_ids())
        assert len(ready) == 1
        assert ready[0].id not in reserved
        assert ready[0].id.endswith("-more")


class TestPlanResult:
    """Tests for PlanResult schema."""

    def test_reason_result_done_keep(self) -> None:
        """Test done result with plan_action keep."""
        result = PlanResult(
            status="done",
            plan_action="keep",
            next_action="I've completed the task.",
            goal_progress="complete",
            reasoning="Goal achieved",
        )

        assert result.status == "done"
        assert result.goal_progress == "complete"
        assert result.is_done() is True

    def test_status_methods(self) -> None:
        """Test status check methods."""
        done = PlanResult(
            status="done",
            plan_action="keep",
            next_action="I'm done.",
            goal_progress="complete",
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
                execution_mode="parallel",
                reasoning="x",
            ),
            next_action="I'll continue working.",
            goal_progress="medium",
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
                execution_mode="parallel",
                reasoning="r",
            ),
            next_action="I'll replan.",
            goal_progress="low",
            reasoning="Replan",
        )
        assert replan.should_replan() is True

    def test_plan_action_validation(self) -> None:
        """IG-264: Keep CAN have decision (optional); new requires decision when not done."""
        # IG-264: plan_action='keep' CAN have decision (no longer raises ValueError)
        # This validation was relaxed to allow optional decision when keeping

        # Still enforce: plan_action='new' requires decision when not done
        with pytest.raises(ValueError):
            PlanResult(
                status="continue",
                plan_action="new",
                decision=None,
                reasoning="bad",
                assessment_reasoning="",  # IG-264: Added
                plan_reasoning="",  # IG-264: Added
                next_action="test",  # IG-264: Added
            )

    def test_progress_validation(self) -> None:
        """Test goal_progress validation."""
        PlanResult(
            status="done",
            plan_action="keep",
            goal_progress="medium",
            reasoning="Test",
        )

        with pytest.raises(ValueError):
            PlanResult(
                status="done",
                plan_action="keep",
                goal_progress="invalid_level",  # Invalid level for testing validation
                reasoning="Test",
            )


class TestPlanGeneration:
    """Tests for flattened PlanGeneration schema."""

    def test_plan_generate_step_schema_includes_execution_routing(self) -> None:
        from soothe.foundation.sloop.state.schemas import plan_generation_model_for_iteration

        props = plan_generation_model_for_iteration(0).model_json_schema()["$defs"][
            "PlanGenerateStep"
        ]["properties"]
        assert "evidence_refs" not in props
        assert {
            "id",
            "description",
            "expected_output",
            "dependencies",
            "execution_hint",
            "subagent",
        } <= set(props.keys())

    def test_plan_generation_schema_execution_mode_excludes_sequential(self) -> None:
        """Structured plan-generate output must not offer sequential to the LLM."""
        from soothe.foundation.sloop.state.schemas import plan_generation_model_for_iteration

        for iteration in (0, 1):
            schema = plan_generation_model_for_iteration(iteration).model_json_schema()
            em = schema["properties"]["execution_mode"]
            enum_values: set[str] = set()
            if "enum" in em:
                enum_values.update(em["enum"])
            for variant in em.get("anyOf", []):
                if isinstance(variant, dict) and "enum" in variant:
                    enum_values.update(variant["enum"])
            assert enum_values <= {"parallel", "dependency", None} or enum_values <= {
                "parallel",
                "dependency",
            }
            assert "sequential" not in enum_values
        agent_em = AgentDecision.model_json_schema()["properties"]["execution_mode"]["enum"]
        assert set(agent_em) == {"parallel", "dependency"}

    def test_plan_generate_steps_convert_to_step_actions(self) -> None:
        steps = [
            PlanGenerateStep(
                id="01",
                description="Search papers",
                expected_output="List",
                dependencies=None,
                execution_hint="subagent",
                subagent="explore",
            )
        ]
        out = plan_generate_steps_to_step_actions(steps)
        assert len(out) == 1
        assert out[0].description == "Search papers"
        assert out[0].wire_subagent == "explore"
        assert "evidence_refs" not in StepAction.model_fields

    def test_resolve_step_wire_subagent(self) -> None:
        assert resolve_step_wire_subagent(execution_hint="auto") is None
        assert resolve_step_wire_subagent(execution_hint="subagent") == "explore"
        assert (
            resolve_step_wire_subagent(execution_hint="subagent", subagent="explore") == "explore"
        )

    def test_apply_step_wire_subagents(self) -> None:
        steps = [
            StepAction(
                id="s1",
                description="Recon",
                expected_output="map",
                execution_hint="subagent",
                subagent="explore",
            )
        ]
        wired = apply_step_wire_subagents(steps)
        assert wired[0].wire_subagent == "explore"

    def test_resolve_wire_subagent_for_step_prefers_planner_hint(self) -> None:
        step = StepAction(
            id="s1",
            description="Recon",
            expected_output="map",
            wire_subagent="explore",
        )
        routing = {"routing_hint": "subagent", "preferred_subagent": "tacitus"}
        assert resolve_wire_subagent_for_step(step, routing) == "explore"
        assert resolve_wire_subagent_for_step(step, None) == "explore"

    def test_resolve_wire_subagent_falls_back_to_routing(self) -> None:
        step = StepAction(id="s1", description="Recon", expected_output="map")
        routing = {"routing_hint": "subagent", "preferred_subagent": "explore"}
        assert resolve_wire_subagent_for_step(step, routing) == "explore"

    def test_new_requires_flattened_fields(self) -> None:
        """plan_action=new requires top-level decision fields."""
        with pytest.raises(ValidationError):
            PlanGeneration(plan_action="new", next_action="test")

    def test_new_final_allows_empty_steps(self) -> None:
        """type=final matches AgentDecision: no execute steps required."""
        out = PlanGeneration(
            plan_action="new",
            type="final",
            execution_mode="parallel",
            steps=[],
            next_action="Wrapping up.",
        )
        assert out.type == "final"
        assert out.steps == []

    def test_new_execute_steps_requires_steps(self) -> None:
        """type=execute_steps still requires at least one step."""
        with pytest.raises(ValidationError):
            PlanGeneration(
                plan_action="new",
                type="execute_steps",
                execution_mode="parallel",
                steps=[],
                next_action="x",
            )

    def test_new_defaults_execution_mode_when_omitted(self) -> None:
        """Omitted execution_mode defaults to parallel (common LLM omission for type=final)."""
        out = PlanGeneration(
            plan_action="new",
            type="final",
            steps=[],
            next_action="Done.",
        )
        assert out.execution_mode == "parallel"

    def test_new_execute_steps_defaults_execution_mode(self) -> None:
        """execute_steps accepts omitted execution_mode; steps are still required."""
        step = PlanGenerateStep(description="Do work", expected_output="ok")
        out = PlanGeneration(
            plan_action="new",
            type="execute_steps",
            steps=[step],
            next_action="Running.",
        )
        assert out.execution_mode == "parallel"

    def test_rejects_sequential_execution_mode(self) -> None:
        """Removed sequential mode is not accepted."""
        with pytest.raises(ValidationError):
            PlanGeneration(
                plan_action="new",
                type="execute_steps",
                steps=[PlanGenerateStep(description="x", expected_output="ok")],
                execution_mode="sequential",
                next_action="Run.",
            )
        with pytest.raises(ValidationError):
            AgentDecision(
                type="execute_steps",
                steps=[StepAction(id="s1", description="d", expected_output="ok")],
                execution_mode="sequential",
            )

    def test_keep_can_omit_decision_fields(self) -> None:
        """plan_action=keep does not require decision fields."""
        out = PlanGeneration(plan_action="keep", next_action="I will continue.")
        assert out.plan_action == "keep"
        assert out.steps == []

    def test_first_wave_model_rejects_more_than_two_steps(self) -> None:
        from soothe.foundation.sloop.state.schemas import plan_generation_model_for_iteration

        schema = plan_generation_model_for_iteration(0)
        steps = [
            PlanGenerateStep(id="01", description=f"step {i}", expected_output="ok")
            for i in range(3)
        ]
        with pytest.raises(ValidationError):
            schema(
                plan_action="new",
                type="execute_steps",
                execution_mode="parallel",
                steps=steps,
                next_action="Proceed.",
            )

    def test_first_wave_model_accepts_two_steps(self) -> None:
        from soothe.foundation.sloop.state.schemas import plan_generation_model_for_iteration

        schema = plan_generation_model_for_iteration(0)
        out = schema(
            plan_action="new",
            type="execute_steps",
            execution_mode="parallel",
            steps=[
                PlanGenerateStep(id="01", description="recon", expected_output="map"),
                PlanGenerateStep(id="02", description="implement", expected_output="done"),
            ],
            next_action="Starting.",
        )
        assert len(out.steps) == 2

    def test_later_iteration_model_allows_three_steps(self) -> None:
        from soothe.foundation.sloop.state.schemas import plan_generation_model_for_iteration

        schema = plan_generation_model_for_iteration(1)
        assert schema is PlanGeneration
        out = PlanGeneration(
            plan_action="new",
            type="execute_steps",
            execution_mode="parallel",
            steps=[
                PlanGenerateStep(id="01", description=f"step {i}", expected_output="ok")
                for i in range(3)
            ],
            next_action="Proceed.",
        )
        assert len(out.steps) == 3


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

    def test_to_evidence_string_subagent_includes_delegate_preview(self):
        """Subagent steps surface bounded delegate preview for planning (IG-356)."""
        result = StepResult(
            step_id="s1",
            success=True,
            outcome={
                "type": "subagent",
                "tool_name": "task",
                "wave_join_preview": "Report intro… full delegate body here.",
                "size_bytes": 100,
            },
            duration_ms=100,
            thread_id="t1",
        )
        evidence = result.to_evidence_string()
        assert "task" in evidence
        assert "Report intro" in evidence
        assert "delegation completed" not in evidence


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
        assert state.goal_user_submission is None
        assert state.iteration == 0
        assert state.max_iterations == 99  # DEFAULT_STRANGE_LOOP_MAX_ITERATIONS
        assert state.current_decision is None
        assert len(state.step_results) == 0

    def test_loop_state_goal_user_submission(self) -> None:
        """Slash-skill runs keep the submitted line for trace UX."""
        state = LoopState(
            goal="Skill: weather\n\nArguments: x",
            goal_user_submission="/skill:weather x",
            thread_id="t1",
        )
        assert state.goal_user_submission == "/skill:weather x"
        trace_goal = state.goal_user_submission or state.goal
        assert trace_goal == "/skill:weather x"

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
            execution_mode="parallel",
            reasoning="Test",
        )

        assert state.has_remaining_steps() is True

        # Step completed
        state.completed_step_ids.add("s1")
        assert state.has_remaining_steps() is False

    def test_dependency_completion_ids_survives_replan_clear(self) -> None:
        """After replan clears ``completed_step_ids``, deps on prior waves still resolve (IG-346)."""
        state = LoopState(goal="Count READMEs", thread_id="t1")
        state.add_step_result(
            StepResult(
                step_id="step_001",
                success=True,
                duration_ms=100,
                thread_id="t1",
            )
        )
        state.completed_step_ids.clear()

        follow_up = StepAction(
            id="step_002",
            description="Filter results",
            expected_output="OK",
            dependencies=["step_001"],
        )
        decision = AgentDecision(
            type="execute_steps",
            steps=[follow_up],
            execution_mode="parallel",
            reasoning="Continue after explore",
        )

        ready = decision.get_ready_steps(state.dependency_completion_ids())
        assert len(ready) == 1
        assert ready[0].id == "step_002"

        state.current_decision = decision
        assert state.has_remaining_steps() is True


class TestGoalContinuousStepIdsIg388:
    """Goal-scoped sequential local step ids after plan-generate (IG-388)."""

    def test_trailing_numeric_suffix_hyphen_and_legacy(self) -> None:
        assert trailing_numeric_suffix_from_step_id("KFA-07") == 7
        assert trailing_numeric_suffix_from_step_id("ZZ-001") == 1
        assert trailing_numeric_suffix_from_step_id("step_004") == 4
        assert trailing_numeric_suffix_from_step_id("no-digits-here") is None

    def test_next_start_from_step_results_and_current_decision(self) -> None:
        state = LoopState(goal="g", thread_id="t1")
        assert next_goal_local_step_id_start(state) == 1
        state.add_step_result(
            StepResult(step_id="ABC-02", success=True, duration_ms=1, thread_id="t1")
        )
        assert max_goal_step_numeric_suffix(state) == 2
        assert next_goal_local_step_id_start(state) == 3
        state.current_decision = AgentDecision(
            type="execute_steps",
            steps=[
                StepAction(id="ABC-05", description="pending", expected_output="x"),
            ],
            execution_mode="parallel",
            reasoning="",
        )
        assert next_goal_local_step_id_start(state) == 6

    def test_renumber_new_plan_after_prior_suffixes(self) -> None:
        state = LoopState(goal="g", thread_id="t1")
        state.add_step_result(
            StepResult(step_id="X-02", success=True, duration_ms=1, thread_id="t1")
        )
        d0 = StepAction(id="01", description="a", expected_output="o")
        d1 = StepAction(id="02", description="b", expected_output="o", dependencies=["01"])
        decision = AgentDecision(
            type="execute_steps",
            steps=[d0, d1],
            execution_mode="dependency",
            reasoning="",
        )
        out = renumber_decision_local_step_ids_for_goal_continuation(decision, state)
        assert [s.id for s in out.steps] == ["03", "04"]
        assert out.steps[1].dependencies == ["03"]

    def test_renumber_preserves_cross_wave_dependency_strings(self) -> None:
        state = LoopState(goal="g", thread_id="t1")
        state.add_step_result(
            StepResult(step_id="PRIOR-01", success=True, duration_ms=1, thread_id="t1")
        )
        d0 = StepAction(
            id="01",
            description="a",
            expected_output="o",
            dependencies=["PRIOR-01"],
        )
        decision = AgentDecision(
            type="execute_steps",
            steps=[d0],
            execution_mode="dependency",
            reasoning="",
        )
        out = renumber_decision_local_step_ids_for_goal_continuation(decision, state)
        assert out.steps[0].id == "02"
        assert out.steps[0].dependencies == ["PRIOR-01"]

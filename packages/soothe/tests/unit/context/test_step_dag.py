"""Tests for StepDAG and dependency resolution (soothe.context.models)."""

import pytest

from soothe.context.models import StepDAG, StepExecution, StepNode


class TestStepDAGAddStep:
    def test_add_step_basic(self) -> None:
        dag = StepDAG()
        step = StepNode(id="S1", description="Do something")
        dag.add_step(step)
        assert "S1" in dag.nodes
        assert dag.nodes["S1"].description == "Do something"

    def test_add_step_overwrites_existing(self) -> None:
        dag = StepDAG()
        dag.add_step(StepNode(id="S1", description="First"))
        dag.add_step(StepNode(id="S1", description="Second"))
        assert dag.nodes["S1"].description == "Second"


class TestStepDAGReadySteps:
    def test_no_deps_all_ready(self) -> None:
        dag = StepDAG()
        for i in range(3):
            dag.add_step(StepNode(id=f"S{i}", description=f"Step {i}"))
        assert dag.ready_steps() == {"S0", "S1", "S2"}

    def test_unmet_deps_not_ready(self) -> None:
        dag = StepDAG()
        dag.add_step(StepNode(id="S1", description="First"))
        dag.add_step(StepNode(id="S2", description="Second", dependencies=["S1"]))
        dag.add_step(StepNode(id="S3", description="Third", dependencies=["S1", "S2"]))
        assert dag.ready_steps() == {"S1"}

    def test_completed_satisfies_dep(self) -> None:
        dag = StepDAG()
        dag.add_step(StepNode(id="S1", description="First"))
        dag.add_step(StepNode(id="S2", description="Second", dependencies=["S1"]))
        dag.mark_completed("S1", StepExecution())
        assert "S2" in dag.ready_steps()

    def test_failed_does_not_satisfy_dep(self) -> None:
        dag = StepDAG()
        dag.add_step(StepNode(id="S1", description="First"))
        dag.add_step(StepNode(id="S2", description="Second", dependencies=["S1"]))
        dag.mark_failed("S1", StepExecution(error="boom"))
        assert "S2" not in dag.ready_steps()

    def test_completed_step_not_ready(self) -> None:
        dag = StepDAG()
        dag.add_step(StepNode(id="S1", description="First"))
        dag.mark_completed("S1", StepExecution())
        assert dag.ready_steps() == set()

    def test_skipped_step_not_ready(self) -> None:
        dag = StepDAG()
        dag.add_step(StepNode(id="S1", description="First"))
        dag.mark_skipped("S1")
        assert dag.ready_steps() == set()

    def test_composite_id_alias_expansion(self) -> None:
        """Composite step IDs like KFA-01 satisfy deps referencing '01' or '1'."""
        dag = StepDAG()
        dag.add_step(StepNode(id="KFA-01", description="First"))
        dag.add_step(StepNode(id="S2", description="Second", dependencies=["01"]))
        dag.mark_completed("KFA-01", StepExecution())
        assert "S2" in dag.ready_steps()

    def test_composite_id_numeric_alias(self) -> None:
        dag = StepDAG()
        dag.add_step(StepNode(id="KFA-01", description="First"))
        dag.add_step(StepNode(id="S2", description="Second", dependencies=["1"]))
        dag.mark_completed("KFA-01", StepExecution())
        assert "S2" in dag.ready_steps()

    def test_ambiguous_composite_not_expanded(self) -> None:
        """Two different owners with same numeric suffix → no alias."""
        dag = StepDAG()
        dag.add_step(StepNode(id="KFA-01", description="First"))
        dag.add_step(StepNode(id="BFA-01", description="Also first"))
        dag.add_step(StepNode(id="S3", description="Third", dependencies=["01"]))
        dag.mark_completed("KFA-01", StepExecution())
        dag.mark_completed("BFA-01", StepExecution())
        assert "S3" not in dag.ready_steps()


class TestStepDAGMarkStatus:
    def test_mark_completed(self) -> None:
        dag = StepDAG()
        dag.add_step(StepNode(id="S1", description="First"))
        exe = StepExecution(tokens_used=100, duration_ms=500)
        dag.mark_completed("S1", exe)
        assert dag.nodes["S1"].status == "completed"
        assert dag.nodes["S1"].execution is exe

    def test_mark_failed(self) -> None:
        dag = StepDAG()
        dag.add_step(StepNode(id="S1", description="First"))
        exe = StepExecution(error="timeout")
        dag.mark_failed("S1", exe)
        assert dag.nodes["S1"].status == "failed"
        assert dag.nodes["S1"].execution.error == "timeout"

    def test_mark_skipped(self) -> None:
        dag = StepDAG()
        dag.add_step(StepNode(id="S1", description="First"))
        dag.mark_skipped("S1")
        assert dag.nodes["S1"].status == "skipped"

    def test_mark_nonexistent_is_noop(self) -> None:
        dag = StepDAG()
        dag.mark_completed("MISSING", StepExecution())
        dag.mark_failed("MISSING", StepExecution())
        dag.mark_skipped("MISSING")


class TestStepDAGProperties:
    def test_total_steps(self) -> None:
        dag = StepDAG()
        dag.add_step(StepNode(id="S1", description="A"))
        dag.add_step(StepNode(id="S2", description="B"))
        assert dag.total_steps == 2

    def test_completed_steps(self) -> None:
        dag = StepDAG()
        dag.add_step(StepNode(id="S1", description="A"))
        dag.add_step(StepNode(id="S2", description="B"))
        dag.mark_completed("S1", StepExecution())
        assert dag.completed_steps == 1

    def test_failed_steps(self) -> None:
        dag = StepDAG()
        dag.add_step(StepNode(id="S1", description="A"))
        dag.mark_failed("S1", StepExecution(error="x"))
        assert dag.failed_steps == 1

    def test_success_rate_no_executions(self) -> None:
        dag = StepDAG()
        assert dag.success_rate == 1.0

    def test_success_rate_all_succeeded(self) -> None:
        dag = StepDAG()
        dag.add_step(StepNode(id="S1", description="A"))
        dag.mark_completed("S1", StepExecution())
        assert dag.success_rate == 1.0

    def test_success_rate_mixed(self) -> None:
        dag = StepDAG()
        dag.add_step(StepNode(id="S1", description="A"))
        dag.add_step(StepNode(id="S2", description="B"))
        dag.add_step(StepNode(id="S3", description="C"))
        dag.mark_completed("S1", StepExecution())
        dag.mark_completed("S2", StepExecution())
        dag.mark_failed("S3", StepExecution(error="x"))
        assert dag.success_rate == pytest.approx(2 / 3)

    def test_id_accessors(self) -> None:
        dag = StepDAG()
        dag.add_step(StepNode(id="S1", description="A"))
        dag.add_step(StepNode(id="S2", description="B"))
        dag.mark_completed("S1", StepExecution())
        assert dag.completed_step_ids() == {"S1"}
        assert dag.pending_step_ids() == {"S2"}
        assert dag.failed_step_ids() == set()

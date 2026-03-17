"""Tests for StepScheduler (RFC-0009)."""

import pytest

from soothe.core.step_scheduler import StepScheduler
from soothe.protocols.planner import Plan, PlanStep


def test_init_valid_plan() -> None:
    plan = Plan(goal="g", steps=[PlanStep(id="a", description="A")])
    sched = StepScheduler(plan)
    assert sched._plan == plan


def test_init_raises_on_cycle() -> None:
    plan = Plan(
        goal="g",
        steps=[
            PlanStep(id="A", description="A", depends_on=["B"]),
            PlanStep(id="B", description="B", depends_on=["A"]),
        ],
    )
    with pytest.raises(ValueError, match="Cycle detected"):
        StepScheduler(plan)


def test_ready_steps_no_deps() -> None:
    plan = Plan(
        goal="g",
        steps=[
            PlanStep(id="a", description="A"),
            PlanStep(id="b", description="B"),
        ],
    )
    sched = StepScheduler(plan)
    ready = sched.ready_steps()
    assert len(ready) == 2
    ids = {s.id for s in ready}
    assert ids == {"a", "b"}


def test_ready_steps_respects_dependencies() -> None:
    plan = Plan(
        goal="g",
        steps=[
            PlanStep(id="A", description="A"),
            PlanStep(id="B", description="B", depends_on=["A"]),
        ],
    )
    sched = StepScheduler(plan)
    ready = sched.ready_steps()
    assert len(ready) == 1
    assert ready[0].id == "A"
    sched.mark_completed("A", "done")
    ready = sched.ready_steps()
    assert len(ready) == 1
    assert ready[0].id == "B"


def test_ready_steps_limit() -> None:
    plan = Plan(
        goal="g",
        steps=[
            PlanStep(id="a", description="A"),
            PlanStep(id="b", description="B"),
            PlanStep(id="c", description="C"),
        ],
    )
    sched = StepScheduler(plan)
    ready = sched.ready_steps(limit=2)
    assert len(ready) == 2


def test_ready_steps_sequential_mode() -> None:
    plan = Plan(
        goal="g",
        steps=[
            PlanStep(id="a", description="A"),
            PlanStep(id="b", description="B"),
        ],
    )
    sched = StepScheduler(plan)
    ready = sched.ready_steps(parallelism="sequential")
    assert len(ready) == 1


def test_ready_steps_dependency_mode() -> None:
    plan = Plan(
        goal="g",
        steps=[
            PlanStep(id="a", description="A"),
            PlanStep(id="b", description="B"),
        ],
    )
    sched = StepScheduler(plan)
    ready = sched.ready_steps(parallelism="dependency")
    assert len(ready) == 2
    ids = {s.id for s in ready}
    assert ids == {"a", "b"}


def test_mark_completed() -> None:
    plan = Plan(goal="g", steps=[PlanStep(id="a", description="A")])
    sched = StepScheduler(plan)
    sched.mark_completed("a", "result")
    step = plan.steps[0]
    assert step.status == "completed"
    assert step.result == "result"


def test_mark_failed() -> None:
    plan = Plan(goal="g", steps=[PlanStep(id="a", description="A")])
    sched = StepScheduler(plan)
    sched.mark_failed("a", "error msg")
    step = plan.steps[0]
    assert step.status == "failed"
    assert step.result == "error msg"


def test_mark_in_progress() -> None:
    plan = Plan(goal="g", steps=[PlanStep(id="a", description="A")])
    sched = StepScheduler(plan)
    sched.mark_in_progress("a")
    step = plan.steps[0]
    assert step.status == "in_progress"


def test_failure_propagation() -> None:
    plan = Plan(
        goal="g",
        steps=[
            PlanStep(id="A", description="A"),
            PlanStep(id="B", description="B", depends_on=["A"]),
        ],
    )
    sched = StepScheduler(plan)
    sched.mark_failed("A", "oops")
    ready = sched.ready_steps()
    assert len(ready) == 0
    b_step = next(s for s in plan.steps if s.id == "B")
    assert b_step.status == "failed"
    assert "Blocked by failed dependency" in (b_step.result or "")


def test_transitive_failure() -> None:
    plan = Plan(
        goal="g",
        steps=[
            PlanStep(id="A", description="A"),
            PlanStep(id="B", description="B", depends_on=["A"]),
            PlanStep(id="C", description="C", depends_on=["B"]),
        ],
    )
    sched = StepScheduler(plan)
    sched.mark_failed("A", "oops")
    ready = sched.ready_steps()
    assert len(ready) == 0
    b_step = next(s for s in plan.steps if s.id == "B")
    c_step = next(s for s in plan.steps if s.id == "C")
    assert b_step.status == "failed"
    assert c_step.status == "failed"


def test_is_complete_all_done() -> None:
    plan = Plan(
        goal="g",
        steps=[
            PlanStep(id="a", description="A"),
            PlanStep(id="b", description="B"),
        ],
    )
    sched = StepScheduler(plan)
    assert sched.is_complete() is False
    sched.mark_completed("a", "ok")
    sched.mark_completed("b", "ok")
    assert sched.is_complete() is True


def test_is_complete_partial() -> None:
    plan = Plan(
        goal="g",
        steps=[
            PlanStep(id="a", description="A"),
            PlanStep(id="b", description="B"),
        ],
    )
    sched = StepScheduler(plan)
    sched.mark_completed("a", "ok")
    assert sched.is_complete() is False


def test_get_dependency_results() -> None:
    plan = Plan(
        goal="g",
        steps=[
            PlanStep(id="A", description="Desc A"),
            PlanStep(id="B", description="Desc B", depends_on=["A"]),
        ],
    )
    sched = StepScheduler(plan)
    sched.mark_completed("A", "result A")
    b_step = next(s for s in plan.steps if s.id == "B")
    results = sched.get_dependency_results(b_step)
    assert results == [("Desc A", "result A")]


def test_summary() -> None:
    plan = Plan(
        goal="g",
        steps=[
            PlanStep(id="a", description="A"),
            PlanStep(id="b", description="B"),
        ],
    )
    sched = StepScheduler(plan)
    summary = sched.summary()
    assert summary["total"] == 2
    assert summary["pending"] == 2
    assert summary["is_complete"] is False
    sched.mark_completed("a", "ok")
    sched.mark_completed("b", "ok")
    summary = sched.summary()
    assert summary["completed"] == 2
    assert summary["pending"] == 0
    assert summary["is_complete"] is True


def test_dag_parallel_batch() -> None:
    plan = Plan(
        goal="g",
        steps=[
            PlanStep(id="A", description="A"),
            PlanStep(id="B", description="B"),
            PlanStep(id="C", description="C", depends_on=["A", "B"]),
        ],
    )
    sched = StepScheduler(plan)
    batch1 = sched.ready_steps()
    assert len(batch1) == 2
    ids1 = {s.id for s in batch1}
    assert ids1 == {"A", "B"}
    sched.mark_completed("A", "a done")
    sched.mark_completed("B", "b done")
    batch2 = sched.ready_steps()
    assert len(batch2) == 1
    assert batch2[0].id == "C"

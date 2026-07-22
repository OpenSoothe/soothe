"""Tests for GoalStepDAG (soothe.context.models)."""

import pytest

from soothe.context.models import MAX_GOAL_DEPTH, GoalNode, GoalStepDAG, StepNode


class TestGoalStepDAGAddGoal:
    @pytest.mark.asyncio
    async def test_add_goal_basic(self) -> None:
        dag = GoalStepDAG()
        goal = GoalNode(description="Test goal")
        dag.add_goal(goal)
        assert dag.get_goal(goal.id) is goal

    @pytest.mark.asyncio
    async def test_add_goal_with_parent(self) -> None:
        dag = GoalStepDAG()
        parent = GoalNode(description="Parent")
        dag.add_goal(parent)
        child = GoalNode(description="Child", parent_id=parent.id)
        dag.add_goal(child)
        assert dag.get_goal(child.id) is child

    def test_add_goal_exceeds_depth(self) -> None:
        dag = GoalStepDAG()
        current = GoalNode(description="Root")
        dag.add_goal(current)
        for i in range(MAX_GOAL_DEPTH - 1):
            child = GoalNode(description=f"Depth {i + 1}", parent_id=current.id)
            dag.add_goal(child)
            current = child
        too_deep = GoalNode(description="Too deep", parent_id=current.id)
        with pytest.raises(ValueError, match="Goal depth limit"):
            dag.add_goal(too_deep)


class TestGoalStepDAGLifecycle:
    def test_complete_goal(self) -> None:
        dag = GoalStepDAG()
        goal = GoalNode(description="Test")
        dag.add_goal(goal)
        dag.complete_goal(goal.id)
        assert dag.goals[goal.id].status == "completed"

    def test_fail_goal(self) -> None:
        dag = GoalStepDAG()
        goal = GoalNode(description="Test")
        dag.add_goal(goal)
        dag.fail_goal(goal.id, "error")
        assert dag.goals[goal.id].status == "failed"

    def test_suspend_goal(self) -> None:
        dag = GoalStepDAG()
        goal = GoalNode(description="Test", assigned_loop_id="loop-1")
        dag.add_goal(goal)
        dag.suspend_goal(goal.id, "waiting")
        assert dag.goals[goal.id].status == "suspended"
        assert dag.goals[goal.id].assigned_loop_id is None

    def test_complete_nonexistent_is_noop(self) -> None:
        dag = GoalStepDAG()
        dag.complete_goal("missing")

    def test_cancel_goal(self) -> None:
        dag = GoalStepDAG()
        goal = GoalNode(description="Test")
        dag.add_goal(goal)
        dag.cancel_goal(goal.id)
        assert dag.goals[goal.id].status == "cancelled"

    def test_block_goal(self) -> None:
        dag = GoalStepDAG()
        goal = GoalNode(description="Test")
        dag.add_goal(goal)
        dag.block_goal(goal.id)
        assert dag.goals[goal.id].status == "blocked"

    def test_unblock_goal(self) -> None:
        dag = GoalStepDAG()
        goal = GoalNode(description="Test")
        dag.add_goal(goal)
        dag.block_goal(goal.id)
        assert dag.goals[goal.id].status == "blocked"
        dag.unblock_goal(goal.id)
        assert dag.goals[goal.id].status == "pending"

    def test_unblock_non_blocked_is_noop(self) -> None:
        dag = GoalStepDAG()
        goal = GoalNode(description="Test", status="active")
        dag.add_goal(goal)
        dag.unblock_goal(goal.id)
        assert dag.goals[goal.id].status == "active"

    def test_cancel_nonexistent_is_noop(self) -> None:
        dag = GoalStepDAG()
        dag.cancel_goal("missing")

    def test_collect_subtree_ids_deepest_first(self) -> None:
        dag = GoalStepDAG()
        root = GoalNode(description="root")
        child = GoalNode(description="child", parent_id=root.id)
        leaf = GoalNode(description="leaf", parent_id=child.id)
        dag.add_goal(root)
        dag.add_goal(child)
        dag.add_goal(leaf)
        assert dag.collect_subtree_ids(root.id) == [leaf.id, child.id, root.id]
        assert dag.collect_subtree_ids("missing") == []


class TestGoalStepDAGScheduling:
    def test_ready_goals_pending_only(self) -> None:
        dag = GoalStepDAG()
        goal = GoalNode(description="Test", status="active")
        dag.add_goal(goal)
        assert dag.peek_ready_goals() == []

    def test_ready_goals_sorted_by_priority(self) -> None:
        dag = GoalStepDAG()
        low = GoalNode(description="Low", priority=10)
        high = GoalNode(description="High", priority=90)
        dag.add_goal(low)
        dag.add_goal(high)
        ready = dag.peek_ready_goals(limit=1)
        assert ready[0].id == high.id

    def test_ready_goals_deps_met(self) -> None:
        dag = GoalStepDAG()
        dep = GoalNode(description="Dep", priority=10)
        dag.add_goal(dep)
        goal = GoalNode(description="Goal", priority=50, depends_on=[dep.id])
        dag.add_goal(goal)
        # Dep itself is ready (no deps), but goal is not
        ready_before = dag.peek_ready_goals()
        assert goal.id not in [g.id for g in ready_before]
        dag.complete_goal(dep.id)
        ready_after = dag.peek_ready_goals()
        assert goal.id in [g.id for g in ready_after]

    def test_ready_goals_conflict_blocks(self) -> None:
        dag = GoalStepDAG()
        active = GoalNode(description="Active", status="active")
        dag.add_goal(active)
        pending = GoalNode(description="Pending", conflicts_with=[active.id])
        dag.add_goal(pending)
        assert dag.peek_ready_goals() == []

    def test_active_goals(self) -> None:
        dag = GoalStepDAG()
        g1 = GoalNode(description="A", status="active")
        g2 = GoalNode(description="B", status="pending")
        dag.add_goal(g1)
        dag.add_goal(g2)
        active = dag.active_goals()
        assert len(active) == 1
        assert active[0].id == g1.id


class TestGoalStepDAGLineage:
    def test_lineage_single(self) -> None:
        dag = GoalStepDAG()
        goal = GoalNode(description="Root")
        dag.add_goal(goal)
        assert dag.goal_lineage(goal.id) == ["Root"]

    def test_lineage_chain(self) -> None:
        dag = GoalStepDAG()
        root = GoalNode(description="Root")
        dag.add_goal(root)
        child = GoalNode(description="Child", parent_id=root.id)
        dag.add_goal(child)
        grandchild = GoalNode(description="Grand", parent_id=child.id)
        dag.add_goal(grandchild)
        assert dag.goal_lineage(grandchild.id) == ["Root", "Child", "Grand"]

    def test_lineage_cycle_breaks(self) -> None:
        dag = GoalStepDAG()
        g1 = GoalNode(description="A")
        dag.add_goal(g1)
        g2 = GoalNode(description="B", parent_id=g1.id)
        dag.add_goal(g2)
        g1.parent_id = g2.id  # create cycle
        lineage = dag.goal_lineage(g2.id)
        assert len(lineage) <= 3


class TestGoalStepDAGSnapshot:
    def test_snapshot_restore_roundtrip(self) -> None:
        dag = GoalStepDAG()
        goal = GoalNode(description="Test", priority=42)
        goal.steps.add_step(StepNode(id="S1", description="Step"))
        dag.add_goal(goal)

        snap = dag.snapshot()
        dag2 = GoalStepDAG()
        dag2.restore_from_snapshot(snap)
        assert len(dag2.goals) == 1
        restored = list(dag2.goals.values())[0]
        assert restored.description == "Test"
        assert restored.priority == 42
        assert "S1" in restored.steps.nodes


class TestGoalStepDAGRecovery:
    def test_recover_active_resets_to_pending(self) -> None:
        dag = GoalStepDAG()
        g1 = GoalNode(description="A", status="active", assigned_loop_id="loop-1")
        g2 = GoalNode(description="B", status="completed")
        dag.add_goal(g1)
        dag.add_goal(g2)
        recovered = dag.recover_active_goals()
        assert recovered == [g1.id]
        assert dag.goals[g1.id].status == "pending"
        assert dag.goals[g1.id].assigned_loop_id is None
        assert dag.goals[g2.id].status == "completed"

    def test_recover_no_active(self) -> None:
        dag = GoalStepDAG()
        assert dag.recover_active_goals() == []

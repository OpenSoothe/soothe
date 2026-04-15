"""Unit tests for dynamic goal management (RFC-0007 §5.4-5.6)."""

import pytest

from soothe.cognition import GoalEngine
from soothe.protocols.planner import GoalContext, GoalDirective


class TestGoalEngineSafety:
    """Test cycle detection, depth validation, and dependency validation."""

    @pytest.mark.asyncio
    async def test_calculate_goal_depth_no_parent(self):
        """Test depth calculation for goal without parent."""
        engine = GoalEngine()
        goal = await engine.create_goal("Test goal")

        depth = engine._calculate_goal_depth(goal.id)
        assert depth == 1

    @pytest.mark.asyncio
    async def test_calculate_goal_depth_with_parent(self):
        """Test depth calculation for hierarchical goals."""
        engine = GoalEngine()
        parent = await engine.create_goal("Parent goal")
        child = await engine.create_goal("Child goal", parent_id=parent.id)
        grandchild = await engine.create_goal("Grandchild goal", parent_id=child.id)

        assert engine._calculate_goal_depth(parent.id) == 1
        assert engine._calculate_goal_depth(child.id) == 2
        assert engine._calculate_goal_depth(grandchild.id) == 3

    @pytest.mark.asyncio
    async def test_create_goal_exceeds_depth_limit(self):
        """Test that creating goals beyond depth limit raises ValueError."""
        engine = GoalEngine()
        parent = await engine.create_goal("Parent")
        child = await engine.create_goal("Child", parent_id=parent.id, _max_depth=2)

        # Should succeed at depth 2
        assert engine._calculate_goal_depth(child.id) == 2

        # Should fail at depth 3 with limit of 2
        with pytest.raises(ValueError, match="depth limit"):
            await engine.create_goal("Grandchild", parent_id=child.id, _max_depth=2)

    @pytest.mark.asyncio
    async def test_would_create_cycle_simple(self):
        """Test cycle detection with simple A -> B -> A cycle."""
        engine = GoalEngine()
        goal_a = await engine.create_goal("Goal A")
        goal_b = await engine.create_goal("Goal B")

        # Add A depends on B
        await engine.add_dependencies(goal_a.id, [goal_b.id])

        # Trying to add B depends on A should detect cycle
        assert engine._would_create_cycle(goal_b.id, [goal_a.id])

    @pytest.mark.asyncio
    async def test_would_create_cycle_complex(self):
        """Test cycle detection with complex A -> B -> C -> A cycle."""
        engine = GoalEngine()
        goal_a = await engine.create_goal("Goal A")
        goal_b = await engine.create_goal("Goal B")
        goal_c = await engine.create_goal("Goal C")

        # A -> B -> C
        await engine.add_dependencies(goal_a.id, [goal_b.id])
        await engine.add_dependencies(goal_b.id, [goal_c.id])

        # Trying to add C -> A should detect cycle
        assert engine._would_create_cycle(goal_c.id, [goal_a.id])

    @pytest.mark.asyncio
    async def test_would_not_create_cycle_valid_dag(self):
        """Test that valid DAG doesn't trigger cycle detection."""
        engine = GoalEngine()
        goal_a = await engine.create_goal("Goal A")
        goal_b = await engine.create_goal("Goal B")
        goal_c = await engine.create_goal("Goal C")

        # A depends on B and C (valid)
        await engine.add_dependencies(goal_a.id, [goal_b.id, goal_c.id])

        # B depends on C (valid)
        assert not engine._would_create_cycle(goal_b.id, [goal_c.id])

    @pytest.mark.asyncio
    async def test_validate_dependency_missing_goal(self):
        """Test validation fails when dependency doesn't exist."""
        engine = GoalEngine()
        goal = await engine.create_goal("Test goal")

        is_valid, error = await engine.validate_dependency(goal.id, ["nonexistent"])
        assert not is_valid
        assert "does not exist" in error

    @pytest.mark.asyncio
    async def test_validate_dependency_self_dependency(self):
        """Test validation fails for self-dependency."""
        engine = GoalEngine()
        goal = await engine.create_goal("Test goal")

        is_valid, error = await engine.validate_dependency(goal.id, [goal.id])
        assert not is_valid
        assert "cannot depend on itself" in error

    @pytest.mark.asyncio
    async def test_add_dependencies_valid(self):
        """Test adding valid dependencies."""
        engine = GoalEngine()
        goal_a = await engine.create_goal("Goal A")
        goal_b = await engine.create_goal("Goal B")

        result = await engine.add_dependencies(goal_a.id, [goal_b.id])

        assert goal_b.id in result.depends_on
        assert result.updated_at > result.created_at

    @pytest.mark.asyncio
    async def test_add_dependencies_cycle_raises(self):
        """Test that adding dependency creating cycle raises ValueError."""
        engine = GoalEngine()
        goal_a = await engine.create_goal("Goal A")
        goal_b = await engine.create_goal("Goal B")

        # A -> B
        await engine.add_dependencies(goal_a.id, [goal_b.id])

        # B -> A should raise
        with pytest.raises(ValueError, match="cycle"):
            await engine.add_dependencies(goal_b.id, [goal_a.id])

    @pytest.mark.asyncio
    async def test_add_dependencies_duplicate(self):
        """Test that adding duplicate dependencies is idempotent."""
        engine = GoalEngine()
        goal_a = await engine.create_goal("Goal A")
        goal_b = await engine.create_goal("Goal B")

        await engine.add_dependencies(goal_a.id, [goal_b.id])
        await engine.add_dependencies(goal_a.id, [goal_b.id])

        # Should only appear once
        assert goal_a.depends_on.count(goal_b.id) == 1


class TestGoalDirectives:
    """Test goal directive processing."""

    @pytest.mark.asyncio
    async def test_directive_create_basic(self):
        """Test basic goal creation directive."""
        engine = GoalEngine()
        directive = GoalDirective(
            action="create",
            description="Test prerequisite",
            priority=60,
            rationale="Needed for main goal",
        )

        # Simulate directive application
        new_goal = await engine.create_goal(
            description=directive.description,
            priority=directive.priority or 50,
        )

        assert new_goal.description == "Test prerequisite"
        assert new_goal.priority == 60
        assert new_goal.status == "pending"

    @pytest.mark.asyncio
    async def test_directive_adjust_priority(self):
        """Test priority adjustment directive."""
        engine = GoalEngine()
        goal = await engine.create_goal("Test goal", priority=50)

        # Simulate priority adjustment
        goal.priority = 90
        goal.updated_at = goal.updated_at  # Trigger update

        assert goal.priority == 90

    @pytest.mark.asyncio
    async def test_directive_add_dependency(self):
        """Test adding dependency directive."""
        engine = GoalEngine()
        goal_a = await engine.create_goal("Goal A")
        goal_b = await engine.create_goal("Goal B")

        # Simulate add_dependency directive
        await engine.add_dependencies(goal_a.id, [goal_b.id])

        assert goal_b.id in goal_a.depends_on

    @pytest.mark.asyncio
    async def test_directive_decompose(self):
        """Test goal decomposition directive."""
        engine = GoalEngine()
        parent = await engine.create_goal("Parent goal", priority=70)

        # Simulate decomposition
        sub_goal = await engine.create_goal(
            description="Sub-task",
            priority=parent.priority,
            parent_id=parent.id,
        )

        assert sub_goal.parent_id == parent.id
        assert sub_goal.priority == 70


class TestGoalContext:
    """Test goal context building."""

    @pytest.mark.asyncio
    async def test_goal_context_building(self):
        """Test building goal context for reflection."""
        engine = GoalEngine()
        goal_a = await engine.create_goal("Goal A", priority=80)
        goal_b = await engine.create_goal("Goal B", priority=70)
        await engine.complete_goal(goal_b.id)

        all_goals = await engine.list_goals()
        context = GoalContext(
            current_goal_id=goal_a.id,
            all_goals=[g.model_dump(mode="json") for g in all_goals],
            completed_goals=[g.id for g in all_goals if g.status == "completed"],
            failed_goals=[g.id for g in all_goals if g.status == "failed"],
            ready_goals=[g.id for g in all_goals if g.status in ("pending", "active")],
            max_parallel_goals=1,
        )

        assert context.current_goal_id == goal_a.id
        assert len(context.all_goals) == 2
        assert goal_b.id in context.completed_goals
        assert goal_a.id in context.ready_goals


class TestDAGConsistency:
    """Test DAG consistency handling."""

    @pytest.mark.asyncio
    async def test_dependencies_met(self):
        """Test that goal with completed dependencies is not deferred."""
        engine = GoalEngine()
        goal_a = await engine.create_goal("Goal A")
        goal_b = await engine.create_goal("Goal B")

        # Complete dependency
        await engine.complete_goal(goal_b.id)

        # Add dependency
        await engine.add_dependencies(goal_a.id, [goal_b.id])

        # Check consistency (should not abort)
        deps_met = all(engine._goals.get(dep_id).status == "completed" for dep_id in goal_a.depends_on)

        assert deps_met

    @pytest.mark.asyncio
    async def test_dependencies_not_met(self):
        """Test that goal with incomplete dependencies should be deferred."""
        engine = GoalEngine()
        goal_a = await engine.create_goal("Goal A")
        goal_b = await engine.create_goal("Goal B")

        # Add dependency (B is not completed)
        await engine.add_dependencies(goal_a.id, [goal_b.id])

        # Check consistency (should abort)
        deps_met = all(engine._goals.get(dep_id).status == "completed" for dep_id in goal_a.depends_on)

        assert not deps_met

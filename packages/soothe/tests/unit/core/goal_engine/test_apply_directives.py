"""Tests for GoalEngine.apply_directives (RFC-204 Group C)."""

import pytest

from soothe.core.goal_engine.engine import GoalEngine
from soothe.core.goal_engine.models import EvidenceBundle
from soothe.protocols.planner import GoalDirective


class TestApplyDirectives:
    """Test directive application to GoalEngine."""

    @pytest.mark.asyncio
    async def test_create_directive_creates_goal(self) -> None:
        """'create' directive should create a new goal."""
        engine = GoalEngine()
        parent = await engine.create_goal("parent goal", goal_id="g_parent", priority=50)

        directives = [
            GoalDirective(action="create", description="subtask A", priority=60),
            GoalDirective(action="create", description="subtask B", priority=70),
        ]

        created_ids = await engine.apply_directives(directives, source_goal_id="g_parent")

        assert len(created_ids) == 2

        # Verify goals were created
        child_a = await engine.get_goal(created_ids[0])
        child_b = await engine.get_goal(created_ids[1])

        assert child_a is not None
        assert child_b is not None
        assert child_a.description == "subtask A"
        assert child_b.description == "subtask B"
        assert child_a.priority == 60
        assert child_b.priority == 70

        # Parent defaults to source_goal_id
        assert child_a.parent_id == "g_parent"
        assert child_b.parent_id == "g_parent"

    @pytest.mark.asyncio
    async def test_create_directive_parent_id_override(self) -> None:
        """'create' directive can override parent_id."""
        engine = GoalEngine()
        await engine.create_goal("parent", goal_id="g_parent")
        await engine.create_goal("other parent", goal_id="g_other")

        directives = [
            GoalDirective(
                action="create",
                description="subtask",
                priority=50,
                parent_id="g_other",
            ),
        ]

        created_ids = await engine.apply_directives(directives, source_goal_id="g_parent")

        child = await engine.get_goal(created_ids[0])
        assert child.parent_id == "g_other"  # Override wins

    @pytest.mark.asyncio
    async def test_create_directive_with_dependencies(self) -> None:
        """'create' directive can set depends_on."""
        engine = GoalEngine()
        await engine.create_goal("dep A", goal_id="dep_a")
        await engine.create_goal("dep B", goal_id="dep_b")
        await engine.create_goal("parent", goal_id="g_parent")

        directives = [
            GoalDirective(
                action="create",
                description="needs deps",
                priority=50,
                depends_on=["dep_a", "dep_b"],
            ),
        ]

        created_ids = await engine.apply_directives(directives, source_goal_id="g_parent")

        child = await engine.get_goal(created_ids[0])
        assert "dep_a" in child.depends_on
        assert "dep_b" in child.depends_on

    @pytest.mark.asyncio
    async def test_adjust_priority_directive(self) -> None:
        """'adjust_priority' directive updates goal priority."""
        engine = GoalEngine()
        await engine.create_goal("test goal", goal_id="g_test", priority=50)

        directives = [
            GoalDirective(action="adjust_priority", goal_id="g_test", priority=90),
        ]

        await engine.apply_directives(directives, source_goal_id="g_parent")

        goal = await engine.get_goal("g_test")
        assert goal.priority == 90

    @pytest.mark.asyncio
    async def test_adjust_priority_clamps_to_range(self) -> None:
        """Priority is clamped to 0-100 range."""
        engine = GoalEngine()
        await engine.create_goal("test", goal_id="g_test", priority=50)

        # Test upper bound clamping
        await engine.apply_directives(
            [GoalDirective(action="adjust_priority", goal_id="g_test", priority=150)],
            source_goal_id="g_parent",
        )
        goal = await engine.get_goal("g_test")
        assert goal.priority == 100

        # Test lower bound clamping
        await engine.apply_directives(
            [GoalDirective(action="adjust_priority", goal_id="g_test", priority=-10)],
            source_goal_id="g_parent",
        )
        goal = await engine.get_goal("g_test")
        assert goal.priority == 0

    @pytest.mark.asyncio
    async def test_adjust_priority_unknown_goal_logs_warning(self) -> None:
        """Adjusting priority of unknown goal should log warning, not raise."""
        engine = GoalEngine()

        # Should not raise, just log
        await engine.apply_directives(
            [GoalDirective(action="adjust_priority", goal_id="nonexistent", priority=80)],
            source_goal_id="g_parent",
        )

    @pytest.mark.asyncio
    async def test_add_dependency_directive(self) -> None:
        """'add_dependency' directive extends depends_on."""
        engine = GoalEngine()
        await engine.create_goal("dep", goal_id="dep_1")
        await engine.create_goal("target", goal_id="g_target", depends_on=[])

        directives = [
            GoalDirective(action="add_dependency", goal_id="g_target", depends_on=["dep_1"]),
        ]

        await engine.apply_directives(directives, source_goal_id="g_parent")

        goal = await engine.get_goal("g_target")
        assert "dep_1" in goal.depends_on

    @pytest.mark.asyncio
    async def test_add_dependency_deduplicates(self) -> None:
        """Adding same dependency twice is deduplicated."""
        engine = GoalEngine()
        await engine.create_goal("dep", goal_id="dep_1")
        await engine.create_goal("target", goal_id="g_target", depends_on=["dep_1"])

        # Try to add again
        await engine.apply_directives(
            [GoalDirective(action="add_dependency", goal_id="g_target", depends_on=["dep_1"])],
            source_goal_id="g_parent",
        )

        goal = await engine.get_goal("g_target")
        assert goal.depends_on.count("dep_1") == 1  # Still only one instance

    @pytest.mark.asyncio
    async def test_fail_directive(self) -> None:
        """'fail' directive marks goal as failed."""
        engine = GoalEngine()
        await engine.create_goal("target", goal_id="g_target", priority=50)

        directives = [
            GoalDirective(action="fail", goal_id="g_target", rationale="Directive-fail"),
        ]

        await engine.apply_directives(directives, source_goal_id="g_parent")

        goal = await engine.get_goal("g_target")
        assert goal.status == "failed"

    @pytest.mark.asyncio
    async def test_complete_directive(self) -> None:
        """'complete' directive marks goal as completed."""
        engine = GoalEngine()
        await engine.create_goal("target", goal_id="g_target", priority=50)

        directives = [
            GoalDirective(action="complete", goal_id="g_target"),
        ]

        await engine.apply_directives(directives, source_goal_id="g_parent")

        goal = await engine.get_goal("g_target")
        assert goal.status == "completed"

    @pytest.mark.asyncio
    async def test_decompose_directive_logs_warning(self) -> None:
        """'decompose' is not implemented, logs warning."""
        engine = GoalEngine()

        # Should not raise, just log warning
        await engine.apply_directives(
            [GoalDirective(action="decompose", goal_id="g_test", description="test")],
            source_goal_id="g_parent",
        )

    @pytest.mark.asyncio
    async def test_empty_directives_list(self) -> None:
        """Empty directives list returns empty created_ids."""
        engine = GoalEngine()

        created_ids = await engine.apply_directives([], source_goal_id="g_parent")
        assert created_ids == []

    @pytest.mark.asyncio
    async def test_multiple_directives_in_sequence(self) -> None:
        """Multiple directives are applied in sequence."""
        engine = GoalEngine()
        await engine.create_goal("parent", goal_id="g_parent")
        await engine.create_goal("existing", goal_id="g_existing", priority=30)

        directives = [
            GoalDirective(action="create", description="new subtask", priority=60),
            GoalDirective(action="adjust_priority", goal_id="g_existing", priority=80),
        ]

        created_ids = await engine.apply_directives(directives, source_goal_id="g_parent")

        assert len(created_ids) == 1  # Only 'create' returns new ID

        # Verify both effects applied
        existing = await engine.get_goal("g_existing")
        assert existing.priority == 80

        new_goal = await engine.get_goal(created_ids[0])
        assert new_goal.description == "new subtask"

    @pytest.mark.asyncio
    async def test_directive_error_is_logged_not_raised(self) -> None:
        """Directive application errors are logged, not raised."""
        engine = GoalEngine()

        # 'fail' with nonexistent goal_id should log warning, not raise
        await engine.apply_directives(
            [GoalDirective(action="fail", goal_id="nonexistent")],
            source_goal_id="g_parent",
        )

        # Execution continues without exception
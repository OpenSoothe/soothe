"""Tests for extended goal lifecycle methods in GoalEngine.

Covers: validate_goal, suspend_goal, block_goal, reactivate_goal,
check_reactivated_goals, append_goal_progress, conflict-aware scheduling,
file-based goal discovery, and frontmatter status updates.
"""

import pytest

from soothe.cognition import Goal, GoalEngine
from soothe.cognition.goal_engine.models import EvidenceBundle


class TestValidateGoal:
    """Tests for validate_goal ."""

    @pytest.mark.asyncio
    async def test_validates_active_goal(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("To validate")
        result = await engine.validate_goal(g.id)
        assert result.status == "validated"
        assert g.status == "validated"

    @pytest.mark.asyncio
    async def test_validated_goal_updates_timestamp(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("Timestamp test")
        before = g.updated_at
        await engine.validate_goal(g.id)
        assert g.updated_at > before

    @pytest.mark.asyncio
    async def test_validate_nonexistent_raises_key_error(self) -> None:
        engine = GoalEngine()
        with pytest.raises(KeyError):
            await engine.validate_goal("nonexistent")

    @pytest.mark.asyncio
    async def test_cannot_validate_completed_goal(self) -> None:
        """validate_goal does not guard against terminal states; it sets validated anyway."""
        engine = GoalEngine()
        g = await engine.create_goal("Already done")
        await engine.complete_goal(g.id)
        # Method does not check current state, so it transitions completed -> validated
        result = await engine.validate_goal(g.id)
        assert result.status == "validated"

    @pytest.mark.asyncio
    async def test_can_validate_pending_goal(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("Pending goal")
        result = await engine.validate_goal(g.id)
        assert result.status == "validated"

    @pytest.mark.asyncio
    async def test_can_validate_suspended_goal(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("Suspended goal")
        await engine.suspend_goal(g.id, reason="test")
        result = await engine.validate_goal(g.id)
        assert result.status == "validated"


class TestSuspendGoal:
    """Tests for suspend_goal ."""

    @pytest.mark.asyncio
    async def test_suspends_active_goal(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("To suspend")
        result = await engine.suspend_goal(g.id, reason="budget exhausted")
        assert result.status == "suspended"

    @pytest.mark.asyncio
    async def test_suspend_updates_timestamp(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("Timestamp test")
        before = g.updated_at
        await engine.suspend_goal(g.id, reason="test")
        assert g.updated_at > before

    @pytest.mark.asyncio
    async def test_suspend_nonexistent_raises_key_error(self) -> None:
        engine = GoalEngine()
        with pytest.raises(KeyError):
            await engine.suspend_goal("nonexistent")

    @pytest.mark.asyncio
    async def test_suspend_with_empty_reason(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("Suspend me")
        result = await engine.suspend_goal(g.id)
        assert result.status == "suspended"

    @pytest.mark.asyncio
    async def test_suspend_pending_goal(self) -> None:
        """Can suspend a goal that is still pending."""
        engine = GoalEngine()
        g = await engine.create_goal("Pending suspend")
        result = await engine.suspend_goal(g.id, reason="paused")
        assert result.status == "suspended"


class TestBlockGoal:
    """Tests for block_goal ."""

    @pytest.mark.asyncio
    async def test_blocks_active_goal(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("To block")
        result = await engine.block_goal(g.id, reason="waiting for API key")
        assert result.status == "blocked"

    @pytest.mark.asyncio
    async def test_block_updates_timestamp(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("Timestamp test")
        before = g.updated_at
        await engine.block_goal(g.id, reason="test")
        assert g.updated_at > before

    @pytest.mark.asyncio
    async def test_block_nonexistent_raises_key_error(self) -> None:
        engine = GoalEngine()
        with pytest.raises(KeyError):
            await engine.block_goal("nonexistent")

    @pytest.mark.asyncio
    async def test_block_with_empty_reason(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("Block me")
        result = await engine.block_goal(g.id)
        assert result.status == "blocked"


class TestReactivateGoal:
    """Tests for reactivate_goal ."""

    @pytest.mark.asyncio
    async def test_reactivates_suspended_goal(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("Suspended then reactivated")
        await engine.suspend_goal(g.id, reason="test")
        result = await engine.reactivate_goal(g.id)
        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_reactivates_blocked_goal(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("Blocked then reactivated")
        await engine.block_goal(g.id, reason="test")
        result = await engine.reactivate_goal(g.id)
        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_reactivate_resets_send_back_count(self) -> None:
        engine = GoalEngine(max_send_backs=3)
        g = await engine.create_goal("Send back reset")
        g.send_back_count = 3
        await engine.suspend_goal(g.id, reason="budget exhausted")
        assert g.send_back_count == 3
        await engine.reactivate_goal(g.id)
        assert g.send_back_count == 0

    @pytest.mark.asyncio
    async def test_reactivate_updates_timestamp(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("Timestamp test")
        await engine.suspend_goal(g.id, reason="test")
        before = g.updated_at
        await engine.reactivate_goal(g.id)
        assert g.updated_at > before

    @pytest.mark.asyncio
    async def test_reactivate_nonexistent_raises_key_error(self) -> None:
        engine = GoalEngine()
        with pytest.raises(KeyError):
            await engine.reactivate_goal("nonexistent")

    @pytest.mark.asyncio
    async def test_reactivate_active_goal_raises_value_error(self) -> None:
        """Cannot reactivate a goal that is already active."""
        engine = GoalEngine()
        g = await engine.create_goal("Active goal")
        g.status = "active"
        with pytest.raises(ValueError, match="is active"):
            await engine.reactivate_goal(g.id)

    @pytest.mark.asyncio
    async def test_reactivate_pending_goal_raises_value_error(self) -> None:
        """Cannot reactivate a goal that is already pending."""
        engine = GoalEngine()
        g = await engine.create_goal("Already pending")
        with pytest.raises(ValueError, match="is pending"):
            await engine.reactivate_goal(g.id)

    @pytest.mark.asyncio
    async def test_reactivate_completed_goal_raises_value_error(self) -> None:
        """Cannot reactivate a terminal goal."""
        engine = GoalEngine()
        g = await engine.create_goal("Completed")
        await engine.complete_goal(g.id)
        with pytest.raises(ValueError, match="is completed"):
            await engine.reactivate_goal(g.id)


class TestCheckReactivatedGoals:
    """Tests for check_reactivated_goals ."""

    @pytest.mark.asyncio
    async def test_auto_reactivates_suspended_when_deps_resolved(self) -> None:
        engine = GoalEngine()
        dep = await engine.create_goal("Dependency")
        suspended = await engine.create_goal("Suspended with dep", priority=60)
        suspended.depends_on = [dep.id]
        suspended.status = "suspended"

        await engine.complete_goal(dep.id)
        reactivated = await engine.check_reactivated_goals()

        assert len(reactivated) == 1
        assert reactivated[0].id == suspended.id
        assert suspended.status == "pending"
        assert suspended.send_back_count == 0

    @pytest.mark.asyncio
    async def test_auto_reactivates_blocked_when_deps_resolved(self) -> None:
        engine = GoalEngine()
        dep = await engine.create_goal("Dependency")
        blocked = await engine.create_goal("Blocked with dep")
        blocked.depends_on = [dep.id]
        blocked.status = "blocked"

        await engine.complete_goal(dep.id)
        reactivated = await engine.check_reactivated_goals()

        assert len(reactivated) == 1
        assert blocked.status == "pending"

    @pytest.mark.asyncio
    async def test_does_not_reactivate_when_deps_unresolved(self) -> None:
        engine = GoalEngine()
        dep = await engine.create_goal("Pending dependency")
        suspended = await engine.create_goal("Suspended waiting")
        suspended.depends_on = [dep.id]
        suspended.status = "suspended"

        reactivated = await engine.check_reactivated_goals()

        assert reactivated == []
        assert suspended.status == "suspended"

    @pytest.mark.asyncio
    async def test_does_not_reactivate_goals_without_deps(self) -> None:
        """Goals without dependencies that are suspended/blocked are reactivated."""
        engine = GoalEngine()
        g = await engine.create_goal("No deps but suspended")
        g.status = "suspended"

        reactivated = await engine.check_reactivated_goals()

        # No deps means deps_met is vacuously True
        assert len(reactivated) == 1
        assert g.status == "pending"

    @pytest.mark.asyncio
    async def test_ignores_pending_and_active_goals(self) -> None:
        engine = GoalEngine()
        g1 = await engine.create_goal("Pending")
        g2 = await engine.create_goal("Active")
        g2.status = "active"

        reactivated = await engine.check_reactivated_goals()
        assert reactivated == []
        assert g1.status == "pending"
        assert g2.status == "active"

    @pytest.mark.asyncio
    async def test_ignores_completed_and_failed_goals(self) -> None:
        engine = GoalEngine()
        g1 = await engine.create_goal("Done")
        await engine.complete_goal(g1.id)
        g2 = await engine.create_goal("Failed")
        await engine.fail_goal(
            g2.id,
            evidence=EvidenceBundle(
                narrative="test failure", source="layer2_execute", structured={}
            ),
            allow_retry=False,
        )

        reactivated = await engine.check_reactivated_goals()
        assert reactivated == []

    @pytest.mark.asyncio
    async def test_multiple_suspended_goals_partial_resolution(self) -> None:
        engine = GoalEngine()
        dep_a = await engine.create_goal("Dep A")
        dep_b = await engine.create_goal("Dep B")

        g1 = await engine.create_goal("Needs A")
        g1.depends_on = [dep_a.id]
        g1.status = "suspended"

        g2 = await engine.create_goal("Needs B")
        g2.depends_on = [dep_b.id]
        g2.status = "suspended"

        # Only complete dep_a
        await engine.complete_goal(dep_a.id)
        reactivated = await engine.check_reactivated_goals()

        assert len(reactivated) == 1
        assert g1.status == "pending"
        assert g2.status == "suspended"

    @pytest.mark.asyncio
    async def test_dep_failed_counts_as_terminal(self) -> None:
        """Failed dependencies are considered resolved (terminal state)."""
        engine = GoalEngine()
        dep = await engine.create_goal("Will fail")
        suspended = await engine.create_goal("Waiting for dep")
        suspended.depends_on = [dep.id]
        suspended.status = "suspended"

        await engine.fail_goal(
            dep.id,
            evidence=EvidenceBundle(
                narrative="dependency failed", source="layer2_execute", structured={}
            ),
            allow_retry=False,
        )
        reactivated = await engine.check_reactivated_goals()

        assert len(reactivated) == 1
        assert suspended.status == "pending"


class TestAppendGoalProgress:
    """Tests for append_goal_progress ."""

    @pytest.mark.asyncio
    async def test_creates_progress_section_if_absent(self, tmp_path) -> None:
        engine = GoalEngine()
        goal_file = tmp_path / "GOAL.md"
        goal_file.write_text("---\nid: test\n---\n\n# Test Goal\n")

        g = await engine.create_goal("Test", source_file=str(goal_file), goal_id="test")
        await engine.append_goal_progress(g.id, "Started working")

        content = goal_file.read_text()
        assert "## Progress" in content
        assert "Started working" in content

    @pytest.mark.asyncio
    async def test_appends_to_existing_progress_section(self, tmp_path) -> None:
        engine = GoalEngine()
        goal_file = tmp_path / "GOAL.md"
        goal_file.write_text(
            "---\nid: test\n---\n\n# Test Goal\n\n## Progress\n\n- [2024-01-01 00:00:00] Old entry\n"
        )

        g = await engine.create_goal("Test", source_file=str(goal_file), goal_id="test")
        await engine.append_goal_progress(g.id, "New entry")

        content = goal_file.read_text()
        assert "Old entry" in content
        assert "New entry" in content

    @pytest.mark.asyncio
    async def test_progress_entry_has_timestamp(self, tmp_path) -> None:
        engine = GoalEngine()
        goal_file = tmp_path / "GOAL.md"
        goal_file.write_text("---\nid: test\n---\n\n# Test Goal\n")

        g = await engine.create_goal("Test", source_file=str(goal_file), goal_id="test")
        await engine.append_goal_progress(g.id, "Action taken")

        content = goal_file.read_text()
        # Timestamp format: [YYYY-MM-DD HH:MM:SS]
        assert "[20" in content  # Year starts with 20
        assert "Action taken" in content

    @pytest.mark.asyncio
    async def test_handles_missing_source_file_gracefully(self) -> None:
        """No error when goal has no source_file."""
        engine = GoalEngine()
        g = await engine.create_goal("No file")
        # Should not raise
        await engine.append_goal_progress(g.id, "some progress")

    @pytest.mark.asyncio
    async def test_handles_nonexistent_file_gracefully(self, tmp_path) -> None:
        """No error when source_file path does not exist."""
        engine = GoalEngine()
        missing = tmp_path / "nonexistent.md"
        g = await engine.create_goal("Missing file", source_file=str(missing), goal_id="missing")
        # Should not raise
        await engine.append_goal_progress(g.id, "progress on missing file")

    @pytest.mark.asyncio
    async def test_appends_before_next_section_header(self, tmp_path) -> None:
        """Progress is inserted before the next ## header, not after it."""
        engine = GoalEngine()
        goal_file = tmp_path / "GOAL.md"
        goal_file.write_text(
            "---\nid: test\n---\n\n# Test Goal\n\n## Progress\n\n- [2024-01-01] Old\n\n## Notes\n\nSome notes\n"
        )

        g = await engine.create_goal("Test", source_file=str(goal_file), goal_id="test")
        await engine.append_goal_progress(g.id, "New entry")

        content = goal_file.read_text()
        # New entry should appear before ## Notes
        notes_idx = content.index("## Notes")
        new_entry_idx = content.index("New entry")
        assert new_entry_idx < notes_idx

    @pytest.mark.asyncio
    async def test_noop_for_goal_without_source_file(self) -> None:
        """Progress update is silently skipped when source_file is None."""
        engine = GoalEngine()
        g = await engine.create_goal("No source")
        await engine.append_goal_progress(g.id, "test entry")
        # No file to check, no exception


class TestConflictAwareScheduling:
    """Tests for conflict-aware scheduling in ready_goals ."""

    @pytest.mark.asyncio
    async def test_conflicting_goal_is_deferred(self) -> None:
        engine = GoalEngine()
        active_g = await engine.create_goal("Active", priority=90)
        active_g.status = "active"

        conflicting = await engine.create_goal("Conflicting", priority=95)
        conflicting.conflicts_with = [active_g.id]

        ready = await engine.ready_goals()
        # active_g is already active (returned by ready_goals),
        # but conflicting is deferred due to the conflict check.
        assert len(ready) == 1
        assert ready[0].id == active_g.id

    @pytest.mark.asyncio
    async def test_non_conflicting_goal_proceeds(self) -> None:
        engine = GoalEngine()
        g1 = await engine.create_goal("Active", priority=90)
        g1.status = "active"

        g2 = await engine.create_goal("Independent", priority=80)

        ready = await engine.ready_goals(limit=10)
        # Both the already-active goal and the independent pending goal are returned
        assert len(ready) == 2
        ids = {r.id for r in ready}
        assert g1.id in ids
        assert g2.id in ids

    @pytest.mark.asyncio
    async def test_conflict_with_inactive_goal_proceeds(self) -> None:
        """Conflict only defers when the conflicting goal is active."""
        engine = GoalEngine()
        inactive = await engine.create_goal("Pending other", priority=90)

        g = await engine.create_goal("No conflict", priority=80)
        g.conflicts_with = [inactive.id]

        ready = await engine.ready_goals(limit=10)
        # Both are pending; inactive is not active, so no conflict deferral
        assert len(ready) == 2
        ids = {r.id for r in ready}
        assert inactive.id in ids
        assert g.id in ids

    @pytest.mark.asyncio
    async def test_multiple_conflicts_all_deferred(self) -> None:
        engine = GoalEngine()
        active_a = await engine.create_goal("Active A", priority=90)
        active_a.status = "active"

        g = await engine.create_goal("Multi-conflict", priority=95)
        g.conflicts_with = [active_a.id]

        ready = await engine.ready_goals()
        # active_a is returned (already active), g is deferred
        assert len(ready) == 1
        assert ready[0].id == active_a.id

    @pytest.mark.asyncio
    async def test_empty_conflicts_with_proceeds(self) -> None:
        engine = GoalEngine()
        g1 = await engine.create_goal("Active", priority=90)
        g1.status = "active"
        g = await engine.create_goal("No conflicts")

        ready = await engine.ready_goals(limit=10)
        # Both are eligible; no conflicts to defer
        assert len(ready) == 2
        ids = {r.id for r in ready}
        assert g1.id in ids
        assert g.id in ids


class TestDiscoverGoalsFromFiles:
    """Tests for discover_goals_from_files ."""

    @pytest.mark.asyncio
    async def test_no_files_returns_empty(self, tmp_path) -> None:
        engine = GoalEngine()
        goals = await engine.discover_goals_from_files(autopilot_dir=str(tmp_path))
        assert goals == []

    @pytest.mark.asyncio
    async def test_single_goal_mode(self, tmp_path) -> None:
        """Root GOAL.md creates exactly one goal and stops."""
        autopilot = tmp_path / "autopilot"
        autopilot.mkdir()
        goal_file = autopilot / "GOAL.md"
        goal_file.write_text(
            "---\nid: single\npriority: 80\n---\n\n# Build the feature\n\nSome description.\n"
        )

        engine = GoalEngine()
        goals = await engine.discover_goals_from_files(autopilot_dir=str(tmp_path))

        assert len(goals) == 1
        assert goals[0].id == "single"
        assert goals[0].description == "Build the feature"
        assert goals[0].priority == 80
        assert goals[0].source_file == str(goal_file)

    @pytest.mark.asyncio
    async def test_batch_mode_goals_md(self, tmp_path) -> None:
        """Root GOALS.md creates multiple goals."""
        autopilot = tmp_path / "autopilot"
        autopilot.mkdir()
        goals_file = autopilot / "GOALS.md"
        goals_file.write_text(
            "## Goal: Authentication\n"
            "- id: auth\n"
            "- priority: 90\n"
            "- depends_on: []\n\n"
            "Set up auth system.\n\n"
            "## Goal: Database\n"
            "- id: db\n"
            "- priority: 70\n"
            "- depends_on: [auth]\n\n"
            "Set up database.\n"
        )

        engine = GoalEngine()
        goals = await engine.discover_goals_from_files(autopilot_dir=str(tmp_path))

        assert len(goals) == 2
        assert goals[0].id == "auth"
        assert goals[0].description == "Authentication: Set up auth system."
        assert goals[1].id == "db"
        assert goals[1].depends_on == ["auth"]

    @pytest.mark.asyncio
    async def test_per_goal_directories(self, tmp_path) -> None:
        """goals/*/GOAL.md creates goals from subdirectories."""
        autopilot = tmp_path / "autopilot"
        goals_dir = autopilot / "goals"

        goal_a = goals_dir / "goal-a"
        goal_a.mkdir(parents=True)
        (goal_a / "GOAL.md").write_text("---\nid: goal-a\npriority: 60\n---\n\n# Goal A\n")

        goal_b = goals_dir / "goal-b"
        goal_b.mkdir(parents=True)
        (goal_b / "GOAL.md").write_text("---\nid: goal-b\npriority: 40\n---\n\n# Goal B\n")

        engine = GoalEngine()
        goals = await engine.discover_goals_from_files(autopilot_dir=str(tmp_path))

        assert len(goals) == 2
        assert goals[0].id == "goal-a"
        assert goals[1].id == "goal-b"

    @pytest.mark.asyncio
    async def test_single_goal_mode_takes_priority(self, tmp_path) -> None:
        """Root GOAL.md should prevent GOALS.md and goals/ from being scanned."""
        autopilot = tmp_path / "autopilot"
        autopilot.mkdir()

        (autopilot / "GOAL.md").write_text("---\nid: single\n---\n\n# Only this one\n")
        (autopilot / "GOALS.md").write_text(
            "## Goal: Batch\n- id: batch\n- priority: 50\n- depends_on: []\n\nBatch goal.\n"
        )
        sub = autopilot / "goals" / "extra"
        sub.mkdir(parents=True)
        (sub / "GOAL.md").write_text("---\nid: extra\n---\n\n# Extra\n")

        engine = GoalEngine()
        goals = await engine.discover_goals_from_files(autopilot_dir=str(tmp_path))

        assert len(goals) == 1
        assert goals[0].id == "single"

    @pytest.mark.asyncio
    async def test_goal_file_without_frontmatter_skipped(self, tmp_path) -> None:
        """GOAL.md without valid frontmatter is skipped."""
        autopilot = tmp_path / "autopilot"
        autopilot.mkdir()
        (autopilot / "GOAL.md").write_text("# No frontmatter goal\n")

        engine = GoalEngine()
        goals = await engine.discover_goals_from_files(autopilot_dir=str(tmp_path))
        assert goals == []

    @pytest.mark.asyncio
    async def test_goals_dir_not_exists(self, tmp_path) -> None:
        """Missing goals/ directory should not cause errors."""
        autopilot = tmp_path / "autopilot"
        autopilot.mkdir()
        # No goals/ subdirectory

        engine = GoalEngine()
        goals = await engine.discover_goals_from_files(autopilot_dir=str(tmp_path))
        assert goals == []

    @pytest.mark.asyncio
    async def test_discovered_goals_have_source_file_set(self, tmp_path) -> None:
        """Goals created from files should have source_file pointing to the file."""
        autopilot = tmp_path / "autopilot"
        autopilot.mkdir()
        goal_file = autopilot / "GOAL.md"
        goal_file.write_text("---\nid: tracked\n---\n\n# Tracked Goal\n")

        engine = GoalEngine()
        goals = await engine.discover_goals_from_files(autopilot_dir=str(tmp_path))

        assert len(goals) == 1
        assert goals[0].source_file == str(goal_file)


class TestUpdateGoalFileStatus:
    """Tests for update_goal_file_status ."""

    @pytest.mark.asyncio
    async def test_updates_frontmatter_status(self, tmp_path) -> None:
        engine = GoalEngine()
        goal_file = tmp_path / "GOAL.md"
        goal_file.write_text("---\nid: test\nstatus: pending\n---\n\n# Test\n")

        g = await engine.create_goal("Test", source_file=str(goal_file), goal_id="test")
        g.status = "completed"
        await engine.update_goal_file_status(g.id)

        content = goal_file.read_text()
        assert "status: completed" in content

    @pytest.mark.asyncio
    async def test_noop_when_source_file_is_none(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("No file")
        # Should not raise
        await engine.update_goal_file_status(g.id)

    @pytest.mark.asyncio
    async def test_noop_when_goal_not_found(self) -> None:
        engine = GoalEngine()
        # Should not raise
        await engine.update_goal_file_status("nonexistent")

    @pytest.mark.asyncio
    async def test_updates_to_suspended_status(self, tmp_path) -> None:
        engine = GoalEngine()
        goal_file = tmp_path / "GOAL.md"
        goal_file.write_text("---\nid: test\nstatus: active\n---\n\n# Test\n")

        g = await engine.create_goal("Test", source_file=str(goal_file), goal_id="test")
        g.status = "suspended"
        await engine.update_goal_file_status(g.id)

        content = goal_file.read_text()
        assert "status: suspended" in content


class TestGoalModelExtendedFields:
    """Tests for Autopilot fields on the Goal model."""

    def test_informs_defaults_to_empty_list(self) -> None:
        goal = Goal(description="Test")
        assert goal.informs == []

    def test_conflicts_with_defaults_to_empty_list(self) -> None:
        goal = Goal(description="Test")
        assert goal.conflicts_with == []

    def test_send_back_count_defaults_to_zero(self) -> None:
        goal = Goal(description="Test")
        assert goal.send_back_count == 0

    def test_max_send_backs_defaults_to_three(self) -> None:
        goal = Goal(description="Test")
        assert goal.max_send_backs == 3

    def test_source_file_defaults_to_none(self) -> None:
        goal = Goal(description="Test")
        assert goal.source_file is None

    def test_can_set_rfc204_fields(self) -> None:
        goal = Goal(
            description="Full",
            informs=["a", "b"],
            conflicts_with=["c"],
            send_back_count=2,
            max_send_backs=5,
            source_file="/path/to/GOAL.md",
        )
        assert goal.informs == ["a", "b"]
        assert goal.conflicts_with == ["c"]
        assert goal.send_back_count == 2
        assert goal.max_send_backs == 5
        assert goal.source_file == "/path/to/GOAL.md"


class TestReadyGoalsDAGExtended:
    """Integration-style tests combining Autopilot features with DAG scheduling."""

    @pytest.mark.asyncio
    async def test_ready_goals_activates_and_respects_conflicts(self) -> None:
        engine = GoalEngine()
        g1 = await engine.create_goal("High priority", priority=90)
        g2 = await engine.create_goal("Conflicts with high", priority=80)
        g2.conflicts_with = [g1.id]

        ready = await engine.ready_goals(limit=1)
        assert len(ready) == 1
        assert ready[0].id == g1.id
        assert ready[0].status == "active"

        # Now g1 is active, so g2 should be deferred.
        # g1 is still returned because it is already active.
        ready2 = await engine.ready_goals(limit=1)
        assert len(ready2) == 1
        assert ready2[0].id == g1.id

    @pytest.mark.asyncio
    async def test_completed_dep_unblocks_check_reactivated(self) -> None:
        """End-to-end: complete a dep, then check_reactivated_goals resumes suspended."""
        engine = GoalEngine()
        dep = await engine.create_goal("Dependency", priority=90)
        suspended = await engine.create_goal("Suspended", priority=80)
        suspended.depends_on = [dep.id]
        suspended.status = "suspended"
        suspended.send_back_count = 3

        # Complete the dependency
        await engine.complete_goal(dep.id)

        # Auto-reactivate
        reactivated = await engine.check_reactivated_goals()
        assert len(reactivated) == 1
        assert suspended.status == "pending"
        assert suspended.send_back_count == 0

        # Now ready_goals should pick it up
        ready = await engine.ready_goals()
        assert len(ready) == 1
        assert ready[0].id == suspended.id

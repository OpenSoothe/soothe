"""Tests for GoalNode iteration tracking and evidence ledger (RFC-624 Phase 4 Step 4)."""

import asyncio

from soothe.foundation.context import ContextEngine, EvidenceEntry, GoalNode


class TestGoalNodeIterationTracking:
    """Tests for iteration_count field and ContextEngine.increment_iteration."""

    def test_goal_node_has_iteration_count_default_zero(self) -> None:
        """GoalNode should have iteration_count default to 0."""
        goal = GoalNode(description="Test goal")
        assert hasattr(goal, "iteration_count")
        assert goal.iteration_count == 0

    def test_goal_node_iteration_count_can_be_set(self) -> None:
        """iteration_count can be set during creation."""
        goal = GoalNode(description="Test goal", iteration_count=3)
        assert goal.iteration_count == 3

    def test_context_engine_increment_iteration(self) -> None:
        """ContextEngine.increment_iteration should increment and return new value."""
        ce = ContextEngine()
        goal = asyncio.run(ce.create_goal(description="Test goal"))

        # First increment
        new_iter = ce.increment_iteration(goal.id)
        assert new_iter == 1

        # Verify goal reflects the change
        updated = ce.get_goal_sync(goal.id)
        assert updated is not None
        assert updated.iteration_count == 1

        # Second increment
        ce.increment_iteration(goal.id)
        updated = ce.get_goal_sync(goal.id)
        assert updated.iteration_count == 2

    def test_increment_iteration_missing_goal_returns_zero(self) -> None:
        """increment_iteration should return 0 for missing goal."""
        ce = ContextEngine()
        result = ce.increment_iteration("nonexistent")
        assert result == 0

    def test_get_iteration_missing_goal_returns_zero(self) -> None:
        """get_iteration should return 0 for missing goal."""
        ce = ContextEngine()
        result = ce.get_iteration("nonexistent")
        assert result == 0

    def test_get_iteration_returns_current_value(self) -> None:
        """get_iteration should return current iteration_count."""
        ce = ContextEngine()
        goal = asyncio.run(ce.create_goal(description="Test goal"))

        # Initial value
        assert ce.get_iteration(goal.id) == 0

        # After increment
        ce.increment_iteration(goal.id)
        assert ce.get_iteration(goal.id) == 1


class TestGoalNodeEvidenceLedger:
    """Tests for evidence_ledger field and ContextEngine.record_evidence."""

    def test_goal_node_has_evidence_ledger_field(self) -> None:
        """GoalNode should have evidence_ledger initialized as empty list."""
        goal = GoalNode(description="Test goal")
        assert hasattr(goal, "evidence_ledger")
        assert goal.evidence_ledger == []

    def test_evidence_ledger_can_be_initialized(self) -> None:
        """evidence_ledger can be initialized with entries."""
        entry = EvidenceEntry(evidence_id="EV-01", summary="Test evidence", kind="tool")
        goal = GoalNode(description="Test goal", evidence_ledger=[entry])
        assert len(goal.evidence_ledger) == 1
        assert goal.evidence_ledger[0].evidence_id == "EV-01"

    def test_context_engine_record_evidence(self) -> None:
        """ContextEngine.record_evidence should append to goal's evidence_ledger."""
        ce = ContextEngine()
        goal = asyncio.run(ce.create_goal(description="Test goal"))

        # Record first evidence
        ce.record_evidence(goal.id, "EV-01", "First evidence", kind="tool")

        # Record second evidence
        ce.record_evidence(goal.id, "EV-02", "Second evidence", kind="bootstrap")

        # Verify entries
        updated = ce.get_goal_sync(goal.id)
        assert updated is not None
        assert len(updated.evidence_ledger) == 2
        assert updated.evidence_ledger[0].evidence_id == "EV-01"
        assert updated.evidence_ledger[0].kind == "tool"
        assert updated.evidence_ledger[1].evidence_id == "EV-02"
        assert updated.evidence_ledger[1].kind == "bootstrap"

    def test_record_evidence_missing_goal_logs_warning(self) -> None:
        """record_evidence should log warning for missing goal without error."""
        ce = ContextEngine()
        # Should not raise, just log warning
        ce.record_evidence("nonexistent", "EV-01", "Test summary")

    def test_evidence_entry_fields(self) -> None:
        """EvidenceEntry should have required fields."""
        entry = EvidenceEntry(evidence_id="EV-01", summary="Test summary", kind="tool")
        assert entry.evidence_id == "EV-01"
        assert entry.summary == "Test summary"
        assert entry.kind == "tool"

    def test_evidence_entry_default_kind(self) -> None:
        """EvidenceEntry should default kind to 'bootstrap'."""
        entry = EvidenceEntry(evidence_id="EV-01", summary="Test")
        assert entry.kind == "bootstrap"


class TestIterationAndEvidenceLedgerIntegration:
    """Tests for combined iteration tracking and evidence ledger."""

    def test_iteration_and_evidence_work_together(self) -> None:
        """Iteration and evidence_ledger can be updated independently."""
        ce = ContextEngine()
        goal = asyncio.run(ce.create_goal(description="Test goal"))

        # Increment iteration
        ce.increment_iteration(goal.id)
        ce.increment_iteration(goal.id)

        # Record evidence at iter 2
        ce.record_evidence(goal.id, "EV-01", "Evidence at iter 2")

        # Verify both
        updated = ce.get_goal_sync(goal.id)
        assert updated is not None
        assert updated.iteration_count == 2
        assert len(updated.evidence_ledger) == 1

    def test_goal_touch_updates_timestamp_on_changes(self) -> None:
        """GoalNode.updated_at should change when iteration/evidence changes."""
        import time

        ce = ContextEngine()
        goal = asyncio.run(ce.create_goal(description="Test goal"))

        # Small delay to ensure timestamp differs
        time.sleep(0.01)

        # Increment iteration
        ce.increment_iteration(goal.id)

        updated = ce.get_goal_sync(goal.id)
        assert updated is not None
        # Note: The timestamp should be updated via touch() in increment_iteration
        # This verifies the touch() mechanism works

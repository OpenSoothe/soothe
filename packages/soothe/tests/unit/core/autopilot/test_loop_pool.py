"""Unit tests for LoopPool models (RFC-222, IG-295)."""

from soothe.core.autopilot.loop_pool import LoopHandle, LoopPool


class TestLoopHandle:
    """Tests for LoopHandle model."""

    def test_create_loop_handle(self) -> None:
        """Test basic LoopHandle creation."""
        loop = LoopHandle()
        assert loop.loop_id
        assert loop.status == "idle"
        assert loop.current_goal_id is None
        assert loop.goal_history == []
        assert loop.idle_since is None

    def test_assign_goal(self) -> None:
        """Test goal assignment."""
        loop = LoopHandle()
        loop.assign_goal("goal-001")

        assert loop.current_goal_id == "goal-001"
        assert loop.status == "active"
        assert loop.idle_since is None

    def test_assign_goal_adds_to_history(self) -> None:
        """Test that assigning new goal adds previous to history."""
        loop = LoopHandle()
        loop.assign_goal("goal-001")
        loop.assign_goal("goal-002")

        assert loop.current_goal_id == "goal-002"
        assert loop.goal_history == ["goal-001"]

    def test_release_goal_success(self) -> None:
        """Test goal release on success."""
        loop = LoopHandle()
        loop.assign_goal("goal-001")
        loop.release_goal(success=True)

        assert loop.current_goal_id is None
        assert loop.status == "idle"
        assert loop.idle_since is not None
        assert "goal-001" in loop.goal_history

    def test_release_goal_failure(self) -> None:
        """Test goal release on failure."""
        loop = LoopHandle()
        loop.assign_goal("goal-001")
        loop.release_goal(success=False)

        assert loop.status == "error"
        assert "goal-001" in loop.goal_history

    def test_mark_idle(self) -> None:
        """Test marking loop idle without goal release."""
        loop = LoopHandle()
        loop.assign_goal("goal-001")
        loop.release_goal(success=True)

        assert loop.status == "idle"
        assert loop.idle_since is not None

    def test_get_history_count(self) -> None:
        """Test history count calculation."""
        loop = LoopHandle()
        assert loop.get_history_count() == 0

        loop.assign_goal("goal-001")
        assert loop.get_history_count() == 1

        loop.assign_goal("goal-002")
        assert loop.get_history_count() == 2

    def test_can_reuse_for_child_current_goal(self) -> None:
        """Test reuse check when parent is current goal."""
        loop = LoopHandle()
        loop.assign_goal("goal-parent")

        assert loop.can_reuse_for_child("goal-parent")

    def test_can_reuse_for_child_from_history(self) -> None:
        """Test reuse check when parent is in history."""
        loop = LoopHandle()
        loop.assign_goal("goal-parent")
        loop.release_goal(success=True)
        loop.assign_goal("goal-other")

        # Parent should be in history last position
        assert "goal-parent" in loop.goal_history
        # Cannot reuse since current goal is different
        assert not loop.can_reuse_for_child("goal-parent")

    def test_can_reuse_for_child_error_status(self) -> None:
        """Test reuse check fails for error status."""
        loop = LoopHandle()
        loop.assign_goal("goal-parent")
        loop.status = "error"

        assert not loop.can_reuse_for_child("goal-parent")


class TestLoopPool:
    """Tests for LoopPool model."""

    def test_create_pool(self) -> None:
        """Test basic LoopPool creation."""
        pool = LoopPool()
        assert pool.loops == {}
        assert pool.idle_loops == []
        assert pool.max_loops == 4
        assert pool.active_tasks == {}

    def test_active_count(self) -> None:
        """Test active loop count."""
        pool = LoopPool(max_loops=4)

        loop1 = LoopHandle(status="active")
        loop2 = LoopHandle(status="idle")
        loop3 = LoopHandle(status="active")

        pool.add_loop(loop1)
        pool.add_loop(loop2)
        pool.add_loop(loop3)

        assert pool.active_count() == 2

    def test_idle_count(self) -> None:
        """Test idle loop count."""
        pool = LoopPool(max_loops=4)

        loop1 = LoopHandle(status="active")
        loop2 = LoopHandle(status="idle")
        loop3 = LoopHandle(status="idle")

        pool.add_loop(loop1)
        pool.add_loop(loop2)
        pool.add_loop(loop3)

        assert pool.idle_count() == 2

    def test_can_spawn(self) -> None:
        """Test spawn capacity check."""
        pool = LoopPool(max_loops=4)
        assert pool.can_spawn()

        for i in range(4):
            pool.add_loop(LoopHandle())

        assert not pool.can_spawn()

    def test_add_loop(self) -> None:
        """Test adding loop to pool."""
        pool = LoopPool()
        loop = LoopHandle(status="idle")

        pool.add_loop(loop)

        assert loop.loop_id in pool.loops
        assert loop.loop_id in pool.idle_loops

    def test_remove_loop(self) -> None:
        """Test removing loop from pool."""
        pool = LoopPool()
        loop = LoopHandle(status="active")
        pool.add_loop(loop)

        removed = pool.remove_loop(loop.loop_id)

        assert removed == loop
        assert loop.loop_id not in pool.loops

    def test_pop_idle_loop(self) -> None:
        """Test getting idle loop from queue."""
        pool = LoopPool()
        loop1 = LoopHandle(status="idle")
        loop2 = LoopHandle(status="idle")

        pool.add_loop(loop1)
        pool.add_loop(loop2)

        popped = pool.pop_idle_loop()

        assert popped == loop1
        assert loop1.loop_id not in pool.idle_loops
        assert loop2.loop_id in pool.idle_loops

    def test_assign_loop_to_goal(self) -> None:
        """Test assigning loop to goal."""
        pool = LoopPool()
        loop = LoopHandle(status="idle")
        pool.add_loop(loop)

        pool.assign_loop_to_goal(loop, "goal-001")

        assert loop.current_goal_id == "goal-001"
        assert loop.status == "active"
        assert pool.goal_to_loop["goal-001"] == loop.loop_id
        assert loop.loop_id not in pool.idle_loops

    def test_record_goal_completion(self) -> None:
        """Test recording goal completion."""
        pool = LoopPool()
        loop = LoopHandle(status="active", current_goal_id="goal-001")
        pool.add_loop(loop)

        pool.record_goal_completion("goal-001", loop.loop_id)

        assert loop.status == "idle"
        assert loop.loop_id in pool.idle_loops
        assert pool.goal_to_loop["goal-001"] == loop.loop_id

    def test_record_goal_failure(self) -> None:
        """Test recording goal failure."""
        pool = LoopPool()
        loop = LoopHandle(status="active", current_goal_id="goal-001")
        pool.add_loop(loop)

        pool.record_goal_failure("goal-001", loop.loop_id)

        assert loop.status == "error"
        assert pool.goal_to_loop["goal-001"] == loop.loop_id

    def test_has_capacity(self) -> None:
        """Test capacity check."""
        pool = LoopPool(max_loops=2)

        # Empty pool has capacity
        assert pool.has_capacity()

        # Add one active loop
        loop1 = LoopHandle(status="active")
        pool.add_loop(loop1)
        assert pool.has_capacity()  # Can spawn

        # Add one idle loop
        loop2 = LoopHandle(status="idle")
        pool.add_loop(loop2)
        assert pool.has_capacity()  # Has idle

        # Fill to max with active
        pool.idle_loops.clear()
        pool.add_loop(LoopHandle(status="active"))
        pool.add_loop(LoopHandle(status="active"))  # Would exceed max

        # Now at max with no idle
        assert not pool.has_capacity()

    def test_get_loop_for_goal(self) -> None:
        """Test retrieving loop for a goal."""
        pool = LoopPool()
        loop = LoopHandle()
        pool.add_loop(loop)
        pool.goal_to_loop["goal-001"] = loop.loop_id

        retrieved = pool.get_loop_for_goal("goal-001")

        assert retrieved == loop

    def test_remove_loop_cleans_mappings(self) -> None:
        """Test that removing loop cleans goal-to-loop mappings."""
        pool = LoopPool()
        loop = LoopHandle()
        pool.add_loop(loop)
        pool.goal_to_loop["goal-001"] = loop.loop_id
        pool.goal_to_loop["goal-002"] = loop.loop_id

        pool.remove_loop(loop.loop_id)

        assert "goal-001" not in pool.goal_to_loop
        assert "goal-002" not in pool.goal_to_loop

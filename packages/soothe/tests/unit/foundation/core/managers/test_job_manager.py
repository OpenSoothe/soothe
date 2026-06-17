"""Unit tests for JobManager lifecycle transitions and checkpoint persistence (RFC-228, RFC-626)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.foundation.context.models import GoalNode
from soothe.foundation.core.entities import Job, JobState
from soothe.foundation.core.managers.job_manager import JobManager


@pytest.fixture
def mock_context_engine():
    """Create mock ContextEngine for testing."""
    ce = MagicMock()
    ce.create_goal = AsyncMock()
    ce.get_goal = AsyncMock()
    ce.suspend_goal = AsyncMock()
    ce.reactivate_goal = AsyncMock()
    ce.cancel_goal = AsyncMock()
    ce.list_goals = AsyncMock()
    return ce


@pytest.fixture
def mock_persist_store():
    """Create mock AsyncPersistStore for testing."""
    store = MagicMock()
    store.save = AsyncMock()
    store.load = AsyncMock()
    store.delete = AsyncMock()
    store.list_keys = AsyncMock(return_value=[])
    return store


@pytest.fixture
def sample_goal_node():
    """Create sample GoalNode for testing."""
    return GoalNode(
        id="test1234",
        description="Test job description",
        status="pending",
        priority=50,
        parent_id=None,  # Root goal
        workspace="/tmp/workspace",
        source_file="/tmp/GOAL.md",
        total_tokens_used=100,
        total_duration_ms=5000,
        guidance_accumulated=[{"text": "guidance1"}],
    )


class TestJobManagerLifecycle:
    """Tests for job lifecycle transitions."""

    @pytest.mark.asyncio
    async def test_create_job_success(
        self, mock_context_engine, mock_persist_store, sample_goal_node
    ):
        """Test successful job creation."""
        mock_context_engine.create_goal.return_value = sample_goal_node

        manager = JobManager(ce=mock_context_engine, persist_store=mock_persist_store)
        job = await manager.create_job(
            "Test job description",
            priority=75,
            workspace="/tmp/workspace",
            source_file="/tmp/GOAL.md",
        )

        # Verify ContextEngine was called
        mock_context_engine.create_goal.assert_called_once_with(
            "Test job description",
            priority=75,
            parent_id=None,
            workspace="/tmp/workspace",
            source_file="/tmp/GOAL.md",
        )

        # Verify job properties
        assert job.id == "test1234"
        assert job.description == "Test job description"
        assert job.state == JobState.PENDING
        assert job.priority == 50
        assert job.workspace == "/tmp/workspace"

        # Verify checkpoint was persisted
        mock_persist_store.save.assert_called_once()
        call_args = mock_persist_store.save.call_args
        assert call_args[0][0] == "autopilot:job_checkpoint:test1234"

    @pytest.mark.asyncio
    async def test_pause_job_success(self, mock_context_engine, mock_persist_store):
        """Test successful job pause transition."""
        # Setup: goal in active state
        active_goal = GoalNode(
            id="test1234",
            description="Active job",
            status="active",
            priority=50,
            parent_id=None,
            assigned_loop_id="loop001",
        )
        suspended_goal = GoalNode(
            id="test1234",
            description="Active job",
            status="suspended",
            priority=50,
            parent_id=None,
            assigned_loop_id="loop001",
        )

        mock_context_engine.get_goal.side_effect = [active_goal, suspended_goal]

        manager = JobManager(ce=mock_context_engine, persist_store=mock_persist_store)
        job = await manager.pause_job("test1234", reason="user_request")

        # Verify suspend_goal was called
        mock_context_engine.suspend_goal.assert_called_once_with("test1234", reason="user_request")

        # Verify returned job state
        assert job is not None
        assert job.state == JobState.SUSPENDED

        # Verify checkpoint was persisted
        mock_persist_store.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_pause_job_terminal_state_raises(self, mock_context_engine, mock_persist_store):
        """Test pause on terminal state raises ValueError."""
        completed_goal = GoalNode(
            id="test1234",
            description="Completed job",
            status="completed",
            priority=50,
            parent_id=None,
        )
        mock_context_engine.get_goal.return_value = completed_goal

        manager = JobManager(ce=mock_context_engine, persist_store=mock_persist_store)

        with pytest.raises(ValueError, match="terminal state"):
            await manager.pause_job("test1234")

    @pytest.mark.asyncio
    async def test_pause_job_not_found(self, mock_context_engine, mock_persist_store):
        """Test pause on non-existent job returns None."""
        mock_context_engine.get_goal.return_value = None

        manager = JobManager(ce=mock_context_engine, persist_store=mock_persist_store)
        job = await manager.pause_job("nonexistent")

        assert job is None
        mock_context_engine.suspend_goal.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_job_success(self, mock_context_engine, mock_persist_store):
        """Test successful job resume transition."""
        suspended_goal = GoalNode(
            id="test1234",
            description="Suspended job",
            status="suspended",
            priority=50,
            parent_id=None,
        )
        pending_goal = GoalNode(
            id="test1234",
            description="Resumed job",
            status="pending",
            priority=50,
            parent_id=None,
        )

        mock_context_engine.get_goal.side_effect = [suspended_goal, pending_goal]

        manager = JobManager(ce=mock_context_engine, persist_store=mock_persist_store)
        job = await manager.resume_job("test1234")

        # Verify reactivate_goal was called
        mock_context_engine.reactivate_goal.assert_called_once_with("test1234")

        # Verify returned job state
        assert job is not None
        assert job.state == JobState.PENDING

        # Verify checkpoint was persisted
        mock_persist_store.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_resume_job_not_suspended_raises(self, mock_context_engine, mock_persist_store):
        """Test resume on non-suspended job raises ValueError."""
        active_goal = GoalNode(
            id="test1234",
            description="Active job",
            status="active",
            priority=50,
            parent_id=None,
        )
        mock_context_engine.get_goal.return_value = active_goal

        manager = JobManager(ce=mock_context_engine, persist_store=mock_persist_store)

        with pytest.raises(ValueError, match="not suspended"):
            await manager.resume_job("test1234")

    @pytest.mark.asyncio
    async def test_cancel_job_success(self, mock_context_engine, mock_persist_store):
        """Test successful job cancel transition."""
        pending_goal = GoalNode(
            id="test1234",
            description="Pending job",
            status="pending",
            priority=50,
            parent_id=None,
        )
        cancelled_goal = GoalNode(
            id="test1234",
            description="Cancelled job",
            status="cancelled",
            priority=50,
            parent_id=None,
        )

        mock_context_engine.get_goal.side_effect = [pending_goal, cancelled_goal]

        manager = JobManager(ce=mock_context_engine, persist_store=mock_persist_store)
        job = await manager.cancel_job("test1234", reason="user_cancelled")

        # Verify cancel_goal was called
        mock_context_engine.cancel_goal.assert_called_once_with("test1234", reason="user_cancelled")

        # Verify returned job state
        assert job is not None
        assert job.state == JobState.CANCELLED

        # Verify checkpoint was persisted
        mock_persist_store.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_job_terminal_raises(self, mock_context_engine, mock_persist_store):
        """Test cancel on terminal state raises ValueError."""
        completed_goal = GoalNode(
            id="test1234",
            description="Completed job",
            status="completed",
            priority=50,
            parent_id=None,
        )
        mock_context_engine.get_goal.return_value = completed_goal

        manager = JobManager(ce=mock_context_engine, persist_store=mock_persist_store)

        with pytest.raises(ValueError, match="terminal state"):
            await manager.cancel_job("test1234")


class TestJobManagerQueries:
    """Tests for job status queries."""

    @pytest.mark.asyncio
    async def test_get_job_success(self, mock_context_engine, sample_goal_node):
        """Test successful job retrieval."""
        mock_context_engine.get_goal.return_value = sample_goal_node

        manager = JobManager(ce=mock_context_engine)
        job = await manager.get_job("test1234")

        assert job is not None
        assert job.id == "test1234"
        assert job.description == "Test job description"

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, mock_context_engine):
        """Test job retrieval for non-existent job."""
        mock_context_engine.get_goal.return_value = None

        manager = JobManager(ce=mock_context_engine)
        job = await manager.get_job("nonexistent")

        assert job is None

    @pytest.mark.asyncio
    async def test_list_jobs_filters_root_goals(self, mock_context_engine):
        """Test list_jobs only returns root goals."""
        root_goal = GoalNode(id="root1", description="Root", status="pending", parent_id=None)
        child_goal = GoalNode(id="child1", description="Child", status="pending", parent_id="root1")

        mock_context_engine.list_goals.return_value = [root_goal, child_goal]

        manager = JobManager(ce=mock_context_engine)
        jobs = await manager.list_jobs()

        # Should only return root goals
        assert len(jobs) == 1
        assert jobs[0].id == "root1"

    @pytest.mark.asyncio
    async def test_list_jobs_status_filter(self, mock_context_engine):
        """Test list_jobs with status filter."""
        pending_goal = GoalNode(id="p1", description="Pending", status="pending", parent_id=None)
        active_goal = GoalNode(id="a1", description="Active", status="active", parent_id=None)

        mock_context_engine.list_goals.return_value = [pending_goal, active_goal]

        manager = JobManager(ce=mock_context_engine)
        jobs = await manager.list_jobs(status=JobState.PENDING)

        # Should filter by status
        assert len(jobs) == 1
        assert jobs[0].id == "p1"

        # Verify list_goals was called with status filter
        mock_context_engine.list_goals.assert_called_once_with(status="pending")

    @pytest.mark.asyncio
    async def test_get_job_status_response(self, mock_context_engine):
        """Test get_job_status_response builds IPC response."""
        root_goal = GoalNode(
            id="job1",
            description="Root job",
            status="active",
            priority=50,
            parent_id=None,
            assigned_loop_id="loop001",
            total_tokens_used=500,
            total_duration_ms=10000,
        )
        child_goal = GoalNode(
            id="child1",
            description="Child goal",
            status="completed",
            priority=50,
            parent_id="job1",
        )

        mock_context_engine.get_goal.return_value = root_goal
        mock_context_engine.list_goals.return_value = [root_goal, child_goal]

        manager = JobManager(ce=mock_context_engine)
        response = await manager.get_job_status_response("job1")

        assert response is not None
        assert response["job_id"] == "job1"
        assert response["status"] == "active"
        assert response["total_goals"] == 2  # Root + child
        assert response["completed_goals"] == 1  # Child completed
        assert response["active_goals"] == 1  # Root active
        assert response["total_tokens_used"] == 500
        assert response["worker_id"] == "loop001"


class TestJobManagerCheckpointPersistence:
    """Tests for checkpoint persistence."""

    @pytest.mark.asyncio
    async def test_get_job_checkpoint_from_persistence(
        self, mock_context_engine, mock_persist_store
    ):
        """Test checkpoint retrieval from persistence store."""
        checkpoint_data = {
            "job_id": "test1234",
            "state": "pending",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "total_goals": 1,
            "completed_goals": 0,
            "failed_goals": 0,
            "active_goals": 0,
            "total_tokens_used": 100,
            "total_duration_ms": 5000,
            "schema_version": "1.0",
        }
        mock_persist_store.load.return_value = checkpoint_data

        manager = JobManager(ce=mock_context_engine, persist_store=mock_persist_store)
        checkpoint = await manager.get_job_checkpoint("test1234")

        assert checkpoint is not None
        assert checkpoint.job_id == "test1234"
        assert checkpoint.state == JobState.PENDING

    @pytest.mark.asyncio
    async def test_get_job_checkpoint_fallback_without_store(
        self, mock_context_engine, sample_goal_node
    ):
        """Test checkpoint builds from ContextEngine when no store."""
        mock_context_engine.get_goal.return_value = sample_goal_node

        manager = JobManager(ce=mock_context_engine, persist_store=None)
        checkpoint = await manager.get_job_checkpoint("test1234")

        assert checkpoint is not None
        assert checkpoint.job_id == "test1234"

    @pytest.mark.asyncio
    async def test_restore_checkpoints_on_startup(
        self, mock_context_engine, mock_persist_store, sample_goal_node
    ):
        """Test checkpoint restoration on daemon startup."""
        mock_persist_store.list_keys.return_value = ["autopilot:job_checkpoint:test1234"]
        mock_context_engine.get_goal.return_value = sample_goal_node

        # Mock checkpoint data for load call
        checkpoint_data = {
            "job_id": "test1234",
            "state": "pending",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "total_goals": 1,
            "completed_goals": 0,
            "failed_goals": 0,
            "active_goals": 0,
            "total_tokens_used": 100,
            "total_duration_ms": 5000,
            "schema_version": "1.0",
        }
        mock_persist_store.load.return_value = checkpoint_data

        manager = JobManager(ce=mock_context_engine, persist_store=mock_persist_store)
        restored = await manager.restore_checkpoints()

        assert "test1234" in restored
        mock_persist_store.list_keys.assert_called_once()

    @pytest.mark.asyncio
    async def test_restore_checkpoints_deletes_orphaned(
        self, mock_context_engine, mock_persist_store
    ):
        """Test orphaned checkpoints are deleted on restore."""
        mock_persist_store.list_keys.return_value = ["autopilot:job_checkpoint:orphan1"]
        mock_context_engine.get_goal.return_value = None  # Goal missing

        manager = JobManager(ce=mock_context_engine, persist_store=mock_persist_store)
        restored = await manager.restore_checkpoints()

        assert len(restored) == 0
        mock_persist_store.delete.assert_called_once_with("autopilot:job_checkpoint:orphan1")

    @pytest.mark.asyncio
    async def test_delete_checkpoint_success(self, mock_context_engine, mock_persist_store):
        """Test checkpoint deletion."""
        mock_persist_store.load.return_value = {"job_id": "test1234"}

        manager = JobManager(ce=mock_context_engine, persist_store=mock_persist_store)
        deleted = await manager.delete_checkpoint("test1234")

        assert deleted
        mock_persist_store.delete.assert_called_once_with("autopilot:job_checkpoint:test1234")

    @pytest.mark.asyncio
    async def test_delete_checkpoint_not_found(self, mock_context_engine, mock_persist_store):
        """Test checkpoint deletion when not found."""
        mock_persist_store.load.return_value = None

        manager = JobManager(ce=mock_context_engine, persist_store=mock_persist_store)
        deleted = await manager.delete_checkpoint("nonexistent")

        assert not deleted
        mock_persist_store.delete.assert_not_called()


class TestJobManagerHelpers:
    """Tests for helper methods."""

    def test_goal_to_job_mapping(self, mock_context_engine, sample_goal_node):
        """Test GoalNode to Job conversion."""
        manager = JobManager(ce=mock_context_engine)
        job = manager._goal_to_job(sample_goal_node)

        assert job.id == "test1234"
        assert job.description == "Test job description"
        assert job.state == JobState.PENDING
        assert job.worker_id == sample_goal_node.assigned_loop_id
        assert job.workspace == "/tmp/workspace"
        assert job.guidance_count == 1

    def test_goal_to_job_status_mapping(self, mock_context_engine):
        """Test all status mappings from GoalNode to Job."""
        manager = JobManager(ce=mock_context_engine)

        status_map = {
            "pending": JobState.PENDING,
            "active": JobState.ACTIVE,
            "completed": JobState.COMPLETED,
            "failed": JobState.FAILED,
            "cancelled": JobState.CANCELLED,
            "suspended": JobState.SUSPENDED,
            "blocked": JobState.BLOCKED,
            "validated": JobState.VALIDATED,
            "awaiting_clarification": JobState.AWAITING_CLARIFICATION,
        }

        for goal_status, expected_state in status_map.items():
            goal = GoalNode(id="test", description="Test", status=goal_status, parent_id=None)
            job = manager._goal_to_job(goal)
            assert job.state == expected_state

    def test_build_checkpoint_from_job(self, mock_context_engine):
        """Test JobCheckpoint building from Job."""
        job = Job(
            id="test1234",
            description="Test job",
            state=JobState.ACTIVE,
            priority=50,
            worker_id="loop001",
            total_goals=3,
            completed_goals=1,
            failed_goals=0,
            active_goals=1,
            total_tokens_used=500,
            total_duration_ms=10000,
        )

        manager = JobManager(ce=mock_context_engine)
        checkpoint = manager._build_checkpoint(job)

        assert checkpoint.job_id == "test1234"
        assert checkpoint.state == JobState.ACTIVE
        assert checkpoint.total_goals == 3
        assert checkpoint.completed_goals == 1
        assert checkpoint.schema_version == "1.0"

    def test_collect_descendant_ids(self, mock_context_engine):
        """Test descendant goal collection."""
        # Build hierarchy: root → child1 → grandchild
        goals = [
            GoalNode(id="root", description="Root", status="pending", parent_id=None),
            GoalNode(id="child1", description="Child1", status="pending", parent_id="root"),
            GoalNode(id="child2", description="Child2", status="pending", parent_id="root"),
            GoalNode(
                id="grandchild", description="Grandchild", status="pending", parent_id="child1"
            ),
        ]

        manager = JobManager(ce=mock_context_engine)
        descendants = manager._collect_descendant_ids("root", goals)

        assert "child1" in descendants
        assert "child2" in descendants
        assert "grandchild" in descendants
        assert "root" not in descendants  # Root excluded

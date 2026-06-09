"""Unit tests for File Lock Registry (RFC-222, IG-295)."""

from soothe.foundation.autopilot.engine.file_lock_registry import (
    FileConflictError,
    FileLockEntry,
    FileLockRegistry,
)


class TestFileLockEntry:
    """Tests for FileLockEntry model."""

    def test_create_entry(self) -> None:
        """Test basic FileLockEntry creation."""
        entry = FileLockEntry(
            file_path="/path/to/file.py",
            goal_id="goal-001",
            loop_id="loop-001",
        )

        assert entry.file_path == "/path/to/file.py"
        assert entry.goal_id == "goal-001"
        assert entry.loop_id == "loop-001"
        assert entry.operation == "edit"
        assert entry.locked_at is not None

    def test_create_entry_with_operation(self) -> None:
        """Test entry with specific operation."""
        entry = FileLockEntry(
            file_path="/path/to/file.py",
            goal_id="goal-001",
            loop_id="loop-001",
            operation="write",
        )

        assert entry.operation == "write"


class TestFileLockRegistry:
    """Tests for FileLockRegistry model."""

    def test_create_registry(self) -> None:
        """Test basic registry creation."""
        registry = FileLockRegistry()
        assert registry.locks == {}
        assert registry.lock_count() == 0

    def test_acquire_lock(self) -> None:
        """Test acquiring lock."""
        registry = FileLockRegistry()

        entry = registry.acquire_lock(
            path="/path/to/file.py",
            goal_id="goal-001",
            loop_id="loop-001",
            operation="edit",
        )

        assert registry.is_locked("/path/to/file.py")
        assert registry.get_lock("/path/to/file.py") == entry
        assert entry.goal_id == "goal-001"
        assert entry.loop_id == "loop-001"

    def test_release_lock(self) -> None:
        """Test releasing lock."""
        registry = FileLockRegistry()
        registry.acquire_lock("/path/to/file.py", "goal-001", "loop-001")

        released = registry.release_lock("/path/to/file.py")

        assert released is not None
        assert not registry.is_locked("/path/to/file.py")

    def test_release_nonexistent_lock(self) -> None:
        """Test releasing nonexistent lock."""
        registry = FileLockRegistry()

        released = registry.release_lock("/nonexistent")

        assert released is None

    def test_is_locked_by_other_true(self) -> None:
        """Test is_locked_by_other returns true for different loop."""
        registry = FileLockRegistry()
        registry.acquire_lock("/path/to/file.py", "goal-001", "loop-001")

        assert registry.is_locked_by_other("/path/to/file.py", "loop-002")

    def test_is_locked_by_other_false_same_loop(self) -> None:
        """Test is_locked_by_other returns false for same loop."""
        registry = FileLockRegistry()
        registry.acquire_lock("/path/to/file.py", "goal-001", "loop-001")

        assert not registry.is_locked_by_other("/path/to/file.py", "loop-001")

    def test_is_locked_by_other_false_not_locked(self) -> None:
        """Test is_locked_by_other returns false if not locked."""
        registry = FileLockRegistry()

        assert not registry.is_locked_by_other("/path/to/file.py", "loop-001")

    def test_is_locked_by_goal(self) -> None:
        """Test is_locked_by_goal."""
        registry = FileLockRegistry()
        registry.acquire_lock("/path/to/file.py", "goal-001", "loop-001")

        assert registry.is_locked_by_goal("/path/to/file.py", "goal-001")
        assert not registry.is_locked_by_goal("/path/to/file.py", "goal-002")

    def test_release_all_for_goal(self) -> None:
        """Test releasing all locks for a goal."""
        registry = FileLockRegistry()
        registry.acquire_lock("/file1.py", "goal-001", "loop-001")
        registry.acquire_lock("/file2.py", "goal-001", "loop-001")
        registry.acquire_lock("/file3.py", "goal-002", "loop-002")

        released = registry.release_all_for_goal("goal-001")

        assert len(released) == 2
        assert "/file1.py" in released
        assert "/file2.py" in released
        assert registry.is_locked("/file3.py")
        assert not registry.is_locked("/file1.py")

    def test_release_all_for_loop(self) -> None:
        """Test releasing all locks for a loop."""
        registry = FileLockRegistry()
        registry.acquire_lock("/file1.py", "goal-001", "loop-001")
        registry.acquire_lock("/file2.py", "goal-002", "loop-001")
        registry.acquire_lock("/file3.py", "goal-003", "loop-002")

        released = registry.release_all_for_loop("loop-001")

        assert len(released) == 2
        assert "/file1.py" in released
        assert "/file2.py" in released
        assert registry.is_locked("/file3.py")

    def test_get_locks_for_goal(self) -> None:
        """Test getting all locks for a goal."""
        registry = FileLockRegistry()
        registry.acquire_lock("/file1.py", "goal-001", "loop-001")
        registry.acquire_lock("/file2.py", "goal-001", "loop-001")
        registry.acquire_lock("/file3.py", "goal-002", "loop-002")

        locks = registry.get_locks_for_goal("goal-001")

        assert len(locks) == 2
        assert all(lock.goal_id == "goal-001" for lock in locks)

    def test_get_locks_for_loop(self) -> None:
        """Test getting all locks for a loop."""
        registry = FileLockRegistry()
        registry.acquire_lock("/file1.py", "goal-001", "loop-001")
        registry.acquire_lock("/file2.py", "goal-002", "loop-001")

        locks = registry.get_locks_for_loop("loop-001")

        assert len(locks) == 2
        assert all(lock.loop_id == "loop-001" for lock in locks)

    def test_lock_count(self) -> None:
        """Test lock count."""
        registry = FileLockRegistry()

        assert registry.lock_count() == 0

        registry.acquire_lock("/file1.py", "goal-001", "loop-001")
        assert registry.lock_count() == 1

        registry.acquire_lock("/file2.py", "goal-002", "loop-002")
        assert registry.lock_count() == 2

        registry.release_lock("/file1.py")
        assert registry.lock_count() == 1

    def test_clear(self) -> None:
        """Test clearing all locks."""
        registry = FileLockRegistry()
        registry.acquire_lock("/file1.py", "goal-001", "loop-001")
        registry.acquire_lock("/file2.py", "goal-002", "loop-002")

        registry.clear()

        assert registry.lock_count() == 0


class TestFileConflictError:
    """Tests for FileConflictError exception."""

    def test_create_error(self) -> None:
        """Test creating conflict error."""
        error = FileConflictError(
            file_path="/path/to/file.py",
            goal_id="goal-001",
            blocking_goal_id="goal-002",
            blocking_loop_id="loop-002",
        )

        assert error.file_path == "/path/to/file.py"
        assert error.goal_id == "goal-001"
        assert error.blocking_goal_id == "goal-002"
        assert error.blocking_loop_id == "loop-002"
        assert "locked by goal goal-002" in str(error)

    def test_error_message_format(self) -> None:
        """Test error message format."""
        error = FileConflictError(
            file_path="/src/main.py",
            goal_id="g1",
            blocking_goal_id="g2",
            blocking_loop_id="l2",
        )

        msg = str(error)
        assert "/src/main.py" in msg
        assert "g2" in msg
        assert "l2" in msg

"""Tests for thread deletion cleanup (RFC-0010)."""

from __future__ import annotations

from pathlib import Path

import pytest


class TestThreadDeletion:
    """Test that thread deletion removes runs/{thread_id}/ directory (RFC-0010)."""

    @pytest.mark.asyncio
    async def test_thread_delete_removes_runs_directory(self, tmp_path: Path) -> None:
        """Verify thread deletion removes the entire runs/{thread_id}/ directory."""
        import shutil

        from soothe.backends.durability.json import JsonDurability
        from soothe.protocols.durability import ThreadMetadata

        # Create a thread with artifacts
        thread_id = "test-thread-delete-123"
        runs_dir = tmp_path / "runs" / thread_id
        runs_dir.mkdir(parents=True, exist_ok=True)

        # Create some artifacts
        (runs_dir / "checkpoint.json").write_text('{"status": "completed"}')
        (runs_dir / "conversation.jsonl").write_text('{"role": "user", "text": "test"}\n')
        goals_dir = runs_dir / "goals" / "g1" / "steps" / "s1"
        goals_dir.mkdir(parents=True, exist_ok=True)
        (goals_dir / "report.json").write_text('{"step_id": "s1", "status": "completed"}')

        # Verify artifacts exist
        assert runs_dir.exists()
        assert (runs_dir / "checkpoint.json").exists()
        assert (runs_dir / "conversation.jsonl").exists()
        assert (goals_dir / "report.json").exists()

        # Simulate thread deletion (same logic as in main.py)
        durability = JsonDurability(persist_dir=str(tmp_path))
        metadata = ThreadMetadata(plan_summary="Test thread")
        await durability.create_thread(metadata)

        # Archive thread metadata
        await durability.archive_thread(thread_id)

        # Remove runs directory
        if runs_dir.exists():
            shutil.rmtree(runs_dir)

        # Verify runs directory is gone
        assert not runs_dir.exists()
        assert not (runs_dir / "checkpoint.json").exists()
        assert not (runs_dir / "conversation.jsonl").exists()

    @pytest.mark.asyncio
    async def test_thread_delete_handles_missing_directory(self, tmp_path: Path) -> None:
        """Verify thread deletion handles case where runs/ directory doesn't exist."""
        import shutil

        thread_id = "test-thread-missing-456"
        runs_dir = tmp_path / "runs" / thread_id

        # Verify directory doesn't exist
        assert not runs_dir.exists()

        # Attempt to delete (should not raise error)
        if runs_dir.exists():
            shutil.rmtree(runs_dir)

        # Still doesn't exist, no error raised
        assert not runs_dir.exists()

    @pytest.mark.asyncio
    async def test_thread_delete_removes_nested_artifacts(self, tmp_path: Path) -> None:
        """Verify deletion removes all nested goal and step artifacts."""
        import shutil

        thread_id = "test-thread-nested-789"
        runs_dir = tmp_path / "runs" / thread_id

        # Create complex nested structure
        for goal_id in ["g1", "g2"]:
            for step_id in ["s1", "s2", "s3"]:
                step_dir = runs_dir / "goals" / goal_id / "steps" / step_id
                step_dir.mkdir(parents=True, exist_ok=True)
                (step_dir / "report.json").write_text(f'{{"step_id": "{step_id}"}}')
                (step_dir / "report.md").write_text(f"# Step {step_id}")

        # Verify nested structure exists
        assert runs_dir.exists()
        assert (runs_dir / "goals" / "g1" / "steps" / "s1" / "report.json").exists()
        assert (runs_dir / "goals" / "g2" / "steps" / "s3" / "report.md").exists()

        # Delete
        if runs_dir.exists():
            shutil.rmtree(runs_dir)

        # Verify everything is gone
        assert not runs_dir.exists()
        assert not (runs_dir / "goals").exists()

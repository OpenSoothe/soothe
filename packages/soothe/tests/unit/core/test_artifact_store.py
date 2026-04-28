"""Tests for RunArtifactStore, RunManifest, and ArtifactEntry (RFC-0010)."""

from __future__ import annotations

import json
from pathlib import Path

from soothe.core.persistence import ArtifactEntry, RunArtifactStore, RunManifest
from soothe.protocols.planner import GoalReport, StepReport


class TestArtifactEntry:
    """Tests for ArtifactEntry model."""

    def test_produced_entry(self) -> None:
        entry = ArtifactEntry(
            path="artifacts/data.csv",
            source="produced",
            size_bytes=1024,
        )
        assert entry.source == "produced"
        assert entry.original_path == ""

    def test_reference_entry(self) -> None:
        entry = ArtifactEntry(
            path="artifacts/ref.txt",
            source="reference",
            original_path="/workspace/src/main.py",
            tool_name="edit_file",
        )
        assert entry.source == "reference"
        assert entry.original_path == "/workspace/src/main.py"


class TestRunManifest:
    """Tests for RunManifest model."""

    def test_defaults(self) -> None:
        m = RunManifest(
            thread_id="t1",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        assert m.version == 1
        assert m.status == "in_progress"
        assert m.artifacts == []

    def test_serialization_roundtrip(self) -> None:
        m = RunManifest(
            thread_id="t1",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
            query="test query",
            mode="autonomous",
        )
        data = m.model_dump_json()
        restored = RunManifest.model_validate_json(data)
        assert restored.thread_id == "t1"


class TestRunArtifactStore:
    """Tests for RunArtifactStore."""

    def test_creates_run_directory(self, tmp_path: Path) -> None:
        store = RunArtifactStore("thread-1", soothe_home=str(tmp_path))
        assert store.run_dir.exists()
        assert store.run_dir == tmp_path / "data" / "threads" / "thread-1"

    def test_conversation_log_path(self, tmp_path: Path) -> None:
        store = RunArtifactStore("thread-1", soothe_home=str(tmp_path))
        assert (
            store.conversation_log_path
            == tmp_path / "data" / "threads" / "thread-1" / "conversation.jsonl"
        )

    def test_record_artifact(self, tmp_path: Path) -> None:
        store = RunArtifactStore("t1", soothe_home=str(tmp_path))
        entry = ArtifactEntry(
            path="artifacts/output.csv",
            source="produced",
            size_bytes=256,
        )
        store.record_artifact(entry)
        assert len(store.manifest.artifacts) == 1
        assert store.manifest.artifacts[0].path == entry.path

    def test_save_and_load_checkpoint(self, tmp_path: Path) -> None:
        store = RunArtifactStore("t1", soothe_home=str(tmp_path))
        envelope = {
            "version": 1,
            "timestamp": "2026-01-01T00:00:00",
            "mode": "single_pass",
            "last_query": "test query",
            "thread_id": "t1",
            "plan": {"goal": "test", "steps": []},
            "completed_step_ids": ["s1", "s2"],
            "total_iterations": 0,
            "status": "in_progress",
        }
        store.save_checkpoint(envelope)

        loaded = store.load_checkpoint()
        assert loaded is not None
        assert loaded["version"] == 1
        assert loaded["last_query"] == "test query"
        assert loaded["completed_step_ids"] == ["s1", "s2"]
        assert loaded["status"] == "in_progress"

    def test_load_checkpoint_missing(self, tmp_path: Path) -> None:
        store = RunArtifactStore("t1", soothe_home=str(tmp_path))
        assert store.load_checkpoint() is None

    def test_save_and_load_manifest(self, tmp_path: Path) -> None:
        store = RunArtifactStore("t1", soothe_home=str(tmp_path))
        store._manifest.query = "my query"
        store._manifest.mode = "autonomous"
        store.save_manifest()

        loaded = store.load_manifest()
        assert loaded is not None
        assert loaded.query == "my query"
        assert loaded.mode == "autonomous"

    def test_manifest_survives_restart(self, tmp_path: Path) -> None:
        store1 = RunArtifactStore("t1", soothe_home=str(tmp_path))
        store1._manifest.query = "original query"
        store1.save_manifest()

        store2 = RunArtifactStore("t1", soothe_home=str(tmp_path))
        assert store2.manifest.query == "original query"

    def test_update_status(self, tmp_path: Path) -> None:
        store = RunArtifactStore("t1", soothe_home=str(tmp_path))
        assert store.manifest.status == "in_progress"
        store.update_status("completed")
        assert store.manifest.status == "completed"

        restored = store.load_manifest()
        assert restored is not None
        assert restored.status == "completed"

    def test_checkpoint_atomic_write(self, tmp_path: Path) -> None:
        """Verify no .tmp file is left after successful checkpoint."""
        store = RunArtifactStore("t1", soothe_home=str(tmp_path))
        store.save_checkpoint({"version": 1, "status": "in_progress"})
        assert not (store.run_dir / "checkpoint.json.tmp").exists()
        assert (store.run_dir / "checkpoint.json").exists()


class TestModelFieldsRFC0010:
    """Test new model fields added in RFC-0010."""

    def test_step_report_depends_on(self) -> None:
        r = StepReport(
            step_id="s2",
            description="Process",
            status="completed",
            depends_on=["s1"],
        )
        assert r.depends_on == ["s1"]
        data = json.loads(r.model_dump_json())
        assert data["depends_on"] == ["s1"]

    def test_step_report_depends_on_default(self) -> None:
        r = StepReport(step_id="s1", description="First", status="completed")
        assert r.depends_on == []

    def test_goal_report_new_fields(self) -> None:
        r = GoalReport(
            goal_id="g1",
            description="Research",
            reflection_assessment="Thorough research",
            cross_validation_notes="Sources agree",
        )
        assert r.reflection_assessment == "Thorough research"
        assert r.cross_validation_notes == "Sources agree"

    def test_goal_report_new_fields_default(self) -> None:
        r = GoalReport(goal_id="g1", description="Test")
        assert r.reflection_assessment == ""
        assert r.cross_validation_notes == ""

    def test_reflection_enhanced_fields(self) -> None:
        from soothe.protocols.planner import Reflection

        r = Reflection(
            assessment="1/3 steps completed",
            should_revise=True,
            feedback="Step s2 failed",
            blocked_steps=["s3"],
            failed_details={"s2": "timeout error"},
        )
        assert r.blocked_steps == ["s3"]
        assert r.failed_details == {"s2": "timeout error"}

    def test_reflection_defaults(self) -> None:
        from soothe.protocols.planner import Reflection

        r = Reflection(assessment="ok", should_revise=False, feedback="")
        assert r.blocked_steps == []
        assert r.failed_details == {}

    def test_checkpoint_envelope(self) -> None:
        from soothe.protocols.planner import CheckpointEnvelope

        e = CheckpointEnvelope(
            thread_id="t1",
            mode="autonomous",
            last_query="test",
            goals=[{"id": "g1", "status": "completed"}],
            completed_step_ids=["s1", "s2"],
            status="in_progress",
        )
        assert e.version == 1
        assert e.mode == "autonomous"
        assert len(e.goals) == 1

        data = json.loads(e.model_dump_json())
        restored = CheckpointEnvelope.model_validate(data)
        assert restored.thread_id == "t1"
        assert restored.completed_step_ids == ["s1", "s2"]

"""Tests for RunArtifactStore, RunManifest, and ArtifactEntry (RFC-0010)."""

from __future__ import annotations

import json
from pathlib import Path

from soothe.core.artifact_store import ArtifactEntry, RunArtifactStore, RunManifest
from soothe.protocols.planner import GoalReport, StepReport


class TestArtifactEntry:
    """Tests for ArtifactEntry model."""

    def test_produced_entry(self) -> None:
        entry = ArtifactEntry(
            path="goals/g1/steps/s1/artifacts/data.csv",
            source="produced",
            step_id="s1",
            goal_id="g1",
            size_bytes=1024,
        )
        assert entry.source == "produced"
        assert entry.original_path == ""

    def test_reference_entry(self) -> None:
        entry = ArtifactEntry(
            path="goals/g1/steps/s1/artifacts/ref.txt",
            source="reference",
            original_path="/workspace/src/main.py",
            tool_name="edit_file",
            step_id="s1",
            goal_id="g1",
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
        assert m.goals == []
        assert m.artifacts == []

    def test_serialization_roundtrip(self) -> None:
        m = RunManifest(
            thread_id="t1",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
            query="test query",
            mode="autonomous",
            goals=["g1", "g2"],
        )
        data = m.model_dump_json()
        restored = RunManifest.model_validate_json(data)
        assert restored.thread_id == "t1"
        assert restored.goals == ["g1", "g2"]


class TestRunArtifactStore:
    """Tests for RunArtifactStore."""

    def test_creates_run_directory(self, tmp_path: Path) -> None:
        store = RunArtifactStore("thread-1", soothe_home=str(tmp_path))
        assert store.run_dir.exists()
        assert store.run_dir == tmp_path / "runs" / "thread-1"

    def test_conversation_log_path(self, tmp_path: Path) -> None:
        store = RunArtifactStore("thread-1", soothe_home=str(tmp_path))
        assert store.conversation_log_path == tmp_path / "runs" / "thread-1" / "conversation.jsonl"

    def test_ensure_step_dir(self, tmp_path: Path) -> None:
        store = RunArtifactStore("t1", soothe_home=str(tmp_path))
        d = store.ensure_step_dir("goal-a", "step-1")
        assert d.exists()
        assert d == tmp_path / "runs" / "t1" / "goals" / "goal-a" / "steps" / "step-1"

    def test_write_step_report(self, tmp_path: Path) -> None:
        store = RunArtifactStore("t1", soothe_home=str(tmp_path))
        store.write_step_report(
            goal_id="g1",
            step_id="s1",
            description="Analyze data",
            status="completed",
            result="Found 42 records",
            duration_ms=150,
            depends_on=["s0"],
        )
        step_dir = store.run_dir / "goals" / "g1" / "steps" / "s1"
        assert (step_dir / "report.json").exists()
        assert (step_dir / "report.md").exists()

        report = StepReport.model_validate_json((step_dir / "report.json").read_text())
        assert report.step_id == "s1"
        assert report.status == "completed"
        assert report.result == "Found 42 records"
        assert report.depends_on == ["s0"]
        assert report.duration_ms == 150

        md = (step_dir / "report.md").read_text()
        assert "Analyze data" in md
        assert "s0" in md

    def test_write_goal_report(self, tmp_path: Path) -> None:
        store = RunArtifactStore("t1", soothe_home=str(tmp_path))
        report = GoalReport(
            goal_id="g1",
            description="Research topic",
            summary="Found interesting results",
            status="completed",
            duration_ms=5000,
            reflection_assessment="Good progress",
            cross_validation_notes="No contradictions",
            step_reports=[
                StepReport(
                    step_id="s1",
                    description="Search",
                    status="completed",
                    result="Found papers",
                ),
            ],
        )
        store.write_goal_report(report)

        goal_dir = store.run_dir / "goals" / "g1"
        assert (goal_dir / "report.json").exists()
        assert (goal_dir / "report.md").exists()

        restored = GoalReport.model_validate_json((goal_dir / "report.json").read_text())
        assert restored.goal_id == "g1"
        assert restored.reflection_assessment == "Good progress"
        assert restored.cross_validation_notes == "No contradictions"

        md = (goal_dir / "report.md").read_text()
        assert "Research topic" in md
        assert "Good progress" in md
        assert "No contradictions" in md

        assert "g1" in store.manifest.goals

    def test_record_artifact(self, tmp_path: Path) -> None:
        store = RunArtifactStore("t1", soothe_home=str(tmp_path))
        entry = ArtifactEntry(
            path="goals/g1/steps/s1/artifacts/output.csv",
            source="produced",
            step_id="s1",
            goal_id="g1",
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
            "goals": [],
            "active_goal_id": None,
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
        store._manifest.goals = ["g1", "g2"]
        store.save_manifest()

        loaded = store.load_manifest()
        assert loaded is not None
        assert loaded.query == "my query"
        assert loaded.mode == "autonomous"
        assert loaded.goals == ["g1", "g2"]

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


class TestCheckpointRecovery:
    """Test checkpoint round-trip for recovery scenarios."""

    def test_step_level_recovery(self, tmp_path: Path) -> None:
        """Simulate crash after 2 of 4 steps, then restore."""
        store = RunArtifactStore("t1", soothe_home=str(tmp_path))

        store.write_step_report("g1", "s1", "Step 1", "completed", "result 1", 100)
        store.write_step_report("g1", "s2", "Step 2", "completed", "result 2", 200)

        envelope = {
            "version": 1,
            "mode": "single_pass",
            "last_query": "do something",
            "thread_id": "t1",
            "goals": [],
            "plan": {
                "goal": "do something",
                "steps": [
                    {"id": "s1", "description": "Step 1", "status": "completed"},
                    {"id": "s2", "description": "Step 2", "status": "completed"},
                    {"id": "s3", "description": "Step 3", "status": "pending"},
                    {"id": "s4", "description": "Step 4", "status": "pending"},
                ],
            },
            "completed_step_ids": ["s1", "s2"],
            "status": "in_progress",
        }
        store.save_checkpoint(envelope)

        # "Restart" -- new store instance
        store2 = RunArtifactStore("t1", soothe_home=str(tmp_path))
        loaded = store2.load_checkpoint()
        assert loaded is not None
        assert loaded["status"] == "in_progress"
        assert set(loaded["completed_step_ids"]) == {"s1", "s2"}
        assert len(loaded["plan"]["steps"]) == 4

    def test_goal_level_recovery(self, tmp_path: Path) -> None:
        """Simulate crash mid-goal-DAG, then restore."""
        store = RunArtifactStore("t1", soothe_home=str(tmp_path))

        goal_report = GoalReport(
            goal_id="gA",
            description="First goal",
            summary="Completed analysis",
            status="completed",
            duration_ms=3000,
        )
        store.write_goal_report(goal_report)

        goals_snapshot = [
            {"id": "gA", "description": "First goal", "status": "completed"},
            {"id": "gB", "description": "Second goal", "status": "in_progress", "depends_on": []},
            {"id": "gC", "description": "Third goal", "status": "pending", "depends_on": ["gA", "gB"]},
        ]

        envelope = {
            "version": 1,
            "mode": "autonomous",
            "last_query": "research and summarize",
            "thread_id": "t1",
            "goals": goals_snapshot,
            "active_goal_id": "gB",
            "plan": {"goal": "Second goal", "steps": [{"id": "s1", "description": "Search", "status": "completed"}]},
            "completed_step_ids": ["s1"],
            "status": "in_progress",
        }
        store.save_checkpoint(envelope)

        store2 = RunArtifactStore("t1", soothe_home=str(tmp_path))
        loaded = store2.load_checkpoint()
        assert loaded is not None
        assert loaded["active_goal_id"] == "gB"
        assert len(loaded["goals"]) == 3
        completed_goals = [g for g in loaded["goals"] if g["status"] == "completed"]
        assert len(completed_goals) == 1
        assert completed_goals[0]["id"] == "gA"


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

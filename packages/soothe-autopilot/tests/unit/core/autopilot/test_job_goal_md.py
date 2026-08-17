"""Tests for job-scoped GOAL.md artifact (IG-702 / IG-742)."""

from __future__ import annotations

from pathlib import Path

import pytest
from soothe.config.models import AutopilotConfig
from soothe.context import ContextEngine
from soothe.events.internal_bus import InternalEventBus

from soothe_autopilot import AutopilotService
from soothe_autopilot.intake import (
    GOAL_MD_FILENAME,
    load_job_goal_md,
    resolve_job_goal_md_path,
    write_job_goal_md,
)
from soothe_autopilot.verify.job_maturity import acceptance_contract_brief

from .fakes import IdleFakeFactory


def _service(*, jobs_root: Path | None = None) -> AutopilotService:
    bus = InternalEventBus()
    ce = ContextEngine()
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=2, max_parallel_goals=2),
        internal_bus=bus,
        runner_factory=IdleFakeFactory(),
    )
    if jobs_root is not None:
        svc._jobs_root = jobs_root
    return svc


class TestJobGoalMdHelpers:
    def test_write_and_load(self, tmp_path: Path) -> None:
        path = write_job_goal_md(
            jobs_root=tmp_path,
            job_id="job-abc",
            description="# Build auth\n\nShip OAuth.",
        )
        assert path is not None
        assert path.name == GOAL_MD_FILENAME
        assert path.read_text(encoding="utf-8") == "# Build auth\n\nShip OAuth."
        assert load_job_goal_md(jobs_root=tmp_path, job_id="job-abc") == (
            "# Build auth\n\nShip OAuth."
        )

    def test_reject_path_traversal(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="invalid path"):
            resolve_job_goal_md_path(jobs_root=tmp_path, job_id="../escape")
        assert (
            write_job_goal_md(
                jobs_root=tmp_path,
                job_id="../escape",
                description="nope",
            )
            is None
        )

    def test_none_jobs_root(self) -> None:
        assert write_job_goal_md(jobs_root=None, job_id="x", description="y") is None
        assert load_job_goal_md(jobs_root=None, job_id="x") == ""


class TestSubmitWritesGoalMd:
    @pytest.mark.asyncio
    async def test_root_submit_writes_goal_md(self, tmp_path: Path) -> None:
        jobs = tmp_path / "jobs"
        jobs.mkdir()
        svc = _service(jobs_root=jobs)
        goal = await svc.submit_task("Implement feature X")
        path = jobs / goal.id / "GOAL.md"
        assert path.is_file()
        assert path.read_text(encoding="utf-8") == "Implement feature X"

    @pytest.mark.asyncio
    async def test_child_submit_does_not_write_child_goal_md(self, tmp_path: Path) -> None:
        jobs = tmp_path / "jobs"
        jobs.mkdir()
        svc = _service(jobs_root=jobs)
        root = await svc.submit_task("root job")
        child = await svc.submit_task("child task", parent_id=root.id)
        assert (jobs / root.id / "GOAL.md").is_file()
        assert not (jobs / child.id / "GOAL.md").exists()


class TestJobArtifactOnly:
    def test_workspace_goal_md_ignored(self, tmp_path: Path) -> None:
        """Acceptance brief uses job artifact only, not workspace GOAL.md (IG-742)."""
        ws = tmp_path / "ws"
        jobs = tmp_path / "jobs"
        ws.mkdir()
        (ws / "GOAL.md").write_text("workspace contract", encoding="utf-8")
        write_job_goal_md(
            jobs_root=jobs,
            job_id="j1",
            description="job artifact contract",
        )
        brief = acceptance_contract_brief(jobs_root=jobs, job_id="j1")
        assert "job artifact contract" in brief
        assert "workspace contract" not in brief

    def test_acceptance_brief_includes_job_goal_md(self, tmp_path: Path) -> None:
        jobs = tmp_path / "jobs"
        write_job_goal_md(
            jobs_root=jobs,
            job_id="j1",
            description="Task: return N",
        )
        brief = acceptance_contract_brief(jobs_root=jobs, job_id="j1")
        assert "GOAL.md" in brief
        assert "return N" in brief

    def test_empty_without_job_artifact(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "GOAL.md").write_text("orphan workspace contract", encoding="utf-8")
        brief = acceptance_contract_brief(jobs_root=tmp_path / "jobs", job_id="missing")
        assert "orphan workspace contract" not in brief
        assert "acceptance contract" in brief.lower()

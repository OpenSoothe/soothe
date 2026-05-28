"""Tests for AutopilotService._process_inbox channel consumer (RFC-222)."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe.config.models import AutonomousConfig
from soothe.core.autopilot import AutopilotService
from soothe.core.events.internal_bus import InternalEventBus
from soothe.core.goal_engine import GoalEngine


def _service(*, inbox_dir: str = "") -> AutopilotService:
    bus = InternalEventBus()
    ge = GoalEngine(internal_bus=bus)
    cfg = AutonomousConfig(max_loops=1, max_parallel_goals=1)
    cfg.inbox_dir = inbox_dir
    return AutopilotService(goal_engine=ge, config=cfg, internal_bus=bus)


class TestProcessInbox:
    @pytest.mark.asyncio
    async def test_no_inbox_dir_short_circuits(self) -> None:
        svc = _service(inbox_dir="")
        await svc._process_inbox()  # no exception, no goals
        goals = await svc.list_goals()
        assert goals == []

    @pytest.mark.asyncio
    async def test_creates_goal_from_task_submit_file(self, tmp_path: Path) -> None:
        svc = _service(inbox_dir=str(tmp_path))

        # Drop a task_submit message file.
        (tmp_path / "01-task.md").write_text(
            "---\ntype: task_submit\npriority: 75\n---\n\nWrite a sonnet."
        )

        await svc._process_inbox()

        goals = await svc.list_goals()
        assert len(goals) == 1
        assert goals[0].priority == 75
        assert "sonnet" in goals[0].description.lower()

    @pytest.mark.asyncio
    async def test_no_frontmatter_uses_defaults(self, tmp_path: Path) -> None:
        svc = _service(inbox_dir=str(tmp_path))
        (tmp_path / "01-bare.md").write_text("Run a quick check.")

        await svc._process_inbox()

        goals = await svc.list_goals()
        assert len(goals) == 1
        assert goals[0].priority == 50  # default

    @pytest.mark.asyncio
    async def test_archives_processed_files(self, tmp_path: Path) -> None:
        svc = _service(inbox_dir=str(tmp_path))
        (tmp_path / "01-task.md").write_text("Hello world")

        await svc._process_inbox()

        # File moved into ./processed/
        assert not (tmp_path / "01-task.md").exists()
        assert (tmp_path / "processed" / "01-task.md").exists()

    @pytest.mark.asyncio
    async def test_skips_non_task_submit_messages(self, tmp_path: Path) -> None:
        svc = _service(inbox_dir=str(tmp_path))
        (tmp_path / "01-signal.md").write_text("---\ntype: signal_resume\n---\n\nresume now")

        await svc._process_inbox()

        goals = await svc.list_goals()
        assert goals == []

    @pytest.mark.asyncio
    async def test_skips_empty_description(self, tmp_path: Path) -> None:
        svc = _service(inbox_dir=str(tmp_path))
        (tmp_path / "01-empty.md").write_text("---\ntype: task_submit\n---\n\n   ")

        await svc._process_inbox()

        goals = await svc.list_goals()
        assert goals == []

    @pytest.mark.asyncio
    async def test_inbox_lazily_initialized_once(self, tmp_path: Path) -> None:
        svc = _service(inbox_dir=str(tmp_path))
        first = svc._get_or_init_inbox()
        second = svc._get_or_init_inbox()
        assert first is second

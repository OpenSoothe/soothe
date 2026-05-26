"""Tests for SkillWorkspaceSyncMiddleware."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from soothe.config import SootheConfig
from soothe.middleware.skill_workspace_sync import SkillWorkspaceSyncMiddleware
from soothe.skills.workspace_sync import workspace_skills_mirror_root


@pytest.mark.asyncio
async def test_middleware_syncs_in_virtual_mode(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    host = tmp_path / "host"
    host.mkdir()
    (host / "my-skill").mkdir()
    (host / "my-skill" / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: D\n---\n# Hi\n",
        encoding="utf-8",
    )

    cfg = SootheConfig()
    cfg.security.allow_paths_outside_workspace = False
    cfg.skills = [str(host / "my-skill")]

    middleware = SkillWorkspaceSyncMiddleware(config=cfg)
    lg_config = {"configurable": {"workspace": str(ws)}}
    with patch("langgraph.config.get_config", return_value=lg_config):
        result = await middleware.abefore_agent({}, MagicMock())

    assert result is None
    assert (workspace_skills_mirror_root(ws) / "my-skill" / "SKILL.md").is_file()


@pytest.mark.asyncio
async def test_middleware_noop_when_paths_outside_allowed(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    host = tmp_path / "host"
    host.mkdir()
    (host / "s").mkdir()
    (host / "s" / "SKILL.md").write_text("---\nname: s\ndescription: d\n---\n", encoding="utf-8")

    cfg = SootheConfig()
    cfg.security.allow_paths_outside_workspace = True
    cfg.skills = [str(host / "s")]

    middleware = SkillWorkspaceSyncMiddleware(config=cfg)
    with patch(
        "langgraph.config.get_config", return_value={"configurable": {"workspace": str(ws)}}
    ):
        await middleware.abefore_agent({}, MagicMock())

    assert not workspace_skills_mirror_root(ws).exists()

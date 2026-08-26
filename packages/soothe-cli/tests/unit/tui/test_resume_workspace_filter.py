"""Workspace scoping for the TUI /resume loop picker."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.loops.sessions import (
    list_loops_via_daemon_rpc,
    loop_matches_workspace,
    normalize_workspace_path,
)
from soothe_cli.runtime.transport.session import TuiDaemonSession
from soothe_cli.tui.widgets.loop_selector import LoopSelectorScreen


def test_loop_matches_workspace_resolves_equivalent_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    loop = {"loop_id": "a", "client_workspace": str(workspace / ".")}
    assert loop_matches_workspace(loop, str(workspace)) is True
    assert loop_matches_workspace(loop, str(tmp_path / "other")) is False


def test_loop_matches_workspace_rejects_missing_workspace() -> None:
    assert loop_matches_workspace({"loop_id": "a"}, "/ws") is False


def test_normalize_workspace_path_empty() -> None:
    assert normalize_workspace_path(None) is None
    assert normalize_workspace_path("  ") is None


def test_resume_selector_filters_initial_loops_to_current_workspace(tmp_path: Path) -> None:
    here = tmp_path / "here"
    other = tmp_path / "other"
    here.mkdir()
    other.mkdir()
    loops = [
        {
            "loop_id": "here-loop",
            "client_workspace": str(here),
            "updated": "2026-08-20T12:00:00+00:00",
        },
        {
            "loop_id": "other-loop",
            "client_workspace": str(other),
            "updated": "2026-08-20T13:00:00+00:00",
        },
    ]
    screen = LoopSelectorScreen(initial_loops=loops, workspace=str(here))
    assert [loop["loop_id"] for loop in screen._loops] == ["here-loop"]
    assert "workspace:" in screen._build_title()
    assert "W show all workspaces" in screen._build_help_text()


def test_resume_selector_w_toggles_to_all_workspaces(tmp_path: Path) -> None:
    here = tmp_path / "here"
    other = tmp_path / "other"
    here.mkdir()
    other.mkdir()
    loops = [
        {
            "loop_id": "here-loop",
            "client_workspace": str(here),
            "updated": "2026-08-20T12:00:00+00:00",
        },
        {
            "loop_id": "other-loop",
            "client_workspace": str(other),
            "updated": "2026-08-20T13:00:00+00:00",
        },
    ]
    screen = LoopSelectorScreen(initial_loops=loops, workspace=str(here))
    screen.action_toggle_workspace_filter()
    assert {loop["loop_id"] for loop in screen._loops} == {"here-loop", "other-loop"}
    assert "all workspaces" in screen._build_title()
    assert "W filter this workspace" in screen._build_help_text()


def test_resume_selector_defaults_to_all_when_workspace_unknown() -> None:
    loops = [
        {
            "loop_id": "a",
            "client_workspace": "/ws-a",
            "updated": "2026-08-20T12:00:00+00:00",
        },
        {
            "loop_id": "b",
            "client_workspace": "/ws-b",
            "updated": "2026-08-20T13:00:00+00:00",
        },
    ]
    screen = LoopSelectorScreen(initial_loops=loops, workspace=None)
    assert {loop["loop_id"] for loop in screen._loops} == {"a", "b"}
    screen.action_toggle_workspace_filter()
    assert {loop["loop_id"] for loop in screen._loops} == {"a", "b"}


@pytest.mark.asyncio
async def test_list_loops_via_daemon_rpc_forwards_workspace(tmp_path: Path) -> None:
    workspace = str(tmp_path)
    daemon = type(
        "DaemonStub",
        (),
        {
            "list_loops": AsyncMock(
                return_value={
                    "loops": [
                        {
                            "loop_id": "loop_a",
                            "status": "idle",
                            "goals": 0,
                            "switches": 0,
                            "created": "2026-06-30T09:00:00+00:00",
                            "client_workspace": workspace,
                        }
                    ]
                }
            )
        },
    )()

    loops = await list_loops_via_daemon_rpc(
        daemon, limit=20, sort_by="updated", workspace=workspace
    )

    daemon.list_loops.assert_awaited_once_with(limit=20, workspace=workspace)
    assert loops[0]["client_workspace"] == workspace


@pytest.mark.asyncio
async def test_tui_daemon_session_list_loops_sends_workspace_filter() -> None:
    session = TuiDaemonSession.__new__(TuiDaemonSession)
    session._rpc_lock = asyncio.Lock()  # noqa: SLF001
    session._ensure_rpc_connected = AsyncMock()  # noqa: SLF001
    session._rpc_client = MagicMock()  # noqa: SLF001
    session._rpc_client.request = AsyncMock(return_value={"loops": []})  # noqa: SLF001

    await session.list_loops(limit=10, workspace="/ws/project")

    session._rpc_client.request.assert_awaited_once_with(  # noqa: SLF001
        "loop_list",
        {"limit": 10, "filter": {"workspace": "/ws/project"}},
        timeout=15.0,
    )

"""Step-card tool stats: register unified main step tools before args arrive."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE

from soothe_cli.runtime.parse.tool_call_resolution import (
    is_execute_step_namespace,
    is_main_step_level_tool_call_id,
    is_step_card_tool_scope,
    is_task_level_subgraph_tool_call_id,
    resolve_tool_result_row_key,
    should_ingest_tool_for_step_stats,
)
from soothe_cli.runtime.state.step_router import StepTaskRouter
from soothe_cli.tui.textual_adapter import TextualUIAdapter, apply_tool_call_wire_update
from soothe_cli.tui.widgets.messages import CognitionStepMessage


def test_is_main_step_level_tool_call_id() -> None:
    assert is_main_step_level_tool_call_id("BCO_01:s:read_file:0")
    assert not is_main_step_level_tool_call_id("BCO_01:s:task:0")
    assert not is_main_step_level_tool_call_id("BCO_01:t0:grep:1")
    assert not is_main_step_level_tool_call_id("grep:0")


def test_is_task_level_subgraph_tool_call_id() -> None:
    assert is_task_level_subgraph_tool_call_id("BCO_01:t0:grep:1")
    assert is_task_level_subgraph_tool_call_id("ZCH_01:t0:read_file:2")
    assert not is_task_level_subgraph_tool_call_id("BCO_01:s:read_file:0")
    assert not is_task_level_subgraph_tool_call_id("BCO_01:s:task:0")


def test_is_step_card_tool_scope() -> None:
    assert is_step_card_tool_scope(ns_key=())
    assert is_step_card_tool_scope(ns_key=("execute:abc",))
    assert is_step_card_tool_scope(ns_key=("execute:abc/1",))
    assert not is_step_card_tool_scope(ns_key=("execute:abc", "tools:xyz"))
    assert not is_step_card_tool_scope(ns_key=("tools:sub",))
    assert is_execute_step_namespace(("execute:abc",))
    assert not is_execute_step_namespace(("execute:abc/1",))
    assert not is_execute_step_namespace(("execute:abc", "tools:xyz"))


def test_resolve_tool_result_row_key_execute_namespace_uses_step_id() -> None:
    tcid = "HHK_01:s:tool-bf00dc631d174c789e85886a7da41417"
    assert (
        resolve_tool_result_row_key(
            ns_key=("execute:3945bafe-5f07-4575-7e74-e93ad55e7b8",),
            tool_call_id=tcid,
        )
        == tcid
    )
    assert (
        resolve_tool_result_row_key(
            ns_key=("execute:3945bafe-5f07-4575-7e74-e93ad55e7b8/1",),
            tool_call_id=tcid,
        )
        == tcid
    )


def test_resolve_tool_result_row_key_subgraph_namespace_remaps() -> None:
    unified = "BCO_01:t0:grep:1"
    remapped = resolve_tool_result_row_key(
        ns_key=("tools:sub",),
        tool_call_id=unified,
    )
    assert remapped == unified
    scoped = resolve_tool_result_row_key(
        ns_key=("tools:sub",),
        tool_call_id="grep:1",
    )
    assert scoped != "grep:1"
    assert "grep:1" in scoped


def test_should_ingest_tool_for_step_stats_without_args() -> None:
    assert should_ingest_tool_for_step_stats(
        is_step_card_scope=True,
        tool_name="read_file",
        tool_call_id="BCO_01:s:read_file:0",
        args_meaningful=False,
    )
    assert should_ingest_tool_for_step_stats(
        is_step_card_scope=True,
        tool_name="grep",
        tool_call_id="grep:0",
        args_meaningful=False,
    )
    assert should_ingest_tool_for_step_stats(
        is_step_card_scope=False,
        tool_name="read_file",
        tool_call_id="BCO_01:t0:read_file:1",
        args_meaningful=False,
    )
    assert not should_ingest_tool_for_step_stats(
        is_step_card_scope=False,
        tool_name="read_file",
        tool_call_id="grep:0",
        args_meaningful=False,
    )
    assert should_ingest_tool_for_step_stats(
        is_step_card_scope=True,
        tool_name="grep",
        tool_call_id="BCO_01:s:grep:0",
        args_meaningful=True,
    )
    assert not should_ingest_tool_for_step_stats(
        is_step_card_scope=True,
        tool_name="task",
        tool_call_id="BCO_01:s:task:0",
        args_meaningful=False,
    )


@pytest.mark.asyncio
async def test_wire_update_registers_main_step_tool_with_empty_args() -> None:
    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    card = CognitionStepMessage("BCO-01", "Read spec", id="stp-wire")
    adapter._current_step_messages["BCO-01"] = card
    router = StepTaskRouter()
    router.on_step_started("BCO-01")

    handled = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "BCO_01:s:read_file:0",
            "name": "read_file",
            "args": {},
        },
        ns_key=(),
        pending_tool_calls_lc={},
    )
    assert handled is True
    assert card.has_tool_call_row("BCO_01:s:read_file:0")
    assert card._stats_title_suffix() == " · 1 tool"


@pytest.mark.asyncio
async def test_wire_update_nested_execute_namespace_registers_step_level_tool() -> None:
    """Sole-child reuse uses execute:{run}/N; step-level ``s:`` tools still show on the card."""
    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    card = CognitionStepMessage("NKX-02", "Identify approach", id="stp-nkx02")
    adapter._current_step_messages["NKX-02"] = card
    router = StepTaskRouter()
    router.on_step_started("NKX-02")

    handled = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "NKX_02:s:tool-ba49b7f1839341778d7c898c4f306ec9",
            "name": "read_file",
            "args": {"path": "pyproject.toml"},
        },
        ns_key=("execute:8a35d5ce-4bf3-1f6e-de19-df51982876b8/1",),
        pending_tool_calls_lc={},
    )
    assert handled is True
    assert card.has_tool_call_row("NKX_02:s:tool-ba49b7f1839341778d7c898c4f306ec9")
    assert card._stats_title_suffix() == " · 1 tool"


@pytest.mark.asyncio
async def test_wire_update_buffers_main_tool_before_step_card() -> None:
    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    router = StepTaskRouter()
    card = CognitionStepMessage("BCO-01", "Read spec", id="stp-wire-buffer")
    tool_to_step: dict[str, object] = {}
    display: dict[str, object] = {}

    handled = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "BCO_01:s:read_file:0",
            "name": "read_file",
            "args": {},
        },
        ns_key=(),
        pending_tool_calls_lc={},
    )
    assert handled is True
    assert not card.has_tool_call_row("BCO_01:s:read_file:0")

    adapter._current_step_messages["BCO-01"] = card
    router.on_step_started("BCO-01")
    routed = router.route_pending_main_tools(
        adapter._current_step_messages,
        tool_to_step,
        display,
    )
    assert routed == 1
    assert card.has_tool_call_row("BCO_01:s:read_file:0")
    assert card._stats_title_suffix() == " · 1 tool"


@pytest.mark.asyncio
async def test_wire_update_fallback_ingests_subgraph_tool_without_task_binding() -> None:
    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    card = CognitionStepMessage("BCO-01", "List workspace", id="stp-wire-subgraph")
    adapter._current_step_messages["BCO-01"] = card
    router = StepTaskRouter()
    router.on_step_started("BCO-01")

    handled = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "BCO_01:t0:ls:0",
            "name": "ls",
            "args": {"path": "."},
        },
        ns_key=("execute:abc",),
        pending_tool_calls_lc={},
    )
    assert handled is True
    assert card.has_tool_call_row("BCO_01:t0:ls:0")


@pytest.mark.asyncio
async def test_wire_update_registers_task_on_execute_namespace() -> None:
    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    card = CognitionStepMessage("ZCH-01", "Survey RFCs", id="stp-wire-task-exec")
    adapter._current_step_messages["ZCH-01"] = card
    router = StepTaskRouter()
    router.on_step_started("ZCH-01")

    handled = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:t0:tool-abc123",
            "name": "task",
            "args": {
                "subagent_type": "deep_research",
                "description": "Survey RFCs 000-105",
            },
        },
        ns_key=("execute:c6612b5c",),
        pending_tool_calls_lc={},
    )
    assert handled is True
    assert card._has_task_activity_body()
    assert card._iter_task_delegation_rows()
    assert router._spawns_by_task_id["ZCH_01:s:task:0"][1] == "deep_research"


@pytest.mark.asyncio
async def test_wire_update_task_call_ids_keep_step_rows_without_subagent_cards() -> None:
    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    card = CognitionStepMessage("XQZ-01", "Analyze architecture", id="stp-wire-task-sync")
    adapter._current_step_messages["XQZ-01"] = card
    router = StepTaskRouter()
    router.on_step_started("XQZ-01")

    first = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "XQZ_01:s:call_aaa111",
            "name": "task",
            "args": {
                "subagent_type": "deep_research",
                "description": "Analyze repo structure",
            },
        },
        ns_key=("execute:abc",),
        pending_tool_calls_lc={},
    )
    second = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "XQZ_01:s:call_bbb222",
            "name": "task",
            "args": {
                "subagent_type": "deep_research",
                "description": "Analyze package boundaries",
            },
        },
        ns_key=("execute:abc",),
        pending_tool_calls_lc={},
    )

    assert first is True
    assert second is True
    assert len(card._iter_task_delegation_rows()) == 2
    # In-step task delegations no longer mount SubAgent cards.


@pytest.mark.asyncio
async def test_wire_update_registers_subgraph_tool_with_placeholder_args() -> None:
    """Subgraph placeholder args must still create a step-card row (tool name only)."""
    from soothe_cli.tui.tool_display import format_step_tool_activity_command

    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    card = CognitionStepMessage("ZCH-01", "Survey RFCs", id="stp-wire-subgraph-ph")
    adapter._current_step_messages["ZCH-01"] = card
    router = StepTaskRouter()
    router.on_step_started("ZCH-01")

    handled = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:t0:read_file:2",
            "name": "read_file",
            "args": {"_subgraph_tool": True},
        },
        ns_key=("execute:abc", "tools:54045a8d"),
        pending_tool_calls_lc={},
    )
    assert handled is True
    assert card.has_tool_call_row("ZCH_01:t0:read_file:2")
    assert format_step_tool_activity_command("read_file", {"_subgraph_tool": True}) == "ReadFile"


@pytest.mark.asyncio
async def test_subgraph_row_hydrates_args_from_late_raw_args_update() -> None:
    """Subgraph tool args hydrate on the parent step card (no SubAgent card)."""
    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    card = CognitionStepMessage("ZCH-01", "Survey RFCs", id="stp-wire-subgraph-late-args")
    adapter._current_step_messages["ZCH-01"] = card
    router = StepTaskRouter()
    router.on_step_started("ZCH-01")

    handled_task = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:s:task:0",
            "name": "task",
            "args": {
                "subagent_type": "deep_research",
                "description": "Enumerate all files",
            },
        },
        ns_key=("execute:abc",),
        pending_tool_calls_lc={},
    )
    assert handled_task is True

    handled_placeholder = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:t0:list_files:0",
            "name": "list_files",
            "args": {"_subgraph_tool": True},
        },
        ns_key=("execute:abc", "tools:late-args"),
        pending_tool_calls_lc={},
    )
    assert handled_placeholder is True

    handled_hydrate = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:t0:list_files:0",
            "name": "list_files",
            "args": '{"path":"/Users/xiamingchen/Workspace/mirasurf/soothe"}',
        },
        ns_key=("execute:abc", "tools:late-args"),
        pending_tool_calls_lc={},
    )
    assert handled_hydrate is True

    assert card.has_tool_call_row("ZCH_01:t0:list_files:0")
    row = card._row_index["ZCH_01:t0:list_files:0"]
    assert "mirasurf/soothe" in str(row.args.get("path") or "")
    card._status = "running"
    text = str(card._step_task_activity_content())
    assert "Deep Research(Enumerate all files) · 1 tool" in text


@pytest.mark.asyncio
async def test_subgraph_wire_string_args_count_on_running_task_line() -> None:
    """Wire updates with string args count toward the running task-line tool total."""
    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    card = CognitionStepMessage("ZCH-01", "Survey RFCs", id="stp-wire-subgraph-string-args")
    adapter._current_step_messages["ZCH-01"] = card
    router = StepTaskRouter()
    router.on_step_started("ZCH-01")

    handled_task = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:s:task:0",
            "name": "task",
            "args": {
                "subagent_type": "deep_research",
                "description": "Enumerate all files in workspace",
            },
        },
        ns_key=("execute:abc",),
        pending_tool_calls_lc={},
    )
    assert handled_task is True

    handled_list = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:t0:list_files:0",
            "name": "list_files",
            "args": '{"path":"/Users/xiamingchen/Workspace/mirasurf/soothe"}',
        },
        ns_key=("execute:abc", "tools:string-args"),
        pending_tool_calls_lc={},
    )
    assert handled_list is True

    handled_glob = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:t0:glob:1",
            "name": "glob",
            "args": '{"glob_pattern":"**/*.py"}',
        },
        ns_key=("execute:abc", "tools:string-args"),
        pending_tool_calls_lc={},
    )
    assert handled_glob is True

    assert card.has_tool_call_row("ZCH_01:t0:list_files:0")
    assert card.has_tool_call_row("ZCH_01:t0:glob:1")
    card._status = "running"
    text = str(card._step_task_activity_content())
    assert "Deep Research(Enumerate all files in workspace) · 2 tools" in text
    # Nested subgraph tool lines are not rendered on the step card.
    assert "Glob(" not in text
    assert "ListFiles(" not in text


@pytest.mark.asyncio
async def test_subagent_wire_step_event_counts_on_step_task_line() -> None:
    from soothe_cli.tui.textual_adapter import _apply_subagent_wire_step_event

    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    step = CognitionStepMessage("ZCH-01", "World Cup", id="stp-wire-step")
    adapter._current_step_messages["ZCH-01"] = step
    router = StepTaskRouter()
    router.on_step_started("ZCH-01")
    await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:s:task:0",
            "name": "task",
            "args": {
                "subagent_type": "deep_research",
                "description": "World Cup status",
            },
        },
        ns_key=("execute:abc",),
        pending_tool_calls_lc={},
    )
    scope: tuple[str, str, str] = ("ZCH_01:s:task:0", "deep_research", "ZCH-01")

    handled = _apply_subagent_wire_step_event(
        adapter,
        event_type="soothe.subagent.deep_research.step.completed",
        data={"tool_name": "PlanSearches", "args_preview": "4 queries", "status": "done"},
        task_scope=scope,
    )
    assert handled is True
    step._status = "running"
    step_text = str(step._step_task_activity_content())
    assert "Deep Research(World Cup status) · 1 tool" in step_text
    assert "PlanSearches" not in step_text


@pytest.mark.asyncio
async def test_subagent_wire_completed_syncs_task_row_on_step_card() -> None:
    """Completed wire event syncs the step-card task marker (no SubAgent card)."""
    from soothe_cli.tui.textual_adapter import _apply_subagent_wire_lifecycle_event

    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    step = CognitionStepMessage("ZCH-01", "Survey RFCs", id="stp-subagent-done")
    adapter._current_step_messages["ZCH-01"] = step
    router = StepTaskRouter()
    router.on_step_started("ZCH-01")

    await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:s:task:0",
            "name": "task",
            "args": {
                "subagent_type": "deep_research",
                "description": "Enumerate files",
            },
        },
        ns_key=("execute:abc",),
        pending_tool_calls_lc={},
    )
    await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:t0:glob:0",
            "name": "glob",
            "args": {"glob_pattern": "**/*"},
        },
        ns_key=("execute:abc", "tools:done"),
        pending_tool_calls_lc={},
    )

    scope: tuple[str, str, str] = ("ZCH-01:s:task:0", "deep_research", "ZCH-01")
    handled = _apply_subagent_wire_lifecycle_event(
        adapter,
        event_type="soothe.subagent.deep_research.completed",
        data={"duration_ms": 1200, "summary": "Survey complete"},
        task_scope=scope,
    )
    assert handled is True
    task_rows = step._iter_task_delegation_rows()
    assert task_rows and task_rows[0].phase == "success"


def test_subagent_footer_ignores_server_step_tool_count() -> None:
    """SubAgent footer must use scope-local rows, not step-wide server totals."""
    from soothe_cli.tui.widgets.messages.cognition_step import create_subagent_card

    card = create_subagent_card(
        step_id="ZCH-01",
        description="Count files",
        subagent_type="deep_research",
        task_idx=0,
        id="subagent-test",
    )
    for i in range(7):
        card.add_tool_call(f"ZCH_01:t0:glob:{i}", "glob", {"glob_pattern": f"**/{i}"})
    card._status_widget = MagicMock()
    card._detail_widget = MagicMock()
    card.set_complete(True, 46426, 8, "Done")
    call_arg = card._status_widget.update.call_args[0][0]
    text = call_arg.plain if hasattr(call_arg, "plain") else str(call_arg)
    assert "7 tools" in text
    assert "8 tools" not in text


def test_subagent_card_shows_latest_two_tool_activities() -> None:
    """SubAgent cards preview the latest 2 tool rows, same cap as step cards."""
    from soothe_cli.tui.widgets.messages.cognition_step import create_subagent_card

    card = create_subagent_card(
        step_id="ZCH-01",
        description="Scan repo",
        subagent_type="deep_research",
        task_idx=0,
        id="subagent-preview",
    )
    for i in range(7):
        card.add_tool_call(f"ZCH_01:t0:glob:{i}", "glob", {"glob_pattern": f"**/{i}"})
    text = str(card._step_task_activity_content())
    assert "**/5" in text
    assert "**/6" in text
    assert "**/4" not in text
    assert "**/0" not in text
    assert "+5 more tools" in text


@pytest.mark.asyncio
async def test_subagent_wire_activity_event_shows_progress_note() -> None:
    from soothe_cli.tui.textual_adapter import _apply_subagent_wire_activity_event

    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    step = CognitionStepMessage("ZCH-01", "Research topic", id="stp-wire-activity")
    adapter._current_step_messages["ZCH-01"] = step
    router = StepTaskRouter()
    router.on_step_started("ZCH-01")
    await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:s:task:0",
            "name": "task",
            "args": {
                "subagent_type": "deep_research",
                "description": "OpenVela architecture",
            },
        },
        ns_key=("execute:abc",),
        pending_tool_calls_lc={},
    )
    scope: tuple[str, str, str] = ("ZCH_01:s:task:0", "deep_research", "ZCH-01")

    handled = _apply_subagent_wire_activity_event(
        adapter,
        event_type="soothe.subagent.deep_research.progress",
        data={
            "phase": "gather",
            "message": "Searching web: OpenVela",
            "loop_count": 1,
            "total_loops": 3,
        },
        task_scope=scope,
    )
    assert handled is True
    text = str(step._step_task_activity_content())
    assert "gather" in text
    assert "Searching web" in text


@pytest.mark.asyncio
async def test_subagent_wire_crawl_summary_counts_on_step_task_line() -> None:
    from soothe_cli.tui.textual_adapter import _apply_subagent_wire_step_event

    adapter = TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )
    step = CognitionStepMessage("ZCH-01", "Research topic", id="stp-wire-crawl")
    adapter._current_step_messages["ZCH-01"] = step
    router = StepTaskRouter()
    router.on_step_started("ZCH-01")
    await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "ZCH_01:s:task:0",
            "name": "task",
            "args": {
                "subagent_type": "deep_research",
                "description": "OpenVela architecture",
            },
        },
        ns_key=("execute:abc",),
        pending_tool_calls_lc={},
    )
    scope: tuple[str, str, str] = ("ZCH_01:s:task:0", "deep_research", "ZCH-01")

    handled = _apply_subagent_wire_step_event(
        adapter,
        event_type="soothe.subagent.deep_research.crawl.summary",
        data={"urls_crawled": 5, "success_count": 4},
        task_scope=scope,
    )
    assert handled is True
    step._status = "running"
    text = str(step._step_task_activity_content())
    assert "Deep Research(OpenVela architecture) · 1 tool" in text
    assert "Crawl(" not in text

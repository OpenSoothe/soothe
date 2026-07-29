"""IG-602: orphan wired-subagent SubAgent card mount / complete."""

from __future__ import annotations

import pytest
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE

from soothe_cli.runtime.state.step_router import StepTaskRouter
from soothe_cli.tui.textual_adapter import (
    TextualUIAdapter,
    _complete_orphan_subagent_card,
    _mount_manual_clarification_input,
    _mount_orphan_subagent_card,
    _route_orphan_wire_event,
    _route_pending_main_tools_to_orphans,
    apply_tool_call_wire_update,
)


def _make_adapter() -> TextualUIAdapter:
    mounted: list[object] = []

    def _mount(w: object) -> None:
        mounted.append(w)

    adapter = TextualUIAdapter(
        mount_message=_mount,
        update_status=lambda _s: None,
    )
    adapter._mounted = mounted  # type: ignore[attr-defined]
    return adapter


@pytest.mark.asyncio
async def test_mount_orphan_subagent_card_registers_keys() -> None:
    adapter = _make_adapter()
    card = await _mount_orphan_subagent_card(
        adapter,
        subagent="deep_research",
        invocation_id="abc123",
        step_id="XYZ-01",
        description="World Cup news",
    )
    assert card is not None
    assert getattr(card, "_invocation_id", "") == "abc123"
    assert adapter._orphan_cards_by_invocation["abc123"] is card
    assert card in adapter._mounted  # type: ignore[attr-defined]


def test_orphan_subagent_card_header_is_single_line_length_preview() -> None:
    from soothe_cli.tui.preview_limits import TASK_DELEGATION_DESC_MAX_CHARS
    from soothe_cli.tui.widgets.messages.cognition_subagent import create_subagent_card

    long_multiline = "Investigate deps\n" + ("across packages " * 20)
    card = create_subagent_card(
        "ORP-01",
        long_multiline,
        "deep_research",
        id="orphan-header-preview",
    )
    header = str(card._step_header_content())
    assert "Deep Research(" in header
    assert "\n" not in header.split("Deep Research(", 1)[-1].split(")", 1)[0]
    inner = header.split("Deep Research(", 1)[-1].rsplit(")", 1)[0]
    assert len(inner) <= TASK_DELEGATION_DESC_MAX_CHARS
    assert inner.endswith("...")


@pytest.mark.asyncio
async def test_orphan_wire_progress_attaches_without_step_widget() -> None:
    adapter = _make_adapter()
    await _mount_orphan_subagent_card(
        adapter,
        subagent="deep_research",
        invocation_id="inv1",
        step_id="WRE-01",
        description="topic",
    )
    assert not adapter._current_step_messages
    handled = _route_orphan_wire_event(
        adapter,
        event_type="soothe.subagent.deep_research.step.completed",
        data={
            "type": "soothe.subagent.deep_research.step.completed",
            "invocation_id": "inv1",
            "step_id": "WRE-01",
            "tool_name": "WebSearch",
            "args_preview": "query",
            "duration_ms": 12,
        },
    )
    assert handled is True
    card = adapter._orphan_cards_by_invocation["inv1"]
    assert len(getattr(card, "_rows", []) or []) >= 1


@pytest.mark.asyncio
async def test_orphan_planner_progress_sets_running_stage_not_notes() -> None:
    """Planner stage progress updates Running · stage; no activity notes."""
    adapter = _make_adapter()
    card = await _mount_orphan_subagent_card(
        adapter,
        subagent="planner",
        invocation_id="plan-inv",
        step_id="PLN-01",
        description="draft a plan",
    )
    handled = _route_orphan_wire_event(
        adapter,
        event_type="soothe.subagent.planner.progress",
        data={
            "type": "soothe.subagent.planner.progress",
            "invocation_id": "plan-inv",
            "step_id": "PLN-01",
            "phase": "draft",
            "message": "drafting 2/5",
            "loop_count": 2,
            "total_loops": 5,
        },
    )
    assert handled is True
    assert getattr(card, "_running_stage", "") == "drafting 2/5"
    assert not getattr(card, "_subagent_notes", [])


@pytest.mark.asyncio
async def test_complete_orphan_clears_registry() -> None:
    adapter = _make_adapter()
    await _mount_orphan_subagent_card(
        adapter,
        subagent="deep_research",
        invocation_id="inv2",
        step_id="WRE-02",
        description="topic",
    )
    _complete_orphan_subagent_card(
        adapter,
        invocation_id="inv2",
        success=True,
        duration_ms=100,
        summary="Done",
    )
    assert "inv2" not in adapter._orphan_cards_by_invocation


@pytest.mark.asyncio
async def test_orphan_browser_use_step_and_lifecycle() -> None:
    """browser_use wire steps settle on orphan cards; *.completed finds orphan registry."""
    from soothe_cli.tui.textual_adapter import _apply_subagent_wire_lifecycle_event

    adapter = _make_adapter()
    card = await _mount_orphan_subagent_card(
        adapter,
        subagent="browser_use",
        invocation_id="bu-inv",
        step_id="BRW-01",
        description="open example.com",
    )
    assert card is not None

    handled = _route_orphan_wire_event(
        adapter,
        event_type="soothe.subagent.browser_use.started",
        data={
            "type": "soothe.subagent.browser_use.started",
            "invocation_id": "bu-inv",
            "task_preview": "open example.com",
        },
    )
    assert handled is True

    handled = _route_orphan_wire_event(
        adapter,
        event_type="soothe.subagent.browser_use.step.completed",
        data={
            "type": "soothe.subagent.browser_use.step.completed",
            "invocation_id": "bu-inv",
            "step_index": 1,
            "action_preview": "navigate",
            "url": "https://example.com",
            "status": "done",  # step finished
            "duration_ms": 400,
        },
    )
    assert handled is True
    rows = list(getattr(card, "_rows", []) or [])
    assert rows
    assert getattr(rows[-1], "phase", "") == "success"

    # Wire lifecycle must resolve orphan (not only {step}:t0).
    scope: tuple[str, str, str] = ("BRW-01:s:task:0", "browser_use", "BRW-01")
    handled = _apply_subagent_wire_lifecycle_event(
        adapter,
        event_type="soothe.subagent.browser_use.completed",
        data={
            "invocation_id": "bu-inv",
            "duration_ms": 1200,
            "success": True,
            "summary": "Opened example.com",
        },
        task_scope=scope,
    )
    assert handled is True
    assert getattr(card, "_status", "") == "success"
    assert "bu-inv" not in adapter._orphan_cards_by_invocation


@pytest.mark.asyncio
async def test_orphan_wire_step_requires_invocation_id() -> None:
    """Orphan wire routing requires stamped invocation_id (no step_id-only fallback)."""
    adapter = _make_adapter()
    card = await _mount_orphan_subagent_card(
        adapter,
        subagent="browser_use",
        invocation_id="bu-no-inv",
        step_id="BRW-03",
        description="task",
    )
    assert card is not None

    handled = _route_orphan_wire_event(
        adapter,
        event_type="soothe.subagent.browser_use.step.completed",
        data={
            "type": "soothe.subagent.browser_use.step.completed",
            "step_id": "BRW-03",
            "tool_name": "Navigate",
            "action_preview": "https://example.com",
            "duration_ms": 123,
        },
    )
    assert handled is False
    assert not list(getattr(card, "_rows", []) or [])


@pytest.mark.asyncio
async def test_orphan_browser_use_lifecycle_honors_success_false() -> None:
    adapter = _make_adapter()
    card = await _mount_orphan_subagent_card(
        adapter,
        subagent="browser_use",
        invocation_id="bu-fail",
        step_id="BRW-02",
        description="task",
    )
    from soothe_cli.tui.textual_adapter import _apply_subagent_wire_lifecycle_event

    scope: tuple[str, str, str] = ("BRW-02:s:task:0", "browser_use", "BRW-02")
    handled = _apply_subagent_wire_lifecycle_event(
        adapter,
        event_type="soothe.subagent.browser_use.completed",
        data={
            "invocation_id": "bu-fail",
            "duration_ms": 50,
            "success": False,
            "summary": "Failed",
        },
        task_scope=scope,
    )
    assert handled is True
    assert getattr(card, "_status", "") == "error"


@pytest.mark.asyncio
async def test_root_ns_tool_wire_update_routes_to_orphan_card() -> None:
    """Intake-only stamped tools on ns ``()`` must land on the orphan card."""
    adapter = _make_adapter()
    card = await _mount_orphan_subagent_card(
        adapter,
        subagent="planner",
        invocation_id="plan-inv",
        step_id="HYE_01",
        description="optimize deps",
    )
    assert card is not None
    router = StepTaskRouter()
    handled = await apply_tool_call_wire_update(
        adapter,
        router,
        data={
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "HYE_01:s:call_abc",
            "name": "grep",
            "args": {"pattern": "uv.lock"},
            "step_id": "HYE_01",
        },
        ns_key=(),
        pending_tool_calls_lc={},
    )
    assert handled is True
    assert card.has_tool_call_row("HYE_01:s:call_abc")
    assert router.pending_main_tool_count == 0
    # Display index must include type ``s`` stamped tools (not only type ``t``).
    index = card._build_row_index()  # noqa: SLF001
    assert index.main_tool_count == 1
    assert index.total_tool_count == 1
    assert any(r.tool_call_id == "HYE_01:s:call_abc" for r in index.main_tools)


@pytest.mark.asyncio
async def test_buffered_main_tools_flush_to_orphan_on_mount() -> None:
    adapter = _make_adapter()
    router = adapter._step_router
    router.buffer_main_tool(
        "HYE_01:s:call_buf",
        "read_file",
        {"file_path": "pyproject.toml"},
    )
    card = await _mount_orphan_subagent_card(
        adapter,
        subagent="planner",
        invocation_id="plan-buf",
        step_id="HYE_01",
        description="optimize deps",
    )
    assert card is not None
    assert card.has_tool_call_row("HYE_01:s:call_buf")
    assert router.pending_main_tool_count == 0


@pytest.mark.asyncio
async def test_route_pending_main_tools_to_orphans_safety_net() -> None:
    adapter = _make_adapter()
    card = await _mount_orphan_subagent_card(
        adapter,
        subagent="planner",
        invocation_id="plan-late",
        step_id="HYE_01",
        description="optimize deps",
    )
    router = StepTaskRouter()
    router.buffer_main_tool("HYE_01:s:call_late", "ls", {"path": "."})
    routed = _route_pending_main_tools_to_orphans(adapter, router)
    assert routed == 1
    assert card is not None
    assert card.has_tool_call_row("HYE_01:s:call_late")


@pytest.mark.asyncio
async def test_manual_clarification_mounts_without_step_or_orphan() -> None:
    """Plan review after orphan complete must still show the answer widget."""
    adapter = _make_adapter()
    assert not adapter._current_step_messages
    assert not adapter._orphan_cards_by_invocation
    key = await _mount_manual_clarification_input(
        adapter,
        questions=["Approve this plan?", "Comments?"],
        origin_node="planner_subagent_review",
        plan_path="/tmp/plans/demo.md",
        plan_markdown="# Plan\n\nDo things.\n",
    )
    assert key == "planner_subagent_review"
    widget = adapter._clarification_input_by_step[key]
    assert widget in adapter._mounted  # type: ignore[attr-defined]
    assert getattr(widget, "_origin_node", "") == "planner_subagent_review"
    assert getattr(widget, "_plan_path", "") == "/tmp/plans/demo.md"
    assert "# Plan" in getattr(widget, "_plan_markdown", "")


@pytest.mark.asyncio
async def test_manual_clarification_prefers_active_orphan_step_id() -> None:
    adapter = _make_adapter()
    await _mount_orphan_subagent_card(
        adapter,
        subagent="planner",
        invocation_id="plan-clarify",
        step_id="HYE_01",
        description="optimize deps",
    )
    key = await _mount_manual_clarification_input(
        adapter,
        questions=["Approve?"],
        origin_node="planner_subagent_review",
    )
    assert key == "HYE_01"

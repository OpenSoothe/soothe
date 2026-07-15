"""IG-602: orphan wired-subagent SubAgent card mount / complete."""

from __future__ import annotations

import pytest

from soothe_cli.tui.textual_adapter import (
    TextualUIAdapter,
    _complete_orphan_subagent_card,
    _mount_orphan_subagent_card,
    _orphan_registry_key,
    _route_orphan_wire_event,
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
    assert getattr(card, "_parent_step_id", "") == ""
    assert adapter._orphan_cards_by_invocation["abc123"] is card
    assert adapter._subagent_cards_by_key[_orphan_registry_key("deep_research", "abc123")] is card
    assert "XYZ-01:t0" not in adapter._subagent_cards_by_key
    assert card in adapter._mounted  # type: ignore[attr-defined]


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
    assert _orphan_registry_key("deep_research", "inv2") not in adapter._subagent_cards_by_key
    assert "WRE-02:t0" not in adapter._subagent_cards_by_key


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
    assert _orphan_registry_key("browser_use", "bu-inv") not in adapter._subagent_cards_by_key


@pytest.mark.asyncio
async def test_orphan_wire_step_routes_without_invocation_id() -> None:
    """Fallback routing should still show step rows when invocation_id is missing."""
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
            # Simulate legacy/malformed forwarding where invocation_id is absent.
            "step_id": "BRW-03",
            "tool_name": "Navigate",
            "action_preview": "https://example.com",
            "duration_ms": 123,
        },
    )
    assert handled is True
    rows = list(getattr(card, "_rows", []) or [])
    assert rows
    assert getattr(rows[-1], "tool_name", "") == "Navigate"
    assert getattr(rows[-1], "phase", "") == "success"


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
            "success": False,
            "summary": "Browser start failed",
            "duration_ms": 50,
        },
        task_scope=scope,
    )
    assert handled is True
    assert getattr(card, "_status", "") == "error"

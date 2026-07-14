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

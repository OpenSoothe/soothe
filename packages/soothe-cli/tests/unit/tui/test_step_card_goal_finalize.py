"""Finalize tracked step cards when the agent loop goal completes."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from soothe_cli.tui.step_task_routing import StepTaskRouter
from soothe_cli.tui.textual_adapter import (
    TextualUIAdapter,
    finalize_tracked_step_cards_on_goal_complete,
    sync_pending_step_cards_from_plan,
)


@pytest.mark.asyncio
async def test_goal_complete_finalizes_pending_step_cards() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=AsyncMock(),
    )
    router = StepTaskRouter()
    await sync_pending_step_cards_from_plan(
        adapter,
        steps=[{"id": "EVK-08", "description": "Update CLI files"}],
    )
    card = adapter._current_step_messages["EVK-08"]
    card.add_tool_call("EVK_08:s:task:0", "code", {"subagent_type": "code"}, is_task_row=True)

    finalize_tracked_step_cards_on_goal_complete(adapter, router)

    assert "EVK-08" not in adapter._current_step_messages
    assert card._status == "success"  # noqa: SLF001

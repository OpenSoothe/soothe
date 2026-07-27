"""Live ``soothe.card.*`` apply path (adapter wiring + create/update)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_sdk.core.events import CARD_CREATED, CARD_UPDATED
from soothe_sdk.display.transcript_types import MessageData, MessageType

from soothe_cli.tui.app._messages_mixin import _MessagesMixin
from soothe_cli.tui.textual_adapter import TextualUIAdapter


class _FakeStore:
    def __init__(self) -> None:
        self._msgs: list[MessageData] = []

    def append(self, msg: MessageData) -> None:
        self._msgs.append(msg)

    def get_all_messages(self) -> list[MessageData]:
        return list(self._msgs)

    def update_message(self, card_id: str, **fields: Any) -> bool:
        for msg in self._msgs:
            if msg.id == card_id:
                for key, value in fields.items():
                    if hasattr(msg, key):
                        setattr(msg, key, value)
                return True
        return False


class _ApplyCardHost(_MessagesMixin):
    """Minimal host exercising ``_apply_card_wire_frame`` without Textual App."""

    def __init__(self) -> None:
        self._message_store = _FakeStore()
        self._ui_adapter = SimpleNamespace(_current_step_messages={})
        self.mounted: list[Any] = []
        self.hydrated: list[tuple[Any, str]] = []
        self._widgets_by_id: dict[str, Any] = {}

    async def _mount_message(self, widget: Any) -> None:
        self.mounted.append(widget)
        if getattr(widget, "id", None):
            self._widgets_by_id[widget.id] = widget
        from soothe_cli.tui.binding import message_from_widget

        self._message_store.append(message_from_widget(widget))

    def _enqueue_hydrated_assistant_render(self, widget: Any, content: str) -> None:
        self.hydrated.append((widget, content))

    def query_one(self, selector: str) -> Any:
        if selector.startswith("#"):
            widget = self._widgets_by_id.get(selector[1:])
            if widget is not None:
                return widget
        raise LookupError(selector)


@pytest.mark.asyncio
async def test_apply_card_created_mounts_assistant() -> None:
    host = _ApplyCardHost()
    handled = await host._apply_card_wire_frame(
        {
            "type": CARD_CREATED,
            "card_id": "asst-1",
            "kind": "assistant",
            "data": {
                "type": "assistant",
                "content": "hello from ledger",
                "id": "asst-1",
            },
        }
    )
    assert handled is True
    assert len(host.mounted) == 1
    assert host.hydrated and host.hydrated[0][1] == "hello from ledger"


@pytest.mark.asyncio
async def test_apply_card_skips_duplicate_user_prompt() -> None:
    host = _ApplyCardHost()
    host._message_store.append(MessageData(type=MessageType.USER, content="count files", id="u0"))
    handled = await host._apply_card_wire_frame(
        {
            "type": CARD_CREATED,
            "card_id": "u1",
            "kind": "user",
            "data": {"type": "user", "content": "count files", "id": "u1"},
        }
    )
    assert handled is True
    assert host.mounted == []


@pytest.mark.asyncio
async def test_apply_card_reuses_existing_step_widget() -> None:
    host = _ApplyCardHost()
    step = SimpleNamespace(id="step-local", _step_id="S1")
    host._ui_adapter._current_step_messages["S1"] = step
    handled = await host._apply_card_wire_frame(
        {
            "type": CARD_CREATED,
            "card_id": "card-step",
            "kind": "step_progress",
            "data": {
                "type": "step_progress",
                "content": "",
                "id": "card-step",
                "step_progress_id": "S1",
                "step_progress_description": "do work",
            },
        }
    )
    assert handled is True
    assert host.mounted == []
    assert host._ui_adapter._current_step_messages["S1"] is step


@pytest.mark.asyncio
async def test_apply_card_updated_assistant_content() -> None:
    host = _ApplyCardHost()
    await host._apply_card_wire_frame(
        {
            "type": CARD_CREATED,
            "card_id": "asst-1",
            "kind": "assistant",
            "data": {"type": "assistant", "content": "hel", "id": "asst-1"},
        }
    )
    host.hydrated.clear()
    handled = await host._apply_card_wire_frame(
        {
            "type": CARD_UPDATED,
            "card_id": "asst-1",
            "kind": "assistant",
            "data": {"content": "hello world", "is_streaming": False},
        }
    )
    assert handled is True
    assert host.hydrated and host.hydrated[0][1] == "hello world"


@pytest.mark.asyncio
async def test_apply_card_skips_assistant_when_goal_completion_mounted() -> None:
    host = _ApplyCardHost()
    host._ui_adapter._goal_completion_mounted_this_turn = True
    handled = await host._apply_card_wire_frame(
        {
            "type": CARD_CREATED,
            "card_id": "asst-gc",
            "kind": "assistant",
            "data": {
                "type": "assistant",
                "content": "3354 files",
                "id": "asst-gc",
                "loop_output_phase": "goal_completion",
            },
        }
    )
    assert handled is True
    assert host.mounted == []


@pytest.mark.asyncio
async def test_apply_card_skips_duplicate_cognition_reason() -> None:
    host = _ApplyCardHost()
    host._message_store.append(
        MessageData(
            type=MessageType.COGNITION_REASON,
            content="",
            id="intent-local",
            cognition_plan_strategy="I'll inspect the repo layout.",
        )
    )
    handled = await host._apply_card_wire_frame(
        {
            "type": CARD_CREATED,
            "card_id": "cog-1",
            "kind": "cognition_reason",
            "data": {
                "type": "cognition_reason",
                "content": "",
                "id": "cog-1",
                "cognition_plan_strategy": "I'll inspect the repo layout.",
            },
        }
    )
    assert handled is True
    assert host.mounted == []


def test_adapter_exposes_apply_card_callback_slot() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=MagicMock(),
    )
    assert adapter._apply_card_wire_frame is None
    adapter._apply_card_wire_frame = AsyncMock(return_value=True)
    assert callable(adapter._apply_card_wire_frame)

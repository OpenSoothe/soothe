"""Per-loop card ledger lifecycle, real-time binding, and reattach replay."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from soothe_sdk.display import card_binder
from soothe_sdk.display.card_ledger import cards_to_mutations
from soothe_sdk.langchain_wire import messages_from_wire_dicts

from soothe_daemon.display.loop_card_ledger import LoopCardLedger
from soothe_daemon.display.loop_history_probe import filter_derivable_log_events

if TYPE_CHECKING:
    from soothe_sdk.display.transcript_types import MessageData

logger = logging.getLogger(__name__)

CARD_REPLAY_BEGIN = "card.replay_begin"
CARD_CREATED = "card.created"
CARD_REPLAY_END = "card.replay_end"

_DERIVABLE_CUSTOM_KINDS = frozenset({"event", "tool_call", "tool_result", "conversation"})


@dataclass
class _BindingBuffers:
    messages: list[Any] = field(default_factory=list)
    log_events: list[dict[str, Any]] = field(default_factory=list)


class LoopCardManager:
    """Owns per-loop ``LoopCardLedger`` instances and real-time card binding."""

    def __init__(self, daemon: Any) -> None:
        self._daemon = daemon
        self._ledgers: dict[str, LoopCardLedger] = {}
        self._buffers: dict[str, _BindingBuffers] = defaultdict(_BindingBuffers)

    async def stop_for_loop(self, loop_id: str) -> None:
        """Drop in-memory ledger and binding buffers for ``loop_id``."""
        self._ledgers.pop(loop_id, None)
        self._buffers.pop(loop_id, None)

    async def _open_ledger(self, loop_id: str) -> LoopCardLedger:
        ledger = self._ledgers.get(loop_id)
        if ledger is None:
            ledger = LoopCardLedger(loop_id=loop_id)
            self._ledgers[loop_id] = ledger
        await ledger.ensure_loaded()
        return ledger

    async def ensure_for_loop(self, loop_id: str) -> LoopCardLedger:
        """Return the ledger for ``loop_id``, loading persisted mutations from DB."""
        return await self._open_ledger(loop_id)

    async def is_display_empty(self, loop_id: str) -> bool:
        """Return True when the persisted ledger has no display cards."""
        ledger = await self._open_ledger(loop_id)
        return ledger.card_count() == 0

    async def record_user_prompt(self, loop_id: str, prompt: str) -> None:
        """Bind the initial user prompt card when a loop turn starts."""
        text = str(prompt or "").strip()
        if not text:
            return
        state = self._buffers[loop_id]
        state.messages = [m for m in state.messages if not isinstance(m, HumanMessage)]
        state.messages.insert(0, HumanMessage(content=text))
        await self._flush_buffers_to_ledger(loop_id, state)

    async def on_event(self, loop_id: str, event: dict[str, Any]) -> None:
        """Apply one derivable activity-log style event to the ledger."""
        rows = filter_derivable_log_events([event])
        if not rows:
            return
        state = self._buffers[loop_id]
        state.log_events.append(rows[0])
        await self._flush_buffers_to_ledger(loop_id, state)

    async def ingest_stream_tuple(
        self,
        loop_id: str,
        namespace: tuple[str, ...],
        mode: str,
        data: Any,
    ) -> None:
        """Bind cards from one runner stream tuple as execution progresses."""
        del namespace  # reserved for future namespace-aware binding
        if mode == "updates":
            return
        state = self._buffers[loop_id]
        changed = False
        if mode == "messages" and isinstance(data, (tuple, list)) and len(data) == 2:
            msg_wire = data[0]
            if isinstance(msg_wire, dict):
                changed = self._ingest_message_wire(state, msg_wire)
        elif mode == "custom" and isinstance(data, dict):
            kind = data.get("kind")
            if kind in _DERIVABLE_CUSTOM_KINDS:
                state.log_events.append(data)
                changed = True
        if changed:
            await self._flush_buffers_to_ledger(loop_id, state)

    @staticmethod
    def _ingest_message_wire(state: _BindingBuffers, msg_wire: dict[str, Any]) -> bool:
        from soothe_sdk.client.wire import flatten_enveloped_message_dict

        flat = flatten_enveloped_message_dict(msg_wire)
        chunk_pos = flat.get("chunk_position")
        if chunk_pos not in (None, "last"):
            return False
        try:
            msgs = messages_from_wire_dicts([flat])
        except Exception:
            logger.debug("Failed to parse stream message for card binding", exc_info=True)
            return False
        if not msgs:
            return False
        state.messages.extend(msgs)
        return True

    async def _flush_buffers_to_ledger(self, loop_id: str, state: _BindingBuffers) -> None:
        cards = await asyncio.to_thread(self._bind_cards, state.messages, state.log_events)
        ledger = await self._open_ledger(loop_id)
        mutations = cards_to_mutations(cards) if cards else []
        if mutations:
            await ledger.replace_with(mutations)

    @staticmethod
    def _bind_cards(
        messages: list[Any],
        log_events: list[dict[str, Any]],
    ) -> list[MessageData]:
        cognition_replay: list[MessageData] = []
        if log_events:
            cognition_replay = card_binder.collect_cognition_card_replay(log_events)
        visible_messages = [
            message
            for message in messages
            if not card_binder.is_loop_internal_checkpoint_message(message)
        ]
        if visible_messages:
            return card_binder.convert_messages_to_data(
                visible_messages,
                cognition_card_replay=cognition_replay if cognition_replay else None,
            )
        if log_events:
            return card_binder.convert_loop_events_to_data(log_events)
        return []

    async def replay_to_client(
        self,
        loop_id: str,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> int:
        """Stream ``card.replay_begin`` → ``card.created`` × N → ``card.replay_end``."""
        ledger = await self.ensure_for_loop(loop_id)
        if ledger.card_count() == 0:
            return await self._emit_empty_replay(loop_id, send_fn)
        return await self._emit_replay_from_ledger(loop_id, ledger, send_fn)

    async def _emit_empty_replay(
        self,
        loop_id: str,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> int:
        await send_fn(
            {
                "type": CARD_REPLAY_BEGIN,
                "loop_id": loop_id,
                "total_cards": 0,
                "latest_seq": 0,
            }
        )
        await send_fn(
            {
                "type": CARD_REPLAY_END,
                "loop_id": loop_id,
                "latest_seq": 0,
                "card_count": 0,
            }
        )
        return 0

    async def _emit_replay_from_ledger(
        self,
        loop_id: str,
        ledger: LoopCardLedger,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> int:
        async with ledger.lock():
            mutations = ledger.to_mutations_snapshot()
        total = len(mutations)
        latest_seq = mutations[-1].seq if mutations else 0

        await send_fn(
            {
                "type": CARD_REPLAY_BEGIN,
                "loop_id": loop_id,
                "total_cards": total,
                "latest_seq": latest_seq,
            }
        )
        for mutation in mutations:
            await send_fn(
                {
                    "type": CARD_CREATED,
                    "loop_id": loop_id,
                    "seq": mutation.seq,
                    "card_id": mutation.card_id,
                    "kind": mutation.kind,
                    "data": mutation.data,
                }
            )
        await send_fn(
            {
                "type": CARD_REPLAY_END,
                "loop_id": loop_id,
                "latest_seq": latest_seq,
                "card_count": total,
            }
        )
        return total


__all__ = [
    "CARD_CREATED",
    "CARD_REPLAY_BEGIN",
    "CARD_REPLAY_END",
    "LoopCardManager",
]

"""SQLite-backed per-loop card ledger."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from soothe.backends.persistence.display_store import get_display_card_store
from soothe_sdk.display.card_ledger import (
    CardMutation,
    InMemoryCardLedger,
    build_header_mutation,
    card_to_wire_dict,
    utc_now_iso,
)

if TYPE_CHECKING:
    from soothe_sdk.display.transcript_types import MessageData

logger = logging.getLogger(__name__)


class LoopCardLedger:
    """SQLite-backed ledger for one loop."""

    def __init__(
        self,
        *,
        loop_id: str,
        created_by: str = "soothe-daemon",
    ) -> None:
        self._loop_id = loop_id
        self._created_by = created_by
        self._store = get_display_card_store()
        self._inner = InMemoryCardLedger(loop_id=loop_id)
        self._lock = asyncio.Lock()
        self._loaded = False

    @property
    def loop_id(self) -> str:
        return self._loop_id

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def card_count(self) -> int:
        return self._inner.card_count()

    def snapshot(self) -> list[MessageData]:
        return self._inner.snapshot()

    def next_seq(self) -> int:
        return self._inner.next_seq

    def lock(self) -> asyncio.Lock:
        return self._lock

    async def ensure_loaded(self) -> None:
        """Load mutations from ``display.db`` or initialize a header row."""
        async with self._lock:
            if self._loaded:
                return
            await asyncio.to_thread(self._load_or_initialize_sync)
            self._loaded = True

    def _load_or_initialize_sync(self) -> None:
        mutations = self._store.list_mutations(self._loop_id)
        if not mutations:
            header = build_header_mutation(
                loop_id=self._loop_id,
                created_by=self._created_by,
            )
            self._store.append_mutations(self._loop_id, [header])
            mutations = [header]

        ledger = InMemoryCardLedger(loop_id=self._loop_id)
        for mutation in mutations:
            try:
                ledger.apply(mutation)
            except ValueError as exc:
                logger.warning(
                    "Dropping inconsistent card mutation seq=%d for loop %s: %s",
                    mutation.seq,
                    self._loop_id,
                    exc,
                )
        self._inner = ledger

    async def append(self, mutation: CardMutation) -> None:
        if not self._loaded:
            await self.ensure_loaded()
        async with self._lock:
            self._inner.apply(mutation)
            await asyncio.to_thread(self._store.append_mutations, self._loop_id, [mutation])

    async def append_many(self, mutations: Iterable[CardMutation]) -> None:
        items = list(mutations)
        if not items:
            return
        if not self._loaded:
            await self.ensure_loaded()
        async with self._lock:
            for mutation in items:
                self._inner.apply(mutation)
            await asyncio.to_thread(self._store.append_mutations, self._loop_id, items)

    async def replace_with(self, mutations: Iterable[CardMutation]) -> None:
        items = list(mutations)
        async with self._lock:
            header = build_header_mutation(loop_id=self._loop_id, created_by=self._created_by)
            all_mutations = [header, *items]
            await asyncio.to_thread(self._store.replace_mutations, self._loop_id, all_mutations)
            self._inner = InMemoryCardLedger(loop_id=self._loop_id)
            for mutation in all_mutations:
                self._inner.apply(mutation)
            self._loaded = True

    def to_mutations_snapshot(self) -> list[CardMutation]:
        snapshot = self._inner.snapshot()
        return [
            CardMutation(
                seq=offset + 1,
                ts=utc_now_iso(),
                op="create",
                card_id=card.id,
                kind=str(card.type),
                data=card_to_wire_dict(card),
            )
            for offset, card in enumerate(snapshot)
        ]


__all__ = ["LoopCardLedger"]

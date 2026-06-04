"""File-backed per-loop card ledger (RFC-413).

Wraps ``soothe_sdk.display.InMemoryCardLedger`` with:

* Append-only JSONL persistence at
  ``~/.soothe/data/loops/<loop_id>/cards.jsonl``.
* Per-loop ``asyncio.Lock`` for single-writer-multi-reader safety.
* Header record on first open so consumers can detect schema version.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

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

_CARDS_FILENAME = "cards.jsonl"


class LoopCardLedger:
    """File-backed ledger for one loop.

    Construction does not touch disk — call :meth:`ensure_loaded` first to
    materialize state from an existing ``cards.jsonl`` or create a fresh file
    with a header record.
    """

    def __init__(
        self,
        *,
        loop_id: str,
        directory: Path,
        created_by: str = "soothe-daemon",
    ) -> None:
        self._loop_id = loop_id
        self._directory = Path(directory)
        self._created_by = created_by
        self._path = self._directory / _CARDS_FILENAME
        self._inner = InMemoryCardLedger(loop_id=loop_id)
        self._lock = asyncio.Lock()
        self._loaded = False

    @property
    def loop_id(self) -> str:
        return self._loop_id

    @property
    def path(self) -> Path:
        return self._path

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def card_count(self) -> int:
        """Number of cards in the in-memory projection (unlocked, snapshot read)."""
        return self._inner.card_count()

    def snapshot(self) -> list[MessageData]:
        """Return cards in insertion order. Should be called under :meth:`lock`."""
        return self._inner.snapshot()

    def next_seq(self) -> int:
        """Sequence number that would be assigned to the next mutation."""
        return self._inner.next_seq

    def lock(self) -> asyncio.Lock:
        """Public access to the per-loop write lock for callers that need to
        snapshot + read in a critical section."""
        return self._lock

    async def ensure_loaded(self) -> None:
        """Load cards.jsonl into memory, or create a fresh file with a header.

        Idempotent: safe to call multiple times.
        """
        async with self._lock:
            if self._loaded:
                return
            await asyncio.to_thread(self._load_or_initialize_sync)
            self._loaded = True

    def _load_or_initialize_sync(self) -> None:
        """Blocking I/O: read existing file or initialize a new one."""
        self._directory.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            header = build_header_mutation(
                loop_id=self._loop_id,
                created_by=self._created_by,
            )
            self._inner = InMemoryCardLedger(loop_id=self._loop_id)
            self._inner.apply(header)
            with self._path.open("w", encoding="utf-8") as fh:
                fh.write(json.dumps(header.to_jsonl_dict()) + "\n")
            return

        mutations: list[CardMutation] = []
        try:
            with self._path.open(encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                        mutations.append(CardMutation.from_jsonl_dict(raw))
                    except (json.JSONDecodeError, KeyError, ValueError):
                        logger.warning(
                            "Skipping malformed card ledger line %s:%d",
                            self._path,
                            lineno,
                        )
        except OSError:
            logger.warning("Failed to read card ledger %s", self._path, exc_info=True)
            return

        ledger = InMemoryCardLedger(loop_id=self._loop_id)
        for mutation in mutations:
            try:
                ledger.apply(mutation)
            except ValueError as exc:
                logger.warning(
                    "Dropping inconsistent card ledger mutation seq=%d in %s: %s",
                    mutation.seq,
                    self._path,
                    exc,
                )
        self._inner = ledger

    async def append(self, mutation: CardMutation) -> None:
        """Append one mutation to disk and the in-memory projection."""
        if not self._loaded:
            await self.ensure_loaded()
        async with self._lock:
            self._inner.apply(mutation)
            await asyncio.to_thread(self._append_sync, mutation)

    async def append_many(self, mutations: Iterable[CardMutation]) -> None:
        """Append several mutations in one critical section (one fsync batch)."""
        items = list(mutations)
        if not items:
            return
        if not self._loaded:
            await self.ensure_loaded()
        async with self._lock:
            for mutation in items:
                self._inner.apply(mutation)
            await asyncio.to_thread(self._append_many_sync, items)

    def _append_sync(self, mutation: CardMutation) -> None:
        """Blocking I/O: append one line."""
        self._directory.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(mutation.to_jsonl_dict()) + "\n")

    def _append_many_sync(self, mutations: list[CardMutation]) -> None:
        """Blocking I/O: append several lines."""
        self._directory.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            for mutation in mutations:
                fh.write(json.dumps(mutation.to_jsonl_dict()) + "\n")

    async def replace_with(self, mutations: Iterable[CardMutation]) -> None:
        """Rewrite the file with a fresh header + the given mutations.

        Used by backfill when an empty (header-only) ledger needs to be
        populated from checkpoint + activity log in one shot. The header is
        regenerated; ``mutations`` are appended after it with sequential ``seq``
        starting from 1.
        """
        items = list(mutations)
        async with self._lock:
            await asyncio.to_thread(self._replace_with_sync, items)
            self._inner = InMemoryCardLedger(loop_id=self._loop_id)
            self._inner.apply(
                build_header_mutation(loop_id=self._loop_id, created_by=self._created_by)
            )
            for mutation in items:
                self._inner.apply(mutation)
            self._loaded = True

    def _replace_with_sync(self, mutations: list[CardMutation]) -> None:
        """Blocking I/O: rewrite header + mutations."""
        self._directory.mkdir(parents=True, exist_ok=True)
        header = build_header_mutation(loop_id=self._loop_id, created_by=self._created_by)
        with self._path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(header.to_jsonl_dict()) + "\n")
            for mutation in mutations:
                fh.write(json.dumps(mutation.to_jsonl_dict()) + "\n")

    def to_mutations_snapshot(self) -> list[CardMutation]:
        """Project the current in-memory ledger as a ``create``-only mutation stream.

        Used by ``LoopCardManager.replay_to_client`` to convert the latest-state
        projection into a wire-ready ordered stream. Each mutation gets a fresh
        ``seq`` starting from 1 and an ISO-now timestamp — those are diagnostic
        metadata for the replay frames, not the original on-disk seq/ts.
        Should be called under :meth:`lock` if the ledger may be mutated
        concurrently.
        """
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

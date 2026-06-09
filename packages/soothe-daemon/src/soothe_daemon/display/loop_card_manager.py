"""Per-loop card ledger lifecycle + lazy derivation + reattach replay (RFC-413).

The manager:

* Tracks ``loop_id → LoopCardLedger`` for active loops.
* On first access (or when stale), backfills the ledger from authoritative
  sources — LangGraph checkpoint messages + persisted activity-log rows —
  using ``soothe_sdk.display.card_binder``.
* Exposes ``replay_to_client`` which streams ``card.replay_begin`` →
  ``card.created`` × N → ``card.replay_end`` frames for use by
  ``handle_loop_reattach`` and ``loop_subscribe``.

Derivation is lazy on RPC, not streaming. The binder runs in a thread
(``asyncio.to_thread``) over the loop's checkpoint + activity log each
time we refresh. A future iteration may introduce a real-time binder
that maintains the ledger as live events arrive.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from soothe.foundation.loop.state.persistence.directory_manager import PersistenceDirectoryManager
from soothe_sdk.display import card_binder
from soothe_sdk.display.card_ledger import cards_to_mutations
from soothe_sdk.langchain_wire import messages_from_wire_dicts

from soothe_daemon.display.loop_card_ledger import LoopCardLedger

if TYPE_CHECKING:
    from soothe_sdk.display.transcript_types import MessageData


logger = logging.getLogger(__name__)

# Wire frame type constants for card.* replay (RFC-413).
CARD_REPLAY_BEGIN = "card.replay_begin"
CARD_CREATED = "card.created"
CARD_REPLAY_END = "card.replay_end"


class LoopCardManager:
    """Owns the per-loop ``LoopCardLedger`` map and the derivation pipeline.

    Construction takes a daemon-shaped object exposing ``_runner`` (for
    checkpoint + activity-log access). The manager itself does not require
    the daemon to be fully started; it's instantiated in ``Daemon.__init__``
    and used after the runner is available.
    """

    def __init__(self, daemon: Any) -> None:
        self._daemon = daemon
        self._ledgers: dict[str, LoopCardLedger] = {}
        # One asyncio.Lock per loop guarding derivation (so two parallel
        # `ensure_for_loop` calls don't both re-derive). Held briefly; the
        # ledger has its own append lock for I/O.
        self._derive_locks: dict[str, asyncio.Lock] = {}
        # Timestamp of last derivation per loop, monotonic seconds.
        self._last_derived_at: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def stop_for_loop(self, loop_id: str) -> None:
        """Drop the in-memory ledger for ``loop_id``. Disk file is untouched.

        Called from loop GC / purge paths. The cards.jsonl file is deleted
        as part of the per-loop data directory purge already done by the
        existing GC; this method just releases the in-memory state.
        """
        self._ledgers.pop(loop_id, None)
        self._derive_locks.pop(loop_id, None)
        self._last_derived_at.pop(loop_id, None)

    # ------------------------------------------------------------------
    # Derivation
    # ------------------------------------------------------------------

    async def ensure_for_loop(self, loop_id: str) -> LoopCardLedger:
        """Return a populated ledger for ``loop_id``, deriving if needed.

        Side effects:

        * Creates ``cards.jsonl`` if it does not yet exist.
        * Re-derives the ledger from checkpoint + activity log if the ledger
          is empty (header-only) on first open.

        No explicit staleness check is implemented beyond "empty ledger →
        derive once". A future iteration may add live updates that keep
        the ledger in sync with the active loop without re-derivation.
        """
        ledger = self._ledgers.get(loop_id)
        if ledger is None:
            directory = PersistenceDirectoryManager.get_loop_directory(loop_id)
            ledger = LoopCardLedger(loop_id=loop_id, directory=directory)
            self._ledgers[loop_id] = ledger

        await ledger.ensure_loaded()
        if ledger.card_count() == 0:
            await self._derive_into(loop_id, ledger)
        return ledger

    async def refresh(self, loop_id: str) -> LoopCardLedger:
        """Force-re-derive ledger from authoritative sources.

        Used when a caller wants to invalidate the cached projection (e.g.
        after a turn completes). Callers may opt to invoke this from a
        turn-completion hook; the default RPC path uses the cached ledger.
        """
        ledger = await self.ensure_for_loop(loop_id)
        await self._derive_into(loop_id, ledger)
        return ledger

    async def _derive_into(self, loop_id: str, ledger: LoopCardLedger) -> None:
        """Run the SDK binder over checkpoint + activity log and replace the
        ledger contents with the resulting cards."""
        lock = self._derive_locks.setdefault(loop_id, asyncio.Lock())
        async with lock:
            t0 = time.monotonic()
            try:
                cards = await self._derive_cards(loop_id)
            except Exception:
                logger.warning("Card ledger derivation failed for loop %s", loop_id, exc_info=True)
                return
            mutations = cards_to_mutations(cards) if cards else []
            await ledger.replace_with(mutations)
            self._last_derived_at[loop_id] = time.monotonic()
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                "Derived %d cards for loop %s in %d ms (source=checkpoint+log)",
                len(cards),
                loop_id,
                elapsed_ms,
            )

    async def _derive_cards(self, loop_id: str) -> list[MessageData]:
        """Read checkpoint + activity log and bind to cards via the SDK binder.

        Returns the same ``list[MessageData]`` the TUI's legacy
        ``_fetch_loop_history_data`` produces over the same inputs, so resume
        through the ledger renders identically to resume through the legacy
        path.
        """
        runner = getattr(self._daemon, "_runner", None)
        if runner is None:
            logger.debug("Runner unavailable; cannot derive cards for loop %s", loop_id)
            return []

        from soothe_daemon.runtime.loop_dispatcher import bind_execution_thread_for_loop

        try:
            checkpoint_thread_id = await bind_execution_thread_for_loop(self._daemon, loop_id)
        except Exception:
            logger.debug(
                "No checkpoint thread bound for loop %s; cannot derive cards",
                loop_id,
                exc_info=True,
            )
            return []

        # Checkpoint messages (primary source — canonical user / assistant /
        # tool message flow).
        try:
            state_values = await runner.get_thread_state_values(checkpoint_thread_id)
        except Exception:
            logger.warning("Failed to read checkpoint state for loop %s", loop_id, exc_info=True)
            state_values = {}

        messages = list(state_values.get("messages", []) or [])
        if messages and isinstance(messages[0], dict):
            try:
                messages = messages_from_wire_dicts(messages)
            except Exception:
                logger.debug(
                    "messages_from_wire_dicts failed for loop %s; using raw dicts",
                    loop_id,
                    exc_info=True,
                )

        # Activity log (secondary — cognition card replay + fallback for
        # checkpoint-less loops).
        try:
            raw_log = await runner.get_persisted_thread_messages(
                checkpoint_thread_id,
                limit=10000,
                include_events=True,
            )
        except Exception:
            logger.warning("Failed to read activity log for loop %s", loop_id, exc_info=True)
            raw_log = []

        log_events = [
            row
            for row in (self._normalize_log_row(r) for r in raw_log)
            if row.get("kind") in ("event", "tool_call", "tool_result", "conversation")
        ]

        cognition_replay: list[MessageData] = []
        if log_events:
            cognition_replay = await asyncio.to_thread(
                card_binder.collect_cognition_card_replay, log_events
            )

        if messages:
            cards = await asyncio.to_thread(
                card_binder.convert_messages_to_data,
                messages,
                cognition_card_replay=cognition_replay if cognition_replay else None,
            )
            return cards

        # No checkpoint messages — fall back to activity-log-only conversion.
        if log_events:
            return await asyncio.to_thread(card_binder.convert_loop_events_to_data, log_events)

        return []

    @staticmethod
    def _normalize_log_row(row: Any) -> dict[str, Any]:
        """Normalize a runner thread-log row into a plain dict.

        ``get_persisted_thread_messages`` returns pydantic models or dicts
        depending on the durability backend. The binder consumes plain dicts.
        """
        if isinstance(row, dict):
            return row
        dump = getattr(row, "model_dump", None)
        if callable(dump):
            try:
                d = dump(mode="json") if "mode" in dump.__code__.co_varnames else dump()
                if isinstance(d, dict):
                    return d
            except Exception:
                logger.debug("model_dump failed on activity-log row", exc_info=True)
        return {}

    # ------------------------------------------------------------------
    # Reattach replay
    # ------------------------------------------------------------------

    async def replay_to_client(
        self,
        loop_id: str,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> int:
        """Stream ``card.replay_begin`` → ``card.created`` × N → ``card.replay_end``.

        Args:
            loop_id: Loop whose ledger to replay.
            send_fn: Async callable used to deliver each frame to the client.

        Returns:
            Number of ``card.created`` frames sent.
        """
        ledger = await self.ensure_for_loop(loop_id)
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

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def last_derived_at(self, loop_id: str) -> float | None:
        """Return monotonic seconds of the last derivation, or ``None``."""
        return self._last_derived_at.get(loop_id)


__all__ = [
    "CARD_CREATED",
    "CARD_REPLAY_BEGIN",
    "CARD_REPLAY_END",
    "LoopCardManager",
]

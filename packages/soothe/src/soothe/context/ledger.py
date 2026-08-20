"""Ledger manager for the Context Engine (RFC-624)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage, SystemMessage

logger = logging.getLogger(__name__)


@dataclass
class _LedgerEntry:
    """Internal tagged ledger entry."""

    message: BaseMessage
    phase: str | None = None


@dataclass
class LedgerManager:
    """Manages the loop message ledger with phase tagging and compaction.

    Replaces ``LoopWorkingMemory`` and the ``loop_messages`` list from
    StrangeLoop state. Messages are tagged with phase metadata for filtered
    retrieval (e.g., execute_step-only projection for CoreAgent).
    """

    max_entries: int = 200
    compact_fn: Callable[[list[_LedgerEntry]], str | None] | None = None
    _entries: list[_LedgerEntry] = field(default_factory=list)
    _revision: int = field(default=0)

    def record_message(self, message: BaseMessage, phase: str) -> None:
        """Append a message to the ledger with phase metadata."""
        self._entries.append(_LedgerEntry(message=message, phase=phase))
        self._revision += 1
        if self.max_entries > 0 and len(self._entries) > self.max_entries:
            self.compact()

    @property
    def revision(self) -> int:
        """Monotonic revision counter; changes on every mutation."""
        return self._revision

    def get_messages(self, phases: list[str] | None = None) -> list[BaseMessage]:
        """Return messages, optionally filtered by phase."""
        if phases is None:
            return [e.message for e in self._entries]
        phase_set = set(phases)
        return [e.message for e in self._entries if e.phase in phase_set]

    def compact(self) -> None:
        """Compact old entries when count exceeds max_entries.

        If a compact_fn is provided, it receives the oldest entries and returns
        a summary string (or None to skip compaction). The summary replaces
        those entries as a single SystemMessage.

        If no compact_fn is set, entries beyond max_entries are dropped.
        """
        if self.max_entries <= 0:
            return
        if len(self._entries) <= self.max_entries:
            return

        excess = len(self._entries) - self.max_entries
        old_entries = self._entries[:excess]

        if self.compact_fn is not None:
            try:
                summary = self.compact_fn(old_entries)
            except Exception:
                logger.warning("Compaction function failed, dropping oldest entries", exc_info=True)
                self._entries = self._entries[excess:]
                self._revision += 1
                return
            if summary:
                self._entries = [
                    _LedgerEntry(message=SystemMessage(content=summary), phase="compacted"),
                    *self._entries[excess:],
                ]
                self._revision += 1
                return

        self._entries = self._entries[excess:]
        self._revision += 1

    def entries(self, phases: list[str] | None = None) -> list[tuple[BaseMessage, str | None]]:
        """Return (message, phase) tuples, optionally filtered by phase."""
        if phases is None:
            return [(e.message, e.phase) for e in self._entries]
        phase_set = set(phases)
        return [(e.message, e.phase) for e in self._entries if e.phase in phase_set]

    def clear(self) -> None:
        """Remove all entries."""
        self._entries.clear()
        self._revision += 1

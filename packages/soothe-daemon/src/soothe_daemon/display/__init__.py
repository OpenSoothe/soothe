"""Daemon-side display card infrastructure (RFC-413).

This package owns the per-loop card ledger that backs the TUI's resume flow:

* ``LoopCardLedger`` — SQLite-backed wrapper around
  ``soothe_sdk.display.InMemoryCardLedger``; persists to ``display.db``.
* ``LoopCardManager`` — per-loop lifecycle, real-time binding from stream
  tuples via ``soothe_sdk.display.card_binder``, and ``card.*`` replay-to-client.
"""

from __future__ import annotations

from soothe_daemon.display.loop_card_ledger import LoopCardLedger
from soothe_daemon.display.loop_card_manager import LoopCardManager

__all__ = [
    "LoopCardLedger",
    "LoopCardManager",
]

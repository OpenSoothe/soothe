"""Daemon-side display card infrastructure (RFC-413).

This package owns the per-loop card ledger that backs the TUI's resume flow:

* ``LoopCardLedger`` — durable wrapper around
  ``soothe_sdk.display.InMemoryCardLedger``; persists via
  ``get_display_card_store()`` (SQLite ``display.db`` or PostgreSQL
  ``soothe_metadata`` when ``persistence.default_backend: postgresql``).
* ``LoopCardManager`` — per-loop lifecycle, real-time binding from stream
  tuples via ``soothe_sdk.display.card_binder``, and ``card.*`` replay-to-client.

IG-535 Optimization 4: ``shutdown_card_bind_executor`` for daemon stop cleanup.
"""

from __future__ import annotations

from soothe_daemon.display.loop_card_ledger import LoopCardLedger
from soothe_daemon.display.loop_card_manager import (
    LoopCardManager,
    shutdown_card_bind_executor,
)

__all__ = [
    "LoopCardLedger",
    "LoopCardManager",
    "shutdown_card_bind_executor",
]

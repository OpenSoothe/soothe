"""Daemon-side display card infrastructure (RFC-413).

This package owns the per-loop card ledger that backs the TUI's resume flow:

* ``DisplayCardStore`` / ``PostgresDisplayCardStore`` — durable card mutation +
  goal snapshot persistence (SQLite ``display.db`` or PostgreSQL
  ``soothe_metadata`` when ``persistence.default_backend: postgresql``).
  Moved from ``soothe_nano`` (IG-635 PR-2); the store and its DDL are
  daemon-owned since display cards are a daemon concept.
* ``LoopCardLedger`` — durable wrapper around
  ``soothe_sdk.display.InMemoryCardLedger``; persists via
  ``get_display_card_store()``.
* ``LoopCardManager`` — per-loop lifecycle, real-time binding from stream
  tuples via ``soothe_sdk.display.card_binder``, and ``card.*`` replay-to-client.

IG-535 Optimization 4: ``shutdown_card_bind_executor`` for daemon stop cleanup.
"""

from __future__ import annotations

from soothe_daemon.display.display_store import (
    DisplayCardStore,
    DisplayCardStoreProtocol,
    configure_display_card_store,
    get_display_card_store,
    reset_display_card_store_for_tests,
)
from soothe_daemon.display.loop_card_ledger import LoopCardLedger
from soothe_daemon.display.loop_card_manager import (
    LoopCardManager,
    shutdown_card_bind_executor,
)

__all__ = [
    "DisplayCardStore",
    "DisplayCardStoreProtocol",
    "LoopCardLedger",
    "LoopCardManager",
    "configure_display_card_store",
    "get_display_card_store",
    "reset_display_card_store_for_tests",
    "shutdown_card_bind_executor",
]

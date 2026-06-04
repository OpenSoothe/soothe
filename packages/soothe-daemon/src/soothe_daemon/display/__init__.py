"""Daemon-side display card infrastructure (RFC-413).

This package owns the per-loop card ledger that backs the TUI's resume flow:

* ``LoopCardLedger`` — file-backed wrapper around
  ``soothe_sdk.display.InMemoryCardLedger``; appends to and loads from
  ``~/.soothe/data/loops/<loop_id>/cards.jsonl``.
* ``LoopCardManager`` — per-loop lifecycle, lazy derivation from the
  authoritative checkpoint + activity log via
  ``soothe_sdk.display.card_binder``, and ``card.*`` replay-to-client.

Live event delivery is unchanged by this package; the ledger powers the
resume / reattach replay path. Cards are derived lazily on RPC (and
re-derived when the checkpoint advances); real-time streaming binding
alongside live event delivery is left for a future iteration.
"""

from __future__ import annotations

from soothe_daemon.display.loop_card_ledger import LoopCardLedger
from soothe_daemon.display.loop_card_manager import LoopCardManager

__all__ = [
    "LoopCardLedger",
    "LoopCardManager",
]

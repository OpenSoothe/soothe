"""Compatibility re-export — implementation lives in ``soothe``.

Daemon and runner call sites should prefer
``soothe.foundation.context.goal_interrupt_persistence``.
"""

from __future__ import annotations

from soothe.foundation.context.goal_interrupt_persistence import (
    _build_cancelled_digest,
    _new_ledger_entry,
    mark_cancelled_goal_interrupted,
)

__all__ = [
    "mark_cancelled_goal_interrupted",
    "_build_cancelled_digest",
    "_new_ledger_entry",
]

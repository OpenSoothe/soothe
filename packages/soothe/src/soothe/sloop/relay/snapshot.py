"""LangGraph snapshot predicates for the relay.

`snapshot_has_resumable_interrupt` checks LangGraph's own interrupt mechanism
(the `interrupt()` call in `InteractiveClarificationPolicy`).
`snapshot_has_unanswered_pending` checks the relay inbox for an unanswered
head.
"""

from __future__ import annotations

from typing import Any


def snapshot_has_resumable_interrupt(snapshot: Any) -> bool:
    """True when `aget_state` still has a LangGraph interrupt to `Command(resume)`.

    Checks both top-level `interrupts` and per-task `task.interrupts`. This is
    about the StrangeLoop graph's own `interrupt()` suspension, not the
    relay's inbox state.
    """
    interrupts = getattr(snapshot, "interrupts", None) or ()
    if interrupts:
        return True
    tasks = getattr(snapshot, "tasks", None) or ()
    for task in tasks:
        task_interrupts = getattr(task, "interrupts", None) or ()
        if task_interrupts:
            return True
    return False


def snapshot_has_unanswered_pending(snapshot: Any) -> bool:
    """True when the relay inbox has a head entry with no answer built yet.

    Reads the `relay_state` graph channel: inbox non-empty and answer slot
    `None`.
    """
    values = getattr(snapshot, "values", {}) or {}
    relay_state = values.get("relay_state")
    if not isinstance(relay_state, dict):
        return False
    inbox = relay_state.get("inbox")
    if not isinstance(inbox, list) or not inbox:
        return False
    return relay_state.get("answer") is None


__all__ = [
    "snapshot_has_resumable_interrupt",
    "snapshot_has_unanswered_pending",
]

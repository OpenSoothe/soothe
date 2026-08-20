"""Sloop package — StrangeLoop single-goal orchestration.

StrangeLoop (alias: Sloop) executes single goals through iterative Plan-Execute
refinement:
- Plan: LLM reasoning with goal-directed evaluation
- Execute: Step execution via CoreAgent
- Judge: Progress assessment toward goal

Public API (root exports only):
    from soothe.sloop import StrangeLoop, Sloop

Import other types from subpackages, e.g.:
    from soothe.sloop.state.schemas import LoopState, PlanResult, StepAction
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "Sloop",
    "StrangeLoop",
]


def __getattr__(name: str) -> Any:
    """Lazy import root public symbols."""
    if name in ("StrangeLoop", "Sloop"):
        from soothe.sloop.strange_loop import StrangeLoop

        return StrangeLoop

    error_msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(error_msg)

"""Loop package - Layer 2 StrangeLoop orchestration.

StrangeLoop (alias: Sloop) executes single goals through iterative Plan-Execute refinement:
- Plan: LLM reasoning with goal-directed evaluation
- Execute: Step execution via CoreAgent
- Judge: Progress assessment toward goal

Import paths:
    from soothe.foundation.loop import StrangeLoop, Sloop
    from soothe.foundation.loop.state.schemas import LoopState, PlanResult, StepAction
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "Sloop",
    "StrangeLoop",
    "LoopState",
    "LoopWorkingMemory",
    "PlanResult",
    "StepAction",
    "StepResult",
]


def __getattr__(name: str) -> Any:
    """Lazy import loop modules."""
    if name in ("StrangeLoop", "Sloop"):
        from soothe.foundation.loop.engine.strange_loop import StrangeLoop

        return StrangeLoop
    if name == "LoopState":
        from soothe.foundation.loop.state.schemas import LoopState

        return LoopState
    if name == "LoopWorkingMemory":
        from soothe.foundation.loop.state.working_memory import LoopWorkingMemory

        return LoopWorkingMemory
    if name == "PlanResult":
        from soothe.foundation.loop.state.schemas import PlanResult

        return PlanResult
    if name == "StepAction":
        from soothe.foundation.loop.state.schemas import StepAction

        return StepAction
    if name == "StepResult":
        from soothe.foundation.loop.state.schemas import StepResult

        return StepResult

    error_msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(error_msg)

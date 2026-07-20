"""Soothe-native protocol definitions (StrangeLoop / runner / loop memory).

Shared CoreAgent contracts live in ``soothe_sdk.protocols``.
"""

from soothe.protocols.loop_planner import LoopPlannerProtocol
from soothe.protocols.loop_working_memory import LoopWorkingMemoryProtocol
from soothe.protocols.runner import LoopRunnerProtocol, LoopRunRequest

__all__ = [
    "LoopPlannerProtocol",
    "LoopRunRequest",
    "LoopRunnerProtocol",
    "LoopWorkingMemoryProtocol",
]

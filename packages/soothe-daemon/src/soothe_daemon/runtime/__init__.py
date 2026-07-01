"""Daemon-side asyncio runtime primitives (per-loop dispatch, thread state, GC)."""

from soothe_daemon.runtime.loop_broadcast_budget import LoopBroadcastBudget
from soothe_daemon.runtime.loop_dispatcher import (
    LoopInputDispatcher,
    bind_execution_thread_for_loop,
)
from soothe_daemon.runtime.thread_state import ThreadState, ThreadStateRegistry

# Wire-compat: interactive loops are always solo; autopilot jobs use daemon AutopilotService.
DEPRECATED_LOOP_AUTOPILOT_MODE = "solo"

__all__ = [
    "DEPRECATED_LOOP_AUTOPILOT_MODE",
    "LoopBroadcastBudget",
    "LoopInputDispatcher",
    "ThreadState",
    "ThreadStateRegistry",
    "bind_execution_thread_for_loop",
]

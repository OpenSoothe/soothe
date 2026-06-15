"""Daemon-side asyncio runtime primitives (per-loop dispatch, thread state, GC)."""

from soothe_daemon.runtime.loop_autopilot_mode import (
    ensure_loop_autopilot_mode,
    get_loop_autopilot_mode,
    set_loop_autopilot_mode,
)
from soothe_daemon.runtime.loop_dispatcher import (
    LoopInputDispatcher,
    bind_execution_thread_for_loop,
)
from soothe_daemon.runtime.thread_state import ThreadState, ThreadStateRegistry

__all__ = [
    "LoopInputDispatcher",
    "ThreadState",
    "ThreadStateRegistry",
    "bind_execution_thread_for_loop",
    "ensure_loop_autopilot_mode",
    "get_loop_autopilot_mode",
    "set_loop_autopilot_mode",
]

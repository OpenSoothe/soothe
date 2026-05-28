"""WorkerPool — sticky-affinity wrapper over LoopRunnerFactory (RFC-222 revised).

WorkerPool is the daemon-owned abstraction over RFC-221's per-loop_id
subprocess workers. It tracks which goal each worker is running, which
goals each worker has recently run (for sticky scheduling), and the idle
queue. The pool itself does not spawn processes — it asks the injected
``runner_factory`` for new ``LoopRunnerProtocol`` instances on demand.

Worker loop_ids are namespaced as ``autopilot__wNNN`` so the daemon's
client subscription router can filter them out — autopilot workers are
not user-facing sessions.

Phase A scaffolding: defines models and the pool API with unit tests.
No production code wires this yet; that happens in Phase B/C.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from soothe.core.goal_engine.models import Goal
    from soothe.protocols.runner import LoopRunnerProtocol

logger = logging.getLogger(__name__)

_WORKER_LOOP_ID_PREFIX = "autopilot__w"


class _RunnerFactoryProtocol(Protocol):
    """Subset of LoopRunnerFactory the pool actually uses."""

    def create_runner(self, loop_id: str) -> LoopRunnerProtocol: ...


@dataclass
class WorkerSlot:
    """One worker in the pool — wraps an RFC-221 LoopRunnerProtocol.

    Tracks:
        loop_id: namespaced (``autopilot__wNNN``) — opaque to clients.
        runner: the live LoopRunnerProtocol instance handling jobs.
        status: ``idle`` → ``active`` → ``idle`` (or ``error`` on failure).
        current_goal_id: id of the goal currently executing on this worker.
        last_goal_ids: recency list of recent goal_ids (sticky-affinity cache).
        active_task: the asyncio.Task draining the worker's stream; settable
            by AutopilotService so it can cancel cleanly.
        idle_since: when status last transitioned to ``idle``.
        created_at: spawn timestamp.
    """

    loop_id: str
    runner: LoopRunnerProtocol
    status: Literal["idle", "active", "error"] = "idle"
    current_goal_id: str | None = None
    last_goal_ids: list[str] = field(default_factory=list)
    active_task: Any = None  # asyncio.Task[Any] | None — Any avoids generic-in-dataclass headaches
    idle_since: datetime | None = field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # RFC-222 H5: wall-clock dispatch start, used by AutopilotService monitor
    # to detect deadline overruns. None whenever the worker is idle.
    dispatch_started_at: datetime | None = None

    # Recency cache bound — see RFC-222 §"WorkerPool". Larger than typical DAG
    # depth so the sticky lookup keeps working for long lineages.
    _LAST_GOALS_MAX = 16

    def assign(self, goal_id: str) -> None:
        """Mark this worker as actively running ``goal_id``."""
        self.status = "active"
        self.current_goal_id = goal_id
        self.idle_since = None
        self.dispatch_started_at = datetime.now(UTC)

    def release_to_idle(self, success: bool = True) -> None:
        """Move this worker back to idle (or error) after a goal completes."""
        if self.current_goal_id:
            self.last_goal_ids.append(self.current_goal_id)
            if len(self.last_goal_ids) > self._LAST_GOALS_MAX:
                self.last_goal_ids.pop(0)
        self.current_goal_id = None
        self.active_task = None
        self.dispatch_started_at = None
        self.status = "idle" if success else "error"
        self.idle_since = datetime.now(UTC) if success else None

    def has_recently_run(self, goal_id: str) -> bool:
        """True if ``goal_id`` is in this worker's recency cache."""
        return goal_id in self.last_goal_ids or goal_id == self.current_goal_id


class WorkerPool:
    """Sticky-affinity wrapper over LoopRunnerFactory (RFC-222 revised).

    Args:
        factory: source of ``LoopRunnerProtocol`` instances (typically RFC-221's
            ``LoopRunnerFactory``).
        max_loops: maximum concurrent worker slots in the pool.
    """

    def __init__(
        self,
        factory: _RunnerFactoryProtocol,
        max_loops: int,
    ) -> None:
        if max_loops < 1:
            msg = f"max_loops must be >= 1; got {max_loops}"
            raise ValueError(msg)
        self._factory = factory
        self._max_loops = max_loops
        self._workers: dict[str, WorkerSlot] = {}
        self._idle: deque[str] = deque()  # LRU of idle loop_ids
        self._next_seq = 0
        # All scheduling mutations serialized — fixes the race that a pure
        # asyncio model would otherwise leave between idle-pop and assign.
        self._assignment_lock = asyncio.Lock()

    # ---- capacity ------------------------------------------------------

    @property
    def max_loops(self) -> int:
        return self._max_loops

    def total_count(self) -> int:
        return len(self._workers)

    def idle_count(self) -> int:
        return sum(1 for w in self._workers.values() if w.status == "idle")

    def active_count(self) -> int:
        return sum(1 for w in self._workers.values() if w.status == "active")

    def has_capacity(self) -> bool:
        """True if the pool can dispatch one more goal right now."""
        return self.idle_count() > 0 or len(self._workers) < self._max_loops

    # ---- pick / release -----------------------------------------------

    async def pick_worker(
        self,
        goal: Goal,
        *,
        prefer: str | None = None,
    ) -> WorkerSlot | None:
        """Pick a worker for ``goal`` under the sticky-affinity rule.

        Preference order:
        1. The worker named in ``prefer`` if it is idle.
        2. Any idle worker whose ``last_goal_ids`` contains one of
           ``goal.depends_on`` (warm-cache lineage).
        3. Any idle worker (LRU).
        4. Spawn a new worker if under ``max_loops``.
        5. ``None`` (no capacity; caller defers).

        Args:
            goal: Goal about to be dispatched.
            prefer: Optional loop_id to prefer (e.g. from a recency cache
                outside the pool).

        Returns:
            A WorkerSlot marked active and assigned to ``goal.id``, or None.
        """
        async with self._assignment_lock:
            # 1. Explicit preference, if idle.
            if prefer and (w := self._workers.get(prefer)) and w.status == "idle":
                return self._claim(w, goal.id)

            # 2. Sticky: idle worker that recently ran any parent of ``goal``.
            for parent_id in goal.depends_on:
                for w in self._workers.values():
                    if w.status == "idle" and w.has_recently_run(parent_id):
                        return self._claim(w, goal.id)

            # 3. Any idle worker (LRU).
            while self._idle:
                loop_id = self._idle.popleft()
                w = self._workers.get(loop_id)
                if w and w.status == "idle":
                    return self._claim(w, goal.id)

            # 4. Spawn under cap.
            if len(self._workers) < self._max_loops:
                w = self._spawn()
                return self._claim(w, goal.id)

            # 5. No capacity.
            return None

    def _claim(self, w: WorkerSlot, goal_id: str) -> WorkerSlot:
        """Internal: mark a worker active. Caller must hold _assignment_lock."""
        w.assign(goal_id)
        # Remove from the idle queue if present.
        try:
            self._idle.remove(w.loop_id)
        except ValueError:
            pass
        logger.debug(
            "WorkerPool: claimed %s for goal %s (active=%d, idle=%d)",
            w.loop_id,
            goal_id,
            self.active_count(),
            self.idle_count(),
        )
        return w

    def _spawn(self) -> WorkerSlot:
        """Internal: create a new worker. Caller must hold _assignment_lock."""
        self._next_seq += 1
        loop_id = f"{_WORKER_LOOP_ID_PREFIX}{self._next_seq:03d}"
        runner = self._factory.create_runner(loop_id)
        w = WorkerSlot(loop_id=loop_id, runner=runner)
        self._workers[loop_id] = w
        logger.info(
            "WorkerPool: spawned worker %s (total=%d, cap=%d)",
            loop_id,
            len(self._workers),
            self._max_loops,
        )
        return w

    async def mark_idle(self, loop_id: str, *, success: bool = True) -> None:
        """Return a worker to the idle queue after its goal completes."""
        async with self._assignment_lock:
            w = self._workers.get(loop_id)
            if w is None:
                return
            w.release_to_idle(success=success)
            if success:
                self._idle.append(loop_id)

    async def release_worker(self, loop_id: str) -> WorkerSlot | None:
        """Remove a worker from the pool entirely (idle timeout / error)."""
        async with self._assignment_lock:
            w = self._workers.pop(loop_id, None)
            if w is None:
                return None
            try:
                self._idle.remove(loop_id)
            except ValueError:
                pass
            logger.info(
                "WorkerPool: released worker %s (remaining=%d)",
                loop_id,
                len(self._workers),
            )
            return w

    def get_worker(self, loop_id: str) -> WorkerSlot | None:
        return self._workers.get(loop_id)

    def workers(self) -> list[WorkerSlot]:
        """Snapshot of all workers — safe for read-only iteration."""
        return list(self._workers.values())

    def idle_workers(self) -> list[WorkerSlot]:
        return [w for w in self._workers.values() if w.status == "idle"]

    def active_workers(self) -> list[WorkerSlot]:
        return [w for w in self._workers.values() if w.status == "active"]


def is_autopilot_worker_loop_id(loop_id: str) -> bool:
    """True if ``loop_id`` belongs to an autopilot-owned worker.

    Daemon's WebSocket router uses this to filter autopilot workers out of
    client ``subscribe_loop`` requests — workers are not user sessions.
    """
    return loop_id.startswith(_WORKER_LOOP_ID_PREFIX)

"""WorkerPool — sticky-affinity wrapper over LoopRunnerFactory (RFC-222 / IG-677).

WorkerPool is the daemon-owned abstraction over RFC-221's per-loop_id
runners. Capacity is tracked by reusable **slots**; each goal assignment
gets a unique job-attributable ``loop_id``:

    autopilot__{job_id}__{uuid4().hex}

so ``data/loops/{loop_id}/`` never mixes jobs when a slot is reused.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from soothe.context.models import GoalNode
    from soothe.protocols.runner import LoopRunnerProtocol

logger = logging.getLogger(__name__)

_AUTOPILOT_LOOP_PREFIX = "autopilot__"
_SLOT_ID_PREFIX = "autopilot__slot_"


class _RunnerFactoryProtocol(Protocol):
    """Subset of LoopRunnerFactory the pool actually uses."""

    def create_runner(self, loop_id: str) -> LoopRunnerProtocol: ...


def allocate_assignment_loop_id(job_id: str) -> str:
    """Allocate a unique, job-attributable assignment loop id."""
    clean = (job_id or "").strip()
    if not clean:
        msg = "job_id is required to allocate an autopilot loop id"
        raise ValueError(msg)
    return f"{_AUTOPILOT_LOOP_PREFIX}{clean}__{uuid.uuid4().hex}"


def parse_job_id_from_loop_id(loop_id: str) -> str | None:
    """Extract ``job_id`` from ``autopilot__{job_id}__{uuid}``; else None."""
    if not loop_id.startswith(_AUTOPILOT_LOOP_PREFIX):
        return None
    rest = loop_id[len(_AUTOPILOT_LOOP_PREFIX) :]
    if "__" not in rest:
        return None
    job_id, _suffix = rest.split("__", 1)
    return job_id or None


@dataclass
class WorkerSlot:
    """One capacity slot in the pool.

    Tracks:
        slot_id: stable pool key (``autopilot__slot_NNN``).
        loop_id: current (or last) assignment loop id under ``data/loops/``.
        runner: LoopRunnerProtocol bound to the current ``loop_id``.
        status: ``idle`` → ``active`` → ``idle``.
        current_goal_id: id of the goal currently executing on this slot.
        last_goal_ids: recency list of recent goal_ids (sticky-affinity cache).
        last_dispatch_ok: whether the previous assignment completed cleanly.
    """

    slot_id: str
    runner: LoopRunnerProtocol
    loop_id: str
    status: Literal["idle", "active"] = "idle"
    current_goal_id: str | None = None
    last_goal_ids: list[str] = field(default_factory=list)
    active_task: Any = None
    idle_since: datetime | None = field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    dispatch_started_at: datetime | None = None
    last_dispatch_ok: bool = True

    _LAST_GOALS_MAX = 16

    def assign(self, goal_id: str, *, loop_id: str, runner: LoopRunnerProtocol) -> None:
        """Bind this slot to a new assignment."""
        self.status = "active"
        self.current_goal_id = goal_id
        self.loop_id = loop_id
        self.runner = runner
        self.idle_since = None
        self.dispatch_started_at = datetime.now(UTC)

    def release_to_idle(self, success: bool = True) -> None:
        """Return this slot to idle after a goal finishes (success or failure).

        Failed dispatches must not permanently remove capacity (IG-678 P0-4).
        ``last_dispatch_ok`` records outcome for observability only.
        """
        if self.current_goal_id:
            self.last_goal_ids.append(self.current_goal_id)
            if len(self.last_goal_ids) > self._LAST_GOALS_MAX:
                self.last_goal_ids.pop(0)
        self.current_goal_id = None
        self.active_task = None
        self.dispatch_started_at = None
        self.last_dispatch_ok = success
        self.status = "idle"
        self.idle_since = datetime.now(UTC)

    def has_recently_run(self, goal_id: str) -> bool:
        """True if ``goal_id`` is in this slot's recency cache."""
        return goal_id in self.last_goal_ids or goal_id == self.current_goal_id


class WorkerPool:
    """Sticky-affinity wrapper over LoopRunnerFactory (RFC-222 / IG-677).

    Args:
        factory: source of ``LoopRunnerProtocol`` instances.
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
        self._workers: dict[str, WorkerSlot] = {}  # slot_id → slot
        self._by_loop_id: dict[str, str] = {}  # loop_id → slot_id
        self._idle: deque[str] = deque()  # LRU of idle slot_ids
        self._next_seq = 0
        self._assignment_lock = asyncio.Lock()

    @property
    def max_loops(self) -> int:
        return self._max_loops

    def total_count(self) -> int:
        return len(self._workers)

    def idle_count(self) -> int:
        return sum(1 for w in self._workers.values() if w.status == "idle")

    def active_count(self) -> int:
        return sum(1 for w in self._workers.values() if w.status == "active")

    async def pick_worker(
        self,
        goal: GoalNode,
        *,
        job_id: str,
        prefer: str | None = None,
    ) -> WorkerSlot | None:
        """Pick a slot for ``goal`` and bind a fresh assignment ``loop_id``.

        Preference order (by slot):
        1. Slot matching ``prefer`` (slot_id or current/last loop_id) if idle.
        2. Idle slot whose ``last_goal_ids`` contains a ``goal.depends_on`` id.
        3. Any idle slot (LRU).
        4. Spawn a new slot if under ``max_loops``.
        5. ``None`` (no capacity).
        """
        async with self._assignment_lock:
            prefer_slot = self._resolve_slot_id(prefer) if prefer else None

            if prefer_slot and (w := self._workers.get(prefer_slot)) and w.status == "idle":
                return self._claim(w, goal.id, job_id)

            for parent_id in goal.depends_on:
                for w in self._workers.values():
                    if w.status == "idle" and w.has_recently_run(parent_id):
                        return self._claim(w, goal.id, job_id)

            while self._idle:
                slot_id = self._idle.popleft()
                w = self._workers.get(slot_id)
                if w and w.status == "idle":
                    return self._claim(w, goal.id, job_id)

            if len(self._workers) < self._max_loops:
                return self._spawn_and_claim(goal.id, job_id)

            return None

    def _resolve_slot_id(self, prefer: str) -> str | None:
        if prefer in self._workers:
            return prefer
        return self._by_loop_id.get(prefer)

    def _claim(self, w: WorkerSlot, goal_id: str, job_id: str) -> WorkerSlot:
        """Bind slot to a new assignment loop_id. Caller holds lock."""
        loop_id = allocate_assignment_loop_id(job_id)
        if w.loop_id and self._by_loop_id.get(w.loop_id) == w.slot_id:
            del self._by_loop_id[w.loop_id]
        runner = self._factory.create_runner(loop_id)
        w.assign(goal_id, loop_id=loop_id, runner=runner)
        self._by_loop_id[loop_id] = w.slot_id
        try:
            self._idle.remove(w.slot_id)
        except ValueError:
            pass
        logger.debug(
            "WorkerPool: claimed slot %s as %s for goal %s (active=%d, idle=%d)",
            w.slot_id,
            loop_id,
            goal_id,
            self.active_count(),
            self.idle_count(),
        )
        return w

    def _spawn_and_claim(self, goal_id: str, job_id: str) -> WorkerSlot:
        """Create a new slot and immediately bind an assignment loop_id."""
        self._next_seq += 1
        slot_id = f"{_SLOT_ID_PREFIX}{self._next_seq:03d}"
        loop_id = allocate_assignment_loop_id(job_id)
        runner = self._factory.create_runner(loop_id)
        w = WorkerSlot(slot_id=slot_id, runner=runner, loop_id=loop_id)
        w.assign(goal_id, loop_id=loop_id, runner=runner)
        self._workers[slot_id] = w
        self._by_loop_id[loop_id] = slot_id
        logger.info(
            "WorkerPool: spawned slot %s as %s (total=%d, cap=%d)",
            slot_id,
            loop_id,
            len(self._workers),
            self._max_loops,
        )
        return w

    async def mark_idle(self, loop_id: str, *, success: bool = True) -> None:
        """Return the slot owning ``loop_id`` to the idle queue.

        Always requeues the slot so failed goals do not leak pool capacity.
        """
        async with self._assignment_lock:
            w = self._get_by_loop_id_unlocked(loop_id)
            if w is None:
                return
            w.release_to_idle(success=success)
            if w.slot_id not in self._idle:
                self._idle.append(w.slot_id)

    async def release_worker(self, loop_id: str) -> WorkerSlot | None:
        """Remove the slot owning ``loop_id`` from the pool entirely."""
        async with self._assignment_lock:
            w = self._get_by_loop_id_unlocked(loop_id)
            if w is None:
                return None
            self._workers.pop(w.slot_id, None)
            # Drop all reverse entries pointing at this slot.
            stale = [lid for lid, sid in self._by_loop_id.items() if sid == w.slot_id]
            for lid in stale:
                del self._by_loop_id[lid]
            try:
                self._idle.remove(w.slot_id)
            except ValueError:
                pass
            logger.info(
                "WorkerPool: released slot %s (loop %s, remaining=%d)",
                w.slot_id,
                loop_id,
                len(self._workers),
            )
            return w

    def get_worker(self, loop_id: str) -> WorkerSlot | None:
        return self._get_by_loop_id_unlocked(loop_id)

    def _get_by_loop_id_unlocked(self, loop_id: str) -> WorkerSlot | None:
        slot_id = self._by_loop_id.get(loop_id)
        if slot_id is not None:
            return self._workers.get(slot_id)
        for w in self._workers.values():
            if w.loop_id == loop_id:
                return w
        return None

    def workers(self) -> list[WorkerSlot]:
        return list(self._workers.values())

    def idle_workers(self) -> list[WorkerSlot]:
        return [w for w in self._workers.values() if w.status == "idle"]

    def active_workers(self) -> list[WorkerSlot]:
        return [w for w in self._workers.values() if w.status == "active"]


def is_autopilot_worker_loop_id(loop_id: str) -> bool:
    """True if ``loop_id`` belongs to an autopilot-owned worker.

    Matches assignment-scoped ids (``autopilot__{job}__{uuid}``), pool slot
    placeholders (``autopilot__slot_*``), and legacy ``autopilot__wNNN``.
    """
    return loop_id.startswith(_AUTOPILOT_LOOP_PREFIX)

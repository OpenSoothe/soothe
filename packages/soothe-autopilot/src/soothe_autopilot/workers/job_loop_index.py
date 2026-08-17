"""Durable job ↔ loop membership index (IG-677).

A job is the root GoalNode id. Each StrangeLoop assignment gets a unique
``loop_id`` under ``data/loops/{loop_id}/``. This module persists membership
and history so autopilot can map ``job_id → loops`` across restarts.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from soothe_sdk.protocols.persistence import AsyncPersistStore

logger = logging.getLogger(__name__)

_JOB_LOOPS_PREFIX = "autopilot:job_loops:"
_LOOP_OWNER_PREFIX = "autopilot:loop_owner:"

LoopEntryStatus = Literal[
    "active",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
]


class JobLoopEntry(BaseModel):
    """One assignment of a goal to a loop under a job."""

    seq: int
    loop_id: str
    goal_id: str
    attempt: int = 1
    status: LoopEntryStatus = "active"
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None


class JobLoopRecord(BaseModel):
    """Durable membership record for one autopilot job."""

    job_id: str
    status: Literal["running", "paused", "completed", "cancelled", "failed"] = "running"
    next_seq: int = 1
    active_loops: list[str] = Field(default_factory=list)
    loops: list[JobLoopEntry] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class JobLoopIndex:
    """Persist job↔loop membership via ``AsyncPersistStore``.

    When ``store`` is None, keeps an in-memory map (tests / no durability).
    """

    def __init__(self, store: AsyncPersistStore | None = None) -> None:
        self._store = store
        self._memory: dict[str, JobLoopRecord] = {}

    @staticmethod
    def _job_key(job_id: str) -> str:
        return f"{_JOB_LOOPS_PREFIX}{job_id}"

    @staticmethod
    def _owner_key(loop_id: str) -> str:
        return f"{_LOOP_OWNER_PREFIX}{loop_id}"

    async def ensure_job(self, job_id: str) -> JobLoopRecord:
        """Create an empty running record if missing."""
        existing = await self.get_job(job_id)
        if existing is not None:
            return existing
        record = JobLoopRecord(job_id=job_id)
        await self._save_job(record)
        return record

    async def get_job(self, job_id: str) -> JobLoopRecord | None:
        if self._store is None:
            return self._memory.get(job_id)
        raw = await self._store.load(self._job_key(job_id))
        if not isinstance(raw, dict):
            return None
        try:
            return JobLoopRecord.model_validate(raw)
        except Exception:
            logger.debug("Invalid JobLoopRecord for job %s", job_id, exc_info=True)
            return None

    async def list_loops(self, job_id: str) -> list[JobLoopEntry]:
        record = await self.get_job(job_id)
        if record is None:
            return []
        return list(record.loops)

    async def owner_of(self, loop_id: str) -> str | None:
        if self._store is None:
            for job_id, record in self._memory.items():
                if any(e.loop_id == loop_id for e in record.loops):
                    return job_id
            return None
        raw = await self._store.load(self._owner_key(loop_id))
        if isinstance(raw, dict):
            job_id = raw.get("job_id")
            return job_id if isinstance(job_id, str) else None
        if isinstance(raw, str):
            return raw
        return None

    async def record_start(
        self,
        job_id: str,
        *,
        loop_id: str,
        goal_id: str,
        attempt: int = 1,
    ) -> JobLoopEntry:
        """Append an active loop entry and reverse-owner mapping."""
        record = await self.ensure_job(job_id)
        entry = JobLoopEntry(
            seq=record.next_seq,
            loop_id=loop_id,
            goal_id=goal_id,
            attempt=attempt,
            status="active",
        )
        record.next_seq += 1
        record.loops.append(entry)
        if loop_id not in record.active_loops:
            record.active_loops.append(loop_id)
        record.status = "running"
        record.updated_at = datetime.now(UTC)
        await self._save_job(record)
        await self._save_owner(loop_id, job_id)
        return entry

    async def record_end(
        self,
        loop_id: str,
        *,
        status: LoopEntryStatus,
        job_id: str | None = None,
    ) -> JobLoopEntry | None:
        """Mark a loop entry terminal and drop it from active_loops."""
        resolved_job = job_id or await self.owner_of(loop_id)
        if resolved_job is None:
            logger.debug("No job owner for loop %s; skip record_end", loop_id)
            return None
        record = await self.get_job(resolved_job)
        if record is None:
            return None
        entry: JobLoopEntry | None = None
        for candidate in reversed(record.loops):
            if candidate.loop_id == loop_id and candidate.status == "active":
                entry = candidate
                break
        if entry is None:
            for candidate in reversed(record.loops):
                if candidate.loop_id == loop_id:
                    entry = candidate
                    break
        if entry is None:
            return None
        entry.status = status
        entry.ended_at = datetime.now(UTC)
        if loop_id in record.active_loops:
            record.active_loops = [lid for lid in record.active_loops if lid != loop_id]
        record.updated_at = datetime.now(UTC)
        await self._save_job(record)
        return entry

    async def mark_job_status(
        self,
        job_id: str,
        status: Literal["running", "paused", "completed", "cancelled", "failed"],
    ) -> None:
        record = await self.ensure_job(job_id)
        record.status = status
        record.updated_at = datetime.now(UTC)
        await self._save_job(record)

    async def interrupt_active_loops(self) -> list[str]:
        """On daemon restore: mark every active entry interrupted.

        Returns:
            List of loop_ids that were interrupted.
        """
        interrupted: list[str] = []
        for job_id in await self._all_job_ids():
            record = await self.get_job(job_id)
            if record is None or not record.active_loops:
                continue
            for loop_id in list(record.active_loops):
                ended = await self.record_end(loop_id, status="interrupted", job_id=job_id)
                if ended is not None:
                    interrupted.append(loop_id)
        return interrupted

    async def snapshot_for_job(self, job_id: str) -> dict[str, Any] | None:
        record = await self.get_job(job_id)
        if record is None:
            return None
        return record.model_dump(mode="json")

    async def _all_job_ids(self) -> list[str]:
        if self._store is None:
            return list(self._memory.keys())
        keys = await self._store.list_keys()
        prefix_len = len(_JOB_LOOPS_PREFIX)
        return [k[prefix_len:] for k in keys if k.startswith(_JOB_LOOPS_PREFIX)]

    async def _save_job(self, record: JobLoopRecord) -> None:
        payload = record.model_dump(mode="json")
        if self._store is None:
            self._memory[record.job_id] = record.model_copy(deep=True)
            return
        await self._store.save(self._job_key(record.job_id), payload)

    async def _save_owner(self, loop_id: str, job_id: str) -> None:
        if self._store is None:
            return
        await self._store.save(self._owner_key(loop_id), {"job_id": job_id})

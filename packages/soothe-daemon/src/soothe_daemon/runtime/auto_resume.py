"""Daemon auto-resume of interrupted StrangeLoop goals (IG-670).

Classifies incomplete ``status=running`` loops after a daemon restart and,
when ``agent.loop.checkpoint.auto_resume_on_start`` is enabled, re-enters
StrangeLoop on the same ``loop_id`` via ``resume_interrupted`` admission so
``recovery_valid_resume`` reuses existing threads, CE state, and checkpoints.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from soothe.autopilot.worker_pool import is_autopilot_worker_loop_id

logger = logging.getLogger(__name__)

# Structural admission text when no resume_topic is available. Multi-word phrase
# is a loop-control signal (Pass 1 bypass) without bare continue-keyword cancel.
_DEFAULT_RESUME_PROMPT = "continue this loop"


class AutoResumeDecision(StrEnum):
    """Outcome of classifying one incomplete loop."""

    RESUME = "resume"
    SKIP = "skip"
    CANCEL = "cancel"


@dataclass(frozen=True)
class AutoResumeClassification:
    """Classification result for one incomplete loop."""

    loop_id: str
    decision: AutoResumeDecision
    reason: str
    resume_prompt: str = _DEFAULT_RESUME_PROMPT


def _parse_updated_at(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        normalized = re.sub(r"Z$", "+00:00", raw.strip())
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _age_hours(updated_at: datetime | None, *, now: datetime) -> float | None:
    if updated_at is None:
        return None
    return max(0.0, (now - updated_at).total_seconds() / 3600.0)


def checkpoint_supports_valid_resume(checkpoint: Any | None) -> bool:
    """True when StrangeLoop would set ``recovery_valid_resume``."""
    if checkpoint is None:
        return False
    if getattr(checkpoint, "status", None) != "running":
        return False
    idx = getattr(checkpoint, "current_goal_index", -1)
    history = getattr(checkpoint, "goal_history", None) or []
    return isinstance(idx, int) and 0 <= idx < len(history)


def classify_incomplete_loop(
    *,
    loop_id: str,
    updated_at_raw: Any,
    checkpoint: Any | None,
    active_runner: bool,
    autopilot_owned: bool | None = None,
    clarification_pending: bool | None = None,
    clarifications_policy: Literal["skip", "reannounce"] = "skip",
    auto_cancel: bool = True,
    cancel_max_age_hours: float = 24.0,
    resume_max_age_hours: float = 24.0,
    resume_topic: str | None = None,
    now: datetime | None = None,
) -> AutoResumeClassification:
    """Classify one incomplete loop for cancel / skip / resume.

    Cancel-by-age wins over resume. Autopilot worker loops are always skipped.
    Clarification-parked loops honor ``clarifications_policy``.
    """
    lid = str(loop_id or "").strip()
    if not lid:
        return AutoResumeClassification("", AutoResumeDecision.SKIP, "empty_loop_id")

    owned = (
        bool(autopilot_owned) if autopilot_owned is not None else is_autopilot_worker_loop_id(lid)
    )
    if owned:
        return AutoResumeClassification(lid, AutoResumeDecision.SKIP, "autopilot_owned")

    if active_runner:
        return AutoResumeClassification(lid, AutoResumeDecision.SKIP, "active_runner")

    now_utc = now or datetime.now(UTC)
    updated_at = _parse_updated_at(updated_at_raw)
    age = _age_hours(updated_at, now=now_utc)

    if auto_cancel and age is not None and age > float(cancel_max_age_hours):
        return AutoResumeClassification(lid, AutoResumeDecision.CANCEL, f"age_hours={age:.1f}")

    if age is not None and age > float(resume_max_age_hours):
        return AutoResumeClassification(lid, AutoResumeDecision.SKIP, f"resume_age_hours={age:.1f}")

    if not checkpoint_supports_valid_resume(checkpoint):
        return AutoResumeClassification(lid, AutoResumeDecision.SKIP, "checkpoint_not_resumable")

    if clarification_pending and clarifications_policy == "skip":
        return AutoResumeClassification(lid, AutoResumeDecision.SKIP, "clarification_pending")

    prompt = (resume_topic or "").strip() or _DEFAULT_RESUME_PROMPT
    reason = "eligible"
    if clarification_pending and clarifications_policy == "reannounce":
        reason = "clarification_reannounce"
    return AutoResumeClassification(lid, AutoResumeDecision.RESUME, reason, resume_prompt=prompt)


async def peek_strange_loop_checkpoint(daemon: Any, loop_id: str) -> Any | None:
    """Load StrangeLoop checkpoint for eligibility (best-effort)."""
    from soothe.sloop.state.sloop_manager import StrangeLoopStateManager

    sm: StrangeLoopStateManager | None = None
    try:
        shared_pool = None
        try:
            from soothe.sloop.checkpoints.shared_pool import SharedPostgreSQLPool

            get_shared = getattr(SharedPostgreSQLPool, "get_shared_instance", None)
            if callable(get_shared):
                shared_pool = await get_shared(daemon._config)
        except Exception:
            shared_pool = None
        sm = StrangeLoopStateManager(loop_id, config=daemon._config, shared_pool=shared_pool)
        return await sm.load()
    except Exception:
        logger.debug("auto_resume checkpoint peek failed loop=%s", loop_id, exc_info=True)
        return None
    finally:
        if sm is not None:
            close = getattr(sm, "close", None)
            if callable(close):
                try:
                    await sm.close()
                except Exception:
                    logger.debug(
                        "auto_resume checkpoint manager close failed loop=%s",
                        loop_id,
                        exc_info=True,
                    )


async def peek_clarification_pending(_daemon: Any, _loop_id: str) -> bool | None:
    """Best-effort clarification pending probe.

    Returns ``None`` when the StrangeLoop graph checkpoint cannot be inspected
    cheaply at startup. Callers treat ``None`` as not pending so mid-execute
    recovery is not blocked; parked clarifications that are resumed re-emit at
    ``await_clarification``.
    """
    return None


def _loop_has_active_runner(daemon: Any, loop_id: str) -> bool:
    if loop_id in getattr(daemon, "_active_stream_loop_ids", set()):
        return True
    if loop_id in getattr(daemon, "_loops_with_active_query", set()):
        return True
    qe = getattr(daemon, "_query_engine", None)
    if qe is not None:
        runners = getattr(qe, "_active_runners", {}) or {}
        if loop_id in runners:
            return True
        starting = getattr(qe, "_loops_turn_starting", set()) or set()
        if loop_id in starting:
            return True
    return False


async def recover_incomplete_loops(daemon: Any) -> list[AutoResumeClassification]:
    """Classify incomplete loops; optionally enqueue auto-resume (IG-670).

    Always runs cancel-by-age classification; resumes only when
    ``auto_resume_on_start`` is true.
    """
    from soothe_daemon.bootstrap.logging import set_loop_id

    cp_cfg = daemon._config.agent.loop.checkpoint
    auto_resume = bool(getattr(cp_cfg, "auto_resume_on_start", False))
    max_loops = int(getattr(cp_cfg, "auto_resume_max_loops", 16) or 16)
    resume_max_age = float(getattr(cp_cfg, "auto_resume_max_age_hours", 24.0) or 24.0)
    clar_policy: Literal["skip", "reannounce"] = getattr(
        cp_cfg, "auto_resume_clarifications", "skip"
    )
    if clar_policy not in ("skip", "reannounce"):
        clar_policy = "skip"

    auto_cancel = bool(getattr(daemon._daemon_config, "auto_cancel_on_startup", True))
    cancel_max_age = float(getattr(daemon._daemon_config, "thread_max_age_hours", 24) or 24)

    protected: set[str] = getattr(daemon, "_auto_resume_protected_loop_ids", None) or set()
    daemon._auto_resume_protected_loop_ids = protected

    try:
        rows = await daemon._persistence_manager.list_loops(status_filter="running")
    except Exception:
        logger.debug("Incomplete loop list failed", exc_info=True)
        return []

    results: list[AutoResumeClassification] = []
    resume_queue: list[AutoResumeClassification] = []
    now = datetime.now(UTC)

    for row in rows:
        if not isinstance(row, dict):
            continue
        loop_id = str(row.get("loop_id") or "").strip()
        if not loop_id:
            continue

        set_loop_id(loop_id)
        checkpoint = await peek_strange_loop_checkpoint(daemon, loop_id)
        clar_pending = await peek_clarification_pending(daemon, loop_id)
        classification = classify_incomplete_loop(
            loop_id=loop_id,
            updated_at_raw=row.get("updated_at"),
            checkpoint=checkpoint,
            active_runner=_loop_has_active_runner(daemon, loop_id),
            autopilot_owned=is_autopilot_worker_loop_id(loop_id),
            clarification_pending=bool(clar_pending) if clar_pending is not None else False,
            clarifications_policy=clar_policy,
            auto_cancel=auto_cancel,
            cancel_max_age_hours=cancel_max_age,
            resume_max_age_hours=resume_max_age,
            resume_topic=str(row.get("resume_topic") or "").strip() or None,
            now=now,
        )
        results.append(classification)
        logger.info(
            "auto_resume loop=%s decision=%s reason=%s",
            loop_id,
            classification.decision.value,
            classification.reason,
        )

        if classification.decision == AutoResumeDecision.CANCEL:
            try:
                await daemon._persistence_manager.update_loop_metadata(loop_id, status="cancelled")
            except Exception:
                logger.warning("Failed to cancel aged loop %s", loop_id, exc_info=True)
            continue

        if classification.decision == AutoResumeDecision.RESUME:
            resume_queue.append(classification)

    if not resume_queue:
        if results:
            logger.info(
                "Found %d incomplete loop(s); none queued for auto-resume "
                "(auto_resume_on_start=%s)",
                len(results),
                auto_resume,
            )
        else:
            logger.debug("No incomplete loops found from previous runs")
        return results

    if not auto_resume:
        logger.info(
            "Found %d incomplete loop(s) eligible for resume; "
            "auto_resume_on_start=false (manual continue required)",
            len(resume_queue),
        )
        return results

    to_resume = resume_queue[: max(1, max_loops)]
    if len(resume_queue) > len(to_resume):
        logger.warning(
            "auto_resume capped at %d of %d eligible loop(s)",
            len(to_resume),
            len(resume_queue),
        )

    for item in to_resume:
        protected.add(item.loop_id)
        try:
            hb = getattr(daemon._persistence_manager, "heartbeat_loop", None)
            if callable(hb):
                await hb(item.loop_id)
        except Exception:
            logger.debug("auto_resume heartbeat failed loop=%s", item.loop_id, exc_info=True)

        await daemon._loop_input_dispatcher.enqueue(
            item.loop_id,
            {
                "type": "input",
                "text": item.resume_prompt,
                "client_id": None,
                "autonomous": False,
                "resume_interrupted": True,
            },
        )
        logger.info(
            "auto_resume enqueued loop=%s prompt_chars=%d",
            item.loop_id,
            len(item.resume_prompt),
        )

    async def _release_protection() -> None:
        recon = getattr(daemon._daemon_config, "loop_status_reconciliation", None)
        stale = float(getattr(recon, "stale_running_seconds", 180) or 180)
        await asyncio.sleep(max(5.0, stale / 6.0))
        for item in to_resume:
            protected.discard(item.loop_id)

    daemon._auto_resume_release_task = asyncio.create_task(_release_protection())
    return results


__all__ = [
    "AutoResumeClassification",
    "AutoResumeDecision",
    "checkpoint_supports_valid_resume",
    "classify_incomplete_loop",
    "peek_clarification_pending",
    "peek_strange_loop_checkpoint",
    "recover_incomplete_loops",
]

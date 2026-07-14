"""Write ``goal_interrupted`` CE ledger markers for cancelled in-flight goals.

When a user submits a new goal (or cancels) while one is in flight, callers
outside the StrangeLoop graph often have only ``loop_id`` — not a
``LoopRuntimeContext``. This module loads the CE ledger, appends a
``phase="goal_interrupted"`` Human+AI pair whose AI body is a compact
deterministic digest of the cancelled goal's partial ``execute_step`` work,
and persists both. Goal DAG status remains the caller's responsibility.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_MAX_EXCERPT_CHARS = 240
_MAX_EVIDENCE_EXCERPTS = 3
_MAX_DIGEST_CHARS = 1200
_INTERRUPTED_LEDGER_HUMAN_BASE = "Goal interrupted before completion. Partial-work digest follows."


def _is_ai_row(entry: dict[str, Any]) -> bool:
    t = str(entry.get("type") or entry.get("_type") or "").strip().lower()
    return t in ("ai", "aimessage", "loopaimessage")


def _entry_phase(entry: dict[str, Any]) -> str:
    md = entry.get("additional_kwargs") or {}
    if isinstance(md, dict):
        p = md.get("phase")
        if isinstance(p, str):
            return p
    p = entry.get("phase")
    return p if isinstance(p, str) else ""


def _entry_content_text(entry: dict[str, Any]) -> str:
    content = entry.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return ""


def _build_cancelled_digest(ledger: list[dict[str, Any]], *, reason: str) -> str:
    """Build the ``goal_interrupted`` AI body from the persisted ledger.

    Walks the ledger backward collecting ``execute_step`` AI excerpts (the
    user-facing synthesis of each wave), deduped by a 64-char prefix. Returns
    empty string when there is no usable execute evidence — callers treat that
    as "no marker".
    """
    excerpts: list[str] = []
    seen_prefixes: set[str] = set()
    for entry in reversed(ledger):
        if len(excerpts) >= _MAX_EVIDENCE_EXCERPTS:
            break
        if _entry_phase(entry) != "execute_step":
            continue
        if not _is_ai_row(entry):
            continue
        text = _entry_content_text(entry).strip()
        if not text:
            continue
        prefix = text[:64]
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        excerpts.append(text[:_MAX_EXCERPT_CHARS])
    if not excerpts:
        return ""
    excerpts.reverse()
    parts = [
        f"Goal interrupted ({reason}).",
        "Evidence produced (oldest first):\n" + "\n\n".join(excerpts),
        "Remaining: the new request should resume from the last completed step; "
        "do not redo work whose evidence appears above.",
    ]
    digest = "\n\n".join(parts)
    if len(digest) > _MAX_DIGEST_CHARS:
        digest = digest[: _MAX_DIGEST_CHARS - 1].rstrip() + "…"
    return digest


def _new_ledger_entry(
    *,
    role: str,
    content: str,
    phase: str,
    thread_id: str | None,
    iteration: int | None,
) -> dict[str, Any]:
    """Build a minimal serialized ledger entry mirroring CE persistence shape."""
    return {
        "type": "ai" if role == "ai" else "human",
        "content": content,
        "additional_kwargs": {"phase": phase},
        "metadata": {
            "thread_id": thread_id,
            "iteration": iteration,
            "phase": phase,
        },
    }


async def mark_cancelled_goal_interrupted(
    config: Any,
    loop_id: str,
    *,
    reason: str = "user_cancelled",
) -> int:
    """Append a ``goal_interrupted`` ledger pair for the in-flight cancelled goal.

    Returns the number of ledger entries appended (0 when no partial execute
    work exists, or on best-effort failure). Failures are logged and swallowed
    so a marker-write error never blocks the cancel path.
    """
    lid = str(loop_id or "").strip()
    if not lid:
        return 0
    try:
        from soothe.foundation.context.persistence.factory import (
            resolve_context_engine_persistence,
        )

        persistence = resolve_context_engine_persistence(config, lid)
        try:
            ledger = await persistence.load_ledger()
            digest = _build_cancelled_digest(ledger or [], reason=reason)
            if not digest:
                logger.debug(
                    "goal_interrupted marker skipped (no execute evidence) loop=%s",
                    lid[:16],
                )
                return 0
            # Best-effort thread_id / iteration from the last execute_step row.
            thread_id = None
            iteration = None
            for entry in reversed(ledger or []):
                if _entry_phase(entry) == "execute_step":
                    md = entry.get("metadata") or {}
                    if isinstance(md, dict):
                        tid = md.get("thread_id")
                        if isinstance(tid, str):
                            thread_id = tid
                        it = md.get("iteration")
                        if isinstance(it, int):
                            iteration = it
                    break
            human_entry = _new_ledger_entry(
                role="human",
                content=_INTERRUPTED_LEDGER_HUMAN_BASE,
                phase="goal_interrupted",
                thread_id=thread_id,
                iteration=iteration,
            )
            ai_entry = _new_ledger_entry(
                role="ai",
                content=digest,
                phase="goal_interrupted",
                thread_id=thread_id,
                iteration=iteration,
            )
            ledger = list(ledger or [])
            ledger.extend([human_entry, ai_entry])
            await persistence.save_ledger(ledger)
            logger.info(
                "goal_interrupted marker written loop=%s reason=%s digest_chars=%d",
                lid[:16],
                reason,
                len(digest),
            )
            return 2
        finally:
            close = getattr(persistence, "close", None)
            if callable(close):
                maybe_coro = close()
                if _maybe_awaitable(maybe_coro):
                    await maybe_coro
    except Exception:
        logger.warning(
            "Failed to write goal_interrupted marker for loop %s",
            lid[:16],
            exc_info=True,
        )
        return 0


def _maybe_awaitable(obj: Any) -> bool:
    import asyncio

    return asyncio.iscoroutine(obj) or asyncio.isfuture(obj)


__all__ = ["mark_cancelled_goal_interrupted"]

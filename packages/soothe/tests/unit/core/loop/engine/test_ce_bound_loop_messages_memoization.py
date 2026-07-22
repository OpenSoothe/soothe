"""Integration test for the CE-bound ``loop_messages`` memoization path.

Exercises the full chain that previously hung: ``LoopState`` bound to a real
``ContextEngine`` via ``bind_ce()``, execute evidence recorded to the CE ledger,
and ``append_goal_interrupted_ledger_pair`` reading ``state.loop_messages``
internally through ``_collect_execute_evidence_excerpts``.

Before the memoization fix, every ``loop_messages`` access when CE-bound
triggered an O(n) rebuild from the full ledger with no change detection.  With
many messages this blocked the event loop.  The fix keys the rebuild on
``LedgerManager.revision`` so repeated accesses between mutations return the
cached list in O(1).

This test verifies:
1. The CE-bound path returns correct messages from the CE ledger.
2. Repeated accesses use the memoization cache (same object, no rebuild).
3. After a ledger mutation the cache invalidates and fresh data is returned.
4. ``append_goal_interrupted_ledger_pair`` completes without hanging and the
   digest references the CE-sourced execute evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from soothe.context.engine import ContextEngine
from soothe.context.store_sqlite import SqliteContextPersistence
from soothe.sloop.engine.goal_interrupt_record import (
    append_goal_interrupted_ledger_pair,
)
from soothe.sloop.state.schemas import LoopState
from soothe.sloop.utils.messages import (
    LoopAIMessage,
    LoopHumanMessage,
    _record_ledger_message,
)


@dataclass
class _FakeCtx:
    """Minimal stand-in for ``LoopRuntimeContext`` used by the writer."""

    loop_state: LoopState
    ce: Any
    ce_goal_id: str | None = None


def _make_ce() -> ContextEngine:
    """Create a ContextEngine with an in-memory SQLite backend."""
    return ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )


def _make_bound_state(ce: ContextEngine, goal_id: str) -> LoopState:
    """Create a LoopState bound to the given CE and goal."""
    state = LoopState(goal="fix the parser bug", thread_id="t1", iteration=2)
    state.bind_ce(ce, goal_id)
    return state


# ── CE-bound loop_messages memoization ─────────────────────────────────


class TestCEBoundLoopMessagesMemoization:
    """Verify the revision-keyed memoization on the CE-bound path."""

    @pytest.mark.asyncio
    async def test_repeated_access_returns_cached_object(self) -> None:
        """Repeated ``loop_messages`` access without mutation returns the same
        list object (memoization hit), proving no O(n) rebuild on each call."""
        ce = _make_ce()
        goal = await ce.create_goal("test goal")
        state = _make_bound_state(ce, goal.id)

        # Record execute_step evidence into the CE ledger
        for i in range(10):
            _record_ledger_message(
                ce,
                LoopHumanMessage(content=f"exec human {i}", phase="execute_step", thread_id="t1"),
                "execute_step",
            )
            _record_ledger_message(
                ce,
                LoopAIMessage(content=f"execute result {i}", phase="execute_step", thread_id="t1"),
                "execute_step",
            )

        first = state.loop_messages
        second = state.loop_messages
        third = state.loop_messages

        # Memoization: same object returned on repeated access (no rebuild)
        assert first is second
        assert second is third
        assert len(first) == 20

    @pytest.mark.asyncio
    async def test_cache_invalidates_after_ledger_mutation(self) -> None:
        """After a new message is recorded, the revision changes and the cache
        is rebuilt — fresh data appears on the next access."""
        ce = _make_ce()
        goal = await ce.create_goal("test goal")
        state = _make_bound_state(ce, goal.id)

        _record_ledger_message(
            ce,
            LoopHumanMessage(content="first message", phase="execute_step", thread_id="t1"),
            "execute_step",
        )

        first = state.loop_messages
        assert len(first) == 1
        assert first[0].content == "first message"

        # Mutate the ledger — revision increments
        _record_ledger_message(
            ce,
            LoopAIMessage(content="second message", phase="execute_step", thread_id="t1"),
            "execute_step",
        )

        second = state.loop_messages
        # Cache invalidated → different object, fresh data
        assert second is not first
        assert len(second) == 2
        assert second[1].content == "second message"

    @pytest.mark.asyncio
    async def test_cache_invalidates_after_bind_ce(self) -> None:
        """``bind_ce`` clears the memoization cache so the first post-bind
        access rebuilds from the CE ledger."""
        ce = _make_ce()
        goal = await ce.create_goal("test goal")
        state = LoopState(goal="test", thread_id="t1")

        # Pre-bind: local cache path
        state._loop_messages_cache.append(  # type: ignore[attr-defined]
            LoopHumanMessage(content="stale local", phase="execute_step", thread_id="t1")
        )
        assert state.loop_messages[0].content == "stale local"

        # Record to CE *before* binding
        _record_ledger_message(
            ce,
            LoopAIMessage(content="from ce", phase="execute_step", thread_id="t1"),
            "execute_step",
        )

        # Bind — clears local cache and invalidates memoization
        state.bind_ce(ce, goal.id)

        result = state.loop_messages
        assert len(result) == 1
        assert result[0].content == "from ce"

    @pytest.mark.asyncio
    async def test_large_ledger_does_not_hang_on_repeated_access(self) -> None:
        """With a large CE ledger, repeated ``loop_messages`` accesses must
        not hang — the memoization ensures O(1) return after the first build."""
        ce = _make_ce()
        goal = await ce.create_goal("stress test goal")
        state = _make_bound_state(ce, goal.id)

        # Populate a sizable ledger (500 messages)
        for i in range(500):
            _record_ledger_message(
                ce,
                LoopHumanMessage(content=f"human-{i}", phase="execute_step", thread_id="t1"),
                "execute_step",
            )
            _record_ledger_message(
                ce,
                LoopAIMessage(content=f"ai-{i}", phase="execute_step", thread_id="t1"),
                "execute_step",
            )

        # First access builds the cache (O(n) once)
        first = state.loop_messages
        assert len(first) == 1000

        # 100 subsequent accesses — all memoized, O(1) each, no hang
        for _ in range(100):
            assert state.loop_messages is first

    @pytest.mark.asyncio
    async def test_append_goal_interrupted_reads_ce_bound_path_without_hang(self) -> None:
        """The actual hang scenario: ``append_goal_interrupted_ledger_pair``
        calls ``_collect_execute_evidence_excerpts(state)`` which iterates
        ``state.loop_messages``.  When CE is bound, this reads from the CE
        ledger.  The function must complete without hanging and the digest
        must reference the CE-sourced execute evidence."""
        ce = _make_ce()
        goal = await ce.create_goal("fix the parser bug")
        state = _make_bound_state(ce, goal.id)

        # Record execute_step evidence that the digest should reference
        _record_ledger_message(
            ce,
            LoopHumanMessage(content="run the parser tests", phase="execute_step", thread_id="t1"),
            "execute_step",
        )
        _record_ledger_message(
            ce,
            LoopAIMessage(
                content="Found the bug in parser.py line 42 — off-by-one in token count",
                phase="execute_step",
                thread_id="t1",
            ),
            "execute_step",
        )

        ctx = _FakeCtx(loop_state=state, ce=ce, ce_goal_id=goal.id)

        # This must complete without hanging
        await append_goal_interrupted_ledger_pair(ctx, reason="user_cancelled")

        # Verify the marker was written with CE-sourced evidence
        ledger = await ce.get_ledger(phases=["goal_interrupted"])
        assert len(ledger) == 2  # Human + AI pair

        ai_body = str(getattr(ledger[-1], "content", ""))
        assert "user_cancelled" in ai_body
        # Evidence from the CE-bound loop_messages path appears in the digest
        assert "parser.py line 42" in ai_body

    @pytest.mark.asyncio
    async def test_append_with_repeated_loop_messages_access_no_hang(self) -> None:
        """Multiple calls to ``append_goal_interrupted_ledger_pair`` each read
        ``state.loop_messages``.  The memoization ensures these don't trigger
        redundant rebuilds between the internal accesses."""
        ce = _make_ce()
        goal = await ce.create_goal("multi-call goal")
        state = _make_bound_state(ce, goal.id)

        # Record initial evidence
        _record_ledger_message(
            ce,
            LoopAIMessage(
                content="Initial analysis complete", phase="execute_step", thread_id="t1"
            ),
            "execute_step",
        )

        ctx = _FakeCtx(loop_state=state, ce=ce, ce_goal_id=goal.id)

        # First call — builds memoization cache, writes marker
        await append_goal_interrupted_ledger_pair(ctx, reason="rate_limited")

        ledger_1 = await ce.get_ledger(phases=["goal_interrupted"])
        assert len(ledger_1) == 2

        # Second call — cache is still valid (no new execute_step messages),
        # but the goal_interrupted markers add to the ledger which changes
        # the revision. The memoization must handle this correctly without
        # hanging.
        await append_goal_interrupted_ledger_pair(ctx, reason="rate_limited")

        ledger_2 = await ce.get_ledger(phases=["goal_interrupted"])
        assert len(ledger_2) == 4  # Two Human+AI pairs

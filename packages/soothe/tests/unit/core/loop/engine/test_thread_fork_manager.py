"""Unit tests for ThreadForkManager (RFC-223).

Covers:
- ``select_fork_source``: source + should_fork tuple per dependency shape
  - 0 deps (main thread, no fork)
  - 1 dep, sole child (reuse predecessor thread, no fork — RFC-223 optimization)
  - 1 dep, has siblings (fork from predecessor)
  - >1 deps (main thread + message injection, no fork)
- ``fork_checkpoint`` via in-house ``copy_thread_via_public_api``
- ``prepare_thread_for_step``: full preparation flow with state updates
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe.core.loop.engine.thread_fork_manager import ThreadForkManager
from soothe.core.loop.state.schemas import AgentDecision, LoopState, StepAction


def _decision(*steps: StepAction) -> AgentDecision:
    return AgentDecision(type="execute_steps", steps=list(steps))


# ---- select_fork_source -----------------------------------------------


class TestSelectForkSource:
    """``select_fork_source`` returns ``(source_thread_id, should_fork)``."""

    def test_no_deps_forks_from_main(self) -> None:
        """No deps → fresh isolated thread sourced from main (parallel safety)."""
        manager = ThreadForkManager(None)
        step = StepAction(id="A", description="step A", dependencies=[])
        state = LoopState(thread_id="loop1", goal="g")

        source, should_fork = manager.select_fork_source(step, _decision(step), state)
        assert source == "loop1"
        assert should_fork is True

    def test_multi_dep_forks_from_main(self) -> None:
        """≥2 deps → fresh isolated thread sourced from main; messages injected upstream."""
        manager = ThreadForkManager(None)
        a = StepAction(id="A", description="A", dependencies=[])
        b = StepAction(id="B", description="B", dependencies=[])
        c = StepAction(id="C", description="C", dependencies=["A", "B"])
        state = LoopState(
            thread_id="loop1",
            goal="g",
            step_thread_ids={"A": "loop1__step_A", "B": "loop1__step_B"},
        )

        source, should_fork = manager.select_fork_source(c, _decision(a, b, c), state)
        assert source == "loop1"
        assert should_fork is True

    def test_singleton_sole_child_reuses_predecessor_no_fork(self) -> None:
        """Sole-child optimization: B depends only on A and is A's only child.
        B reuses A's thread directly. No fork."""
        manager = ThreadForkManager(None)
        a = StepAction(id="A", description="A", dependencies=[])
        b = StepAction(id="B", description="B", dependencies=["A"])
        state = LoopState(
            thread_id="loop1",
            goal="g",
            step_thread_ids={"A": "loop1__step_A"},
        )

        source, should_fork = manager.select_fork_source(b, _decision(a, b), state)
        assert source == "loop1__step_A"
        assert should_fork is False  # sole child → reuse, no copy

    def test_singleton_with_siblings_forks(self) -> None:
        """A→B and A→C: B and C both depend on A. A has 2 dependents.
        Each child must FORK to keep their histories independent."""
        manager = ThreadForkManager(None)
        a = StepAction(id="A", description="A", dependencies=[])
        b = StepAction(id="B", description="B", dependencies=["A"])
        c = StepAction(id="C", description="C", dependencies=["A"])
        state = LoopState(
            thread_id="loop1",
            goal="g",
            step_thread_ids={"A": "loop1__step_A"},
        )

        source_b, fork_b = manager.select_fork_source(b, _decision(a, b, c), state)
        source_c, fork_c = manager.select_fork_source(c, _decision(a, b, c), state)
        assert source_b == "loop1__step_A"
        assert source_c == "loop1__step_A"
        assert fork_b is True
        assert fork_c is True

    def test_chain_singleton_inherits_from_immediate_predecessor(self) -> None:
        """Chain A→B→C: each link is sole-child, all reuse without fork."""
        manager = ThreadForkManager(None)
        a = StepAction(id="A", description="A", dependencies=[])
        b = StepAction(id="B", description="B", dependencies=["A"])
        c = StepAction(id="C", description="C", dependencies=["B"])
        state = LoopState(
            thread_id="loop1",
            goal="g",
            step_thread_ids={"A": "loop1__step_A", "B": "loop1__step_B"},
        )

        source, should_fork = manager.select_fork_source(c, _decision(a, b, c), state)
        assert source == "loop1__step_B"
        assert should_fork is False  # B has only one dependent (C)

    def test_missing_predecessor_thread_falls_back_to_main(self) -> None:
        """Predecessor's thread wasn't tracked → fall back to main + fork."""
        manager = ThreadForkManager(None)
        a = StepAction(id="A", description="A", dependencies=[])
        b = StepAction(id="B", description="B", dependencies=["A"])
        state = LoopState(thread_id="loop1", goal="g")  # no step_thread_ids

        source, should_fork = manager.select_fork_source(b, _decision(a, b), state)
        assert source == "loop1"
        assert should_fork is True


# ---- fork_checkpoint --------------------------------------------------


class TestForkCheckpoint:
    """fork_checkpoint uses copy_thread_via_public_api (no acopy_thread call)."""

    @pytest.mark.asyncio
    async def test_fork_calls_copy_helper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from soothe.core.loop.engine import thread_fork_manager as tfm_mod

        recorded: dict[str, Any] = {}

        async def _fake_copy(saver: Any, source: str, target: str) -> int:
            recorded["saver"] = saver
            recorded["source"] = source
            recorded["target"] = target
            return 3  # 3 checkpoints copied

        monkeypatch.setattr(tfm_mod, "copy_thread_via_public_api", _fake_copy)

        saver = MagicMock()
        manager = ThreadForkManager(saver)
        result = await manager.fork_checkpoint("src", "tgt")

        assert result == "tgt"
        assert recorded == {"saver": saver, "source": "src", "target": "tgt"}

    @pytest.mark.asyncio
    async def test_fork_helper_failure_returns_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from soothe.core.loop.engine import thread_fork_manager as tfm_mod

        async def _fake_copy(saver: Any, source: str, target: str) -> int:
            raise RuntimeError("DB error")

        monkeypatch.setattr(tfm_mod, "copy_thread_via_public_api", _fake_copy)

        manager = ThreadForkManager(MagicMock())
        result = await manager.fork_checkpoint("src", "tgt")
        assert result == "src"  # fallback to source

    @pytest.mark.asyncio
    async def test_no_checkpointer_returns_source(self) -> None:
        manager = ThreadForkManager(None)
        result = await manager.fork_checkpoint("src", "tgt")
        assert result == "src"

    @pytest.mark.asyncio
    async def test_same_source_target_no_op(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When source == target, no copy attempted."""
        from soothe.core.loop.engine import thread_fork_manager as tfm_mod

        called = {"count": 0}

        async def _fake_copy(*_args: Any, **_kwargs: Any) -> int:
            called["count"] += 1
            return 0

        monkeypatch.setattr(tfm_mod, "copy_thread_via_public_api", _fake_copy)
        manager = ThreadForkManager(MagicMock())
        result = await manager.fork_checkpoint("same", "same")
        assert result == "same"
        assert called["count"] == 0


# ---- prepare_thread_for_step ------------------------------------------


class TestPrepareThreadForStep:
    @pytest.mark.asyncio
    async def test_first_step_forks_to_isolated_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No deps → fresh isolated __step_<id> thread sourced from main."""
        from soothe.core.loop.engine import thread_fork_manager as tfm_mod

        copy_calls: list[tuple[str, str]] = []

        async def _fake_copy(saver: Any, source: str, target: str) -> int:
            copy_calls.append((source, target))
            return 0  # main has no checkpoints yet

        monkeypatch.setattr(tfm_mod, "copy_thread_via_public_api", _fake_copy)

        manager = ThreadForkManager(MagicMock())
        step = StepAction(id="A", description="A", dependencies=[])
        state = LoopState(thread_id="loop1", goal="g")

        result = await manager.prepare_thread_for_step(step, _decision(step), state, "loop1")
        assert result == "loop1__step_A"
        assert copy_calls == [("loop1", "loop1__step_A")]
        assert state.step_thread_ids["A"] == "loop1__step_A"
        assert state.thread_fork_sources["loop1__step_A"] == "loop1"

    @pytest.mark.asyncio
    async def test_sole_child_reuses_predecessor_no_copy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from soothe.core.loop.engine import thread_fork_manager as tfm_mod

        copy_called = {"count": 0}

        async def _fake_copy(*_args: Any, **_kwargs: Any) -> int:
            copy_called["count"] += 1
            return 0

        monkeypatch.setattr(tfm_mod, "copy_thread_via_public_api", _fake_copy)

        manager = ThreadForkManager(MagicMock())
        a = StepAction(id="A", description="A", dependencies=[])
        b = StepAction(id="B", description="B", dependencies=["A"])
        state = LoopState(
            thread_id="loop1",
            goal="g",
            step_thread_ids={"A": "loop1__step_A"},
        )

        result = await manager.prepare_thread_for_step(b, _decision(a, b), state, "loop1")
        assert result == "loop1__step_A"  # reused, no fork
        assert copy_called["count"] == 0  # no copy for sole-child
        assert state.step_thread_ids["B"] == "loop1__step_A"

    @pytest.mark.asyncio
    async def test_sibling_step_forks_with_copy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from soothe.core.loop.engine import thread_fork_manager as tfm_mod

        copy_calls: list[tuple[str, str]] = []

        async def _fake_copy(saver: Any, source: str, target: str) -> int:
            copy_calls.append((source, target))
            return 5

        monkeypatch.setattr(tfm_mod, "copy_thread_via_public_api", _fake_copy)

        manager = ThreadForkManager(MagicMock())
        a = StepAction(id="A", description="A", dependencies=[])
        b = StepAction(id="B", description="B", dependencies=["A"])
        c = StepAction(id="C", description="C", dependencies=["A"])
        state = LoopState(
            thread_id="loop1",
            goal="g",
            step_thread_ids={"A": "loop1__step_A"},
        )

        # B and C are siblings — both fork from A.
        b_thread = await manager.prepare_thread_for_step(b, _decision(a, b, c), state, "loop1")
        c_thread = await manager.prepare_thread_for_step(c, _decision(a, b, c), state, "loop1")

        assert b_thread == "loop1__step_B"
        assert c_thread == "loop1__step_C"
        assert ("loop1__step_A", "loop1__step_B") in copy_calls
        assert ("loop1__step_A", "loop1__step_C") in copy_calls
        assert state.step_thread_ids["B"] == "loop1__step_B"
        assert state.step_thread_ids["C"] == "loop1__step_C"
        assert state.thread_fork_sources["loop1__step_B"] == "loop1__step_A"

    @pytest.mark.asyncio
    async def test_multi_dep_forks_from_main_to_isolated_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Multi-dep step → fresh isolated thread sourced from main."""
        from soothe.core.loop.engine import thread_fork_manager as tfm_mod

        copy_calls: list[tuple[str, str]] = []

        async def _fake_copy(saver: Any, source: str, target: str) -> int:
            copy_calls.append((source, target))
            return 0

        monkeypatch.setattr(tfm_mod, "copy_thread_via_public_api", _fake_copy)

        manager = ThreadForkManager(MagicMock())
        a = StepAction(id="A", description="A", dependencies=[])
        b = StepAction(id="B", description="B", dependencies=[])
        c = StepAction(id="C", description="C", dependencies=["A", "B"])
        state = LoopState(
            thread_id="loop1",
            goal="g",
            step_thread_ids={"A": "loop1__step_A", "B": "loop1__step_B"},
        )

        result = await manager.prepare_thread_for_step(c, _decision(a, b, c), state, "loop1")
        assert result == "loop1__step_C"
        assert copy_calls == [("loop1", "loop1__step_C")]
        assert state.thread_fork_sources["loop1__step_C"] == "loop1"

    @pytest.mark.asyncio
    async def test_chain_a_b_c_only_first_forks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A→B→C linear chain: A forks from main once; B and C reuse A's
        thread because each link is a sole-child step. Total copies = 1."""
        from soothe.core.loop.engine import thread_fork_manager as tfm_mod

        copy_calls: list[tuple[str, str]] = []

        async def _fake_copy(saver: Any, source: str, target: str) -> int:
            copy_calls.append((source, target))
            return 0

        monkeypatch.setattr(tfm_mod, "copy_thread_via_public_api", _fake_copy)

        manager = ThreadForkManager(MagicMock())
        a = StepAction(id="A", description="A", dependencies=[])
        b = StepAction(id="B", description="B", dependencies=["A"])
        c = StepAction(id="C", description="C", dependencies=["B"])
        decision = _decision(a, b, c)
        state = LoopState(thread_id="loop1", goal="g")

        a_thread = await manager.prepare_thread_for_step(a, decision, state, "loop1")
        b_thread = await manager.prepare_thread_for_step(b, decision, state, "loop1")
        c_thread = await manager.prepare_thread_for_step(c, decision, state, "loop1")

        # A forks from main into __step_A. B and C reuse __step_A (sole-child).
        assert a_thread == "loop1__step_A"
        assert b_thread == "loop1__step_A"
        assert c_thread == "loop1__step_A"
        assert copy_calls == [("loop1", "loop1__step_A")]


# ---- fork failure fallback in prepare_thread_for_step ------------------


class TestPrepareThreadForStepForkFailure:
    @pytest.mark.asyncio
    async def test_fork_failure_uses_source_thread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the copy helper raises, prepare returns source (not target)."""
        from soothe.core.loop.engine import thread_fork_manager as tfm_mod

        async def _fake_copy(*_args: Any, **_kwargs: Any) -> int:
            raise RuntimeError("disk full")

        monkeypatch.setattr(tfm_mod, "copy_thread_via_public_api", _fake_copy)

        manager = ThreadForkManager(MagicMock())
        a = StepAction(id="A", description="A", dependencies=[])
        b = StepAction(id="B", description="B", dependencies=["A"])
        c = StepAction(id="C", description="C", dependencies=["A"])  # sibling forces fork
        state = LoopState(
            thread_id="loop1",
            goal="g",
            step_thread_ids={"A": "loop1__step_A"},
        )

        result = await manager.prepare_thread_for_step(b, _decision(a, b, c), state, "loop1")
        # Fork failed → fall back to source thread.
        assert result == "loop1__step_A"
        # State still records the actual thread used.
        assert state.step_thread_ids["B"] == "loop1__step_A"

"""Tests for the live agent-mode hot-swap on StrangeLoop and SootheRunner.

Covers:
- `StrangeLoop.set_clarification_mode` updates `ctx.interaction_mode` and
  rebuilds the policy with the bypass flag.
- `SootheRunner.set_clarification_mode` swaps the live CoreAgent graph when
  `interaction_mode` changes (auto→bypass, bypass→auto) and leaves the graph
  untouched when only the clarification mode changes (auto↔manual).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from soothe.runner import SootheRunner
from soothe.sloop.strange_loop import StrangeLoop


class _FakeAgent:
    """Stand-in for the live StrangeLoop instance held by SootheRunner."""

    def __init__(self, initial_graph: object) -> None:
        self.core_agent = initial_graph
        self.policy_swaps: list[tuple[str, str | None]] = []

    def set_clarification_mode(
        self,
        mode: str,
        *,
        interaction_mode: str | None = None,
    ) -> bool:
        self.policy_swaps.append((mode, interaction_mode))
        return True


def _bare_strange_loop() -> StrangeLoop:
    """A StrangeLoop with __init__ bypassed; only swap-relevant attrs set."""
    loop = StrangeLoop.__new__(StrangeLoop)
    loop.config = SimpleNamespace()  # build_clarification_policy_for_runner is patched
    return loop


def _bare_runner(agent: _FakeAgent, *, interaction_mode: str | None) -> SootheRunner:
    """A SootheRunner with __init__ bypassed; only swap-relevant attrs set."""
    runner = SootheRunner.__new__(SootheRunner)
    runner._live_loop_agent = agent
    runner._live_loop_interaction_mode = interaction_mode
    runner._bypass_core_agent = object()  # sentinel graph
    runner._core_agent = object()  # sentinel default graph
    runner._materialize_core_agent = AsyncMock(return_value=None)  # type: ignore[method-assign]
    return runner


# --------------------------------------------------------------------------- #
# StrangeLoop.set_clarification_mode
# --------------------------------------------------------------------------- #


def test_strange_loop_no_live_context_returns_false() -> None:
    loop = _bare_strange_loop()
    loop._live_runtime_ctx = None
    assert loop.set_clarification_mode("manual") is False


def test_strange_loop_swaps_policy_and_interaction_mode() -> None:
    """`interaction_mode` lands on `ctx` alongside the rebuilt policy."""
    loop = _bare_strange_loop()
    sentinel_policy = object()
    ctx = SimpleNamespace(
        clarification_policy=None,
        interaction_mode=None,
        emit=lambda *_a, **_k: None,
        strange_loop=SimpleNamespace(_thread_id="t1"),
        state_manager=SimpleNamespace(loop_id="l1"),
    )
    loop._live_runtime_ctx = ctx

    with patch(
        "soothe.sloop.clarification.runtime_factory.build_clarification_policy_for_runner",
        return_value=sentinel_policy,
    ) as mocked:
        result = loop.set_clarification_mode("auto", interaction_mode="bypass")

    assert result is True
    assert ctx.clarification_policy is sentinel_policy
    assert ctx.interaction_mode == "bypass"
    assert mocked.call_args.kwargs["interaction_mode"] == "bypass"
    assert mocked.call_args.kwargs["mode"] == "auto"


def test_strange_loop_build_failure_keeps_existing_policy() -> None:
    """When the policy rebuild raises, the existing policy stays untouched."""
    loop = _bare_strange_loop()
    existing = object()
    ctx = SimpleNamespace(
        clarification_policy=existing,
        interaction_mode=None,
        emit=lambda *_a, **_k: None,
        strange_loop=SimpleNamespace(_thread_id="t1"),
        state_manager=SimpleNamespace(loop_id="l1"),
    )
    loop._live_runtime_ctx = ctx

    with patch(
        "soothe.sloop.clarification.runtime_factory.build_clarification_policy_for_runner",
        side_effect=RuntimeError("boom"),
    ):
        result = loop.set_clarification_mode("manual", interaction_mode=None)

    assert result is False
    assert ctx.clarification_policy is existing
    assert ctx.interaction_mode is None


# --------------------------------------------------------------------------- #
# SootheRunner.set_clarification_mode
# --------------------------------------------------------------------------- #


async def test_runner_no_live_agent_returns_false() -> None:
    runner = _bare_runner(_FakeAgent(object()), interaction_mode=None)
    runner._live_loop_agent = None
    assert await runner.set_clarification_mode("auto") is False


async def test_runner_auto_to_bypass_swaps_graph() -> None:
    """Switching to bypass reassigns the live agent's CoreAgent graph."""
    default_graph = object()
    agent = _FakeAgent(default_graph)
    runner = _bare_runner(agent, interaction_mode=None)
    bypass_graph = runner._bypass_core_agent

    result = await runner.set_clarification_mode("auto", interaction_mode="bypass")

    assert result is True
    assert agent.core_agent is bypass_graph
    assert runner._live_loop_interaction_mode == "bypass"
    runner._materialize_core_agent.assert_awaited_once_with("bypass")
    assert agent.policy_swaps == [("auto", "bypass")]


async def test_runner_bypass_to_auto_swaps_back_to_default_graph() -> None:
    """Switching off bypass restores the default (interrupt-on) graph."""
    bypass_graph = object()
    agent = _FakeAgent(bypass_graph)
    runner = _bare_runner(agent, interaction_mode="bypass")
    default_graph = runner._core_agent

    result = await runner.set_clarification_mode("manual", interaction_mode=None)

    assert result is True
    assert agent.core_agent is default_graph
    assert runner._live_loop_interaction_mode is None
    runner._materialize_core_agent.assert_awaited_once_with(None)
    assert agent.policy_swaps == [("manual", None)]


async def test_runner_auto_to_manual_skips_graph_swap() -> None:
    """auto↔manual share the default graph; no materialize call fires."""
    default_graph = object()
    agent = _FakeAgent(default_graph)
    runner = _bare_runner(agent, interaction_mode=None)

    result = await runner.set_clarification_mode("manual", interaction_mode=None)

    assert result is True
    assert agent.core_agent is default_graph
    assert runner._live_loop_interaction_mode is None
    runner._materialize_core_agent.assert_not_awaited()
    assert agent.policy_swaps == [("manual", None)]


async def test_runner_materialize_failure_skips_graph_swap_keeps_policy() -> None:
    """A graph-compile failure is logged+skipped; the policy swap still runs."""
    default_graph = object()
    agent = _FakeAgent(default_graph)
    runner = _bare_runner(agent, interaction_mode=None)
    runner._materialize_core_agent = AsyncMock(side_effect=RuntimeError("compile failed"))  # type: ignore[method-assign]

    result = await runner.set_clarification_mode("auto", interaction_mode="bypass")

    assert result is True
    # graph not swapped (materialize raised before reassignment)
    assert agent.core_agent is default_graph
    assert runner._live_loop_interaction_mode is None
    # policy swap still attempted so the mode badge reflects intent
    assert agent.policy_swaps == [("auto", "bypass")]

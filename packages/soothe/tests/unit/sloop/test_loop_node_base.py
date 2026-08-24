"""Tests for the ``LoopNode`` lifecycle base and typed contracts (RFC-903 P1).

P1 is non-breaking: these tests exercise the new types and the driver in
isolation. No existing node is migrated yet — ``wrap_node`` legacy detection
is tested against a stub function, not the real builder.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.sloop.orchestrator.node_base import (
    GuardOutcome,
    LoopNode,
    NodeResult,
    RouteDecision,
    wrap_node,
)

# --------------------------------------------------------------------------- #
# RouteDecision.as_state_patch
# --------------------------------------------------------------------------- #


class TestRouteDecisionStatePatch:
    def test_proceed_merges_state_patch(self) -> None:
        rd = RouteDecision(kind="proceed", next_phase="execute", state_patch={"foo": 1})
        assert rd.as_state_patch() == {"foo": 1}

    def test_proceed_no_patch_returns_empty(self) -> None:
        rd = RouteDecision(kind="proceed")
        assert rd.as_state_patch() == {}

    def test_fatal_sets_last_outcome(self) -> None:
        rd = RouteDecision(kind="fatal")
        assert rd.as_state_patch() == {"last_outcome": "fatal"}

    def test_deferred_sets_last_outcome(self) -> None:
        rd = RouteDecision(kind="deferred")
        assert rd.as_state_patch() == {"last_outcome": "deferred"}

    def test_terminal_does_not_set_last_outcome(self) -> None:
        """Terminal is a route (to complete/END), not an outcome channel."""
        rd = RouteDecision(kind="terminal")
        assert rd.as_state_patch() == {}

    def test_fatal_respects_explicit_last_outcome_override(self) -> None:
        rd = RouteDecision(kind="fatal", state_patch={"last_outcome": "continue"})
        assert rd.as_state_patch() == {"last_outcome": "continue"}

    def test_fatal_merges_extra_patch(self) -> None:
        rd = RouteDecision(kind="fatal", state_patch={"step_id": "s01"})
        patch = rd.as_state_patch()
        assert patch == {"last_outcome": "fatal", "step_id": "s01"}


# --------------------------------------------------------------------------- #
# GuardOutcome.as_state_patch
# --------------------------------------------------------------------------- #


class TestGuardOutcomeStatePatch:
    def test_fatal_sets_last_outcome(self) -> None:
        g = GuardOutcome(kind="fatal")
        assert g.as_state_patch() == {"last_outcome": "fatal"}

    def test_deferred_sets_last_outcome(self) -> None:
        g = GuardOutcome(kind="deferred")
        assert g.as_state_patch() == {"last_outcome": "deferred"}

    def test_skip_produces_no_outcome_change(self) -> None:
        g = GuardOutcome(kind="skip")
        assert g.as_state_patch() == {}

    def test_skip_merges_explicit_patch(self) -> None:
        """Skip can still clear channels (e.g. last_outcome=None)."""
        g = GuardOutcome(kind="skip", state_patch={"last_outcome": None})
        assert g.as_state_patch() == {"last_outcome": None}


# --------------------------------------------------------------------------- #
# LoopNode driver — runs stages in order
# --------------------------------------------------------------------------- #


class _StubNode(LoopNode):
    """Minimal node for testing the driver pipeline."""

    station = "test_stub"
    call_kind = None

    def __init__(self) -> None:
        self.pre_called = False
        self.project_called = False
        self.prompt_called = False
        self.process_called = False
        self.post_called = False

    def post(self, ctx: Any, state: dict[str, Any], result: NodeResult) -> RouteDecision:
        self.post_called = True
        return RouteDecision(kind="proceed")

    async def process(self, ctx: Any, state: dict[str, Any], messages: list) -> NodeResult:
        self.process_called = True
        assert messages == [], "non-LLM node should get empty messages"
        return NodeResult(payload="done")


class TestLoopNodeDriver:
    async def test_runs_all_stages_in_order(self) -> None:
        node = _StubNode()
        ctx = MagicMock()
        state: dict[str, Any] = {}

        patch = await node(ctx, state)

        assert node.process_called is True
        assert node.post_called is True
        assert patch == {}  # post returns RouteDecision(proceed) -> {}

    async def test_pre_short_circuits_skips_process(self) -> None:
        class _GuardedNode(_StubNode):
            async def pre(self, ctx: Any, state: dict[str, Any]) -> GuardOutcome | None:
                return GuardOutcome(kind="fatal")

        node = _GuardedNode()
        ctx = MagicMock()
        state: dict[str, Any] = {}

        patch = await node(ctx, state)

        assert node.process_called is False
        assert node.post_called is False
        assert patch == {"last_outcome": "fatal"}

    async def test_pre_returning_none_proceeds(self) -> None:
        class _NonePreNode(_StubNode):
            async def pre(self, ctx: Any, state: dict[str, Any]) -> GuardOutcome | None:
                return None

        node = _NonePreNode()
        ctx = MagicMock()

        await node(ctx, {})

        assert node.process_called is True

    async def test_driver_emits_process_events(self) -> None:
        emitted: list[tuple[str, dict]] = []

        class _EmittingNode(_StubNode):
            async def process(self, ctx: Any, state: dict[str, Any], messages: list) -> NodeResult:
                self.process_called = True
                return NodeResult(
                    payload="done",
                    events=[("plan", {"status": "ok"}), ("step_started", {"step_id": "1"})],
                )

        node = _EmittingNode()
        ctx = MagicMock()
        ctx.emit = AsyncMock(side_effect=lambda t, p: emitted.append((t, p)))

        await node(ctx, {})

        assert emitted == [("plan", {"status": "ok"}), ("step_started", {"step_id": "1"})]

    def test_non_llm_node_gets_empty_projection_and_prompt(self) -> None:
        node = _StubNode()
        ctx = MagicMock()
        state: dict[str, Any] = {}

        proj = node.project(ctx, state)
        assert proj.messages == []
        assert proj.mode is None
        assert proj.completion_in_ledger is False

        messages = node.prompt(ctx, state, proj)
        assert messages == []


# --------------------------------------------------------------------------- #
# wrap_node adapter
# --------------------------------------------------------------------------- #


class TestWrapNode:
    async def test_detects_loop_node_instance(self) -> None:
        node = _StubNode()
        ctx = MagicMock()
        state = {"x": 1}

        wrapped = wrap_node("test_stub", node, ctx)
        assert wrapped.__name__ == "node_test_stub"

        patch = await wrapped(state)
        # Default post returns proceed -> {}
        assert patch == {}
        assert node.process_called is True

    async def test_legacy_function_path_unchanged(self) -> None:
        called_with: dict[str, Any] = {}

        async def legacy_node(ctx: Any, state: dict[str, Any]) -> dict[str, Any]:
            called_with["ctx"] = ctx
            called_with["state"] = state
            return {"last_outcome": "continue"}

        ctx = MagicMock()
        state = {"x": 1}

        wrapped = wrap_node("legacy", legacy_node, ctx)
        assert wrapped.__name__ == "node_legacy"

        patch = await wrapped(state)

        assert patch == {"last_outcome": "continue"}
        assert called_with["state"] is state
        assert called_with["ctx"] is ctx

    async def test_loop_node_dispatches_through_driver(self) -> None:
        """A LoopNode passed to wrap_node should use __call__, not be called
        as a legacy ``async def(ctx, state)``."""

        class _TrackingNode(LoopNode):
            station = "track"
            driver_invoked = False

            async def process(self, ctx: Any, state: dict[str, Any], messages: list) -> NodeResult:
                self.driver_invoked = True
                return NodeResult()

        node = _TrackingNode()
        ctx = MagicMock()
        wrapped = wrap_node("track", node, ctx)

        await wrapped({})

        assert node.driver_invoked is True


# --------------------------------------------------------------------------- #
# Abstract method enforcement
# --------------------------------------------------------------------------- #


class TestLoopNodeAbstract:
    def test_cannot_instantiate_without_process(self) -> None:
        with pytest.raises(TypeError):
            LoopNode()  # type: ignore[abstract]

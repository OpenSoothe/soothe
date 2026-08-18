"""Generalized StrangeLoop graph node lifecycle (RFC-903 §4, IG P1).

Introduces the ``LoopNode`` base class with a five-method lifecycle
(``pre`` / ``project`` / ``prompt`` / ``process`` / ``post``) and the typed
``RouteDecision`` / ``GuardOutcome`` contracts that replace the implicit
``async def(ctx, state) -> dict`` shape and free-form route-key dict.

P1 (this module) is **non-breaking**: the ``wrap_node`` adapter detects
``LoopNode`` instances vs legacy ``async def(ctx, state) -> dict`` functions so
the graph builder can adopt the new base incrementally without touching
existing nodes. No node is migrated in P1; guard centralization (fatal,
clarification, resume-skip) lands in P2–P3, and the phase-subgraph topology in
P4–P5.

See:
- RFC-903 §Generalized Node Lifecycle
- ``docs/impl/IG-sloop-generalized-node-topology.md`` §3–§4
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from soothe.sloop.prompts.graph_wrapper import (
        GraphCallKind,
        ProjectionResult,
    )

    from .runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Typed return contracts
# --------------------------------------------------------------------------- #

RouteKind = Literal["proceed", "await_user", "deferred", "fatal", "terminal"]
"""Discriminator for the route a node selects after its work completes.

- ``proceed`` — continue within the current phase or hand to the next.
- ``await_user`` — route to the residual ``await_user`` sidecar (non-return
  clarification origin only; return-to-sender origins use native
  ``interrupt()`` in P6).
- ``deferred`` — clarification deferred by policy; terminate the run.
- ``fatal`` — unrecoverable error; terminate the run.
- ``terminal`` — goal done; route to ``complete`` / END.
"""

GuardKind = Literal["fatal", "deferred", "skip"]
"""Discriminator for a ``pre()`` short-circuit.

- ``fatal`` — missing prerequisite; emit ``fatal_error`` and end.
- ``deferred`` — clarification deferred before any work.
- ``skip`` — this invocation should not run (e.g. resume-skip); no-op.
"""


@dataclass
class RouteDecision:
    """Typed route return from :meth:`LoopNode.post`.

    Replaces the free-form route-key dict (``plan_route``, ``assess_route``,
    ``evidence_gather_route``, ``after_record_route``, ``resume_synth``,
    ``planner_implement_handoff``) with one sum type. Routers pattern-match on
    :attr:`kind`; the bag-of-flags problem is solved structurally.
    """

    kind: RouteKind
    """Which route to take next."""

    next_phase: str | None = None
    """For ``proceed``: the target phase or internal station id."""

    clarification_origin: str | None = None
    """For ``await_user``: the non-return clarification origin (e.g.
    ``planner_subagent_review``). Return-to-sender origins use native
    ``interrupt()`` and do not set this."""

    state_patch: dict[str, Any] = field(default_factory=dict)
    """Scratch/state writes + emit side effects merged into the graph state."""

    def as_state_patch(self) -> dict[str, Any]:
        """Convert to the LangGraph state-dict the node returns.

        Maps ``kind`` to the ``last_outcome`` channel the existing routers
        read, so a migrated node is wire-compatible with legacy routers during
        the P2–P3 transition.
        """
        patch: dict[str, Any] = dict(self.state_patch)
        if self.kind == "fatal":
            patch.setdefault("last_outcome", "fatal")
        elif self.kind == "deferred":
            patch.setdefault("last_outcome", "deferred")
        elif self.kind == "terminal":
            # Terminal routes to complete/END; legacy routers read
            # ``plan_route == goal_done`` or ``after_record_route``. Migrated
            # nodes set the legacy channel in ``state_patch`` explicitly during
            # P2 transition; the default here only signals ``last_outcome``
            # absence (proceed-like) since terminal is a route, not an outcome.
            pass
        return patch


@dataclass
class GuardOutcome:
    """Short-circuit result from :meth:`LoopNode.pre`.

    When ``pre`` returns a ``GuardOutcome``, the ``__call__`` driver skips
    ``project``/``prompt``/``process``/``post`` and returns
    :meth:`as_state_patch` directly.
    """

    kind: GuardKind
    """Why the node is short-circuiting."""

    state_patch: dict[str, Any] = field(default_factory=dict)
    """Scratch/state writes to merge (e.g. ``pending_clarification`` clear)."""

    def as_state_patch(self) -> dict[str, Any]:
        """Convert to the LangGraph state-dict the node returns."""
        patch: dict[str, Any] = dict(self.state_patch)
        if self.kind == "fatal":
            patch.setdefault("last_outcome", "fatal")
        elif self.kind == "deferred":
            patch.setdefault("last_outcome", "deferred")
        # ``skip`` produces no outcome change — the node is a no-op this turn.
        return patch


@dataclass
class NodeResult:
    """Internal result from :meth:`LoopNode.process`, fed to :meth:`post`.

    Carries the raw output of the core work and any events that ``post``
    should emit. Distinct from :class:`RouteDecision` (what ``post`` returns
    to the router). Keeping them separate means ``process`` stays focused on
    *doing the work* while ``post`` owns *what to emit and where to route*.
    """

    payload: Any = None
    """Raw output of the core work (e.g. ``PlanResult``, ``AgentDecision``)."""

    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    """Events for ``post`` to emit via ``ctx.emit``."""


# --------------------------------------------------------------------------- #
# LoopNode base class
# --------------------------------------------------------------------------- #


class LoopNode(ABC):
    """Base class for every StrangeLoop graph node (RFC-903 §4.1).

    Subclasses override the stages they need. The base ``__call__`` driver
    runs::

        pre -> project -> prompt -> process -> post

    and centralizes the guard boilerplate (fatal, clarification, resume-skip,
    phase status) that is currently copy-pasted per node. P1 introduces the
    base with **minimal defaults** — no guard logic moves yet (that is P2–P3);
    the driver and typed contracts are the deliverable.

    Non-LLM nodes (``call_kind is None``) inherit no-op ``project``/``prompt``.
    LLM nodes override ``prompt`` to call ``GraphPromptWrapper.build_messages``
    with their call-specific parameters (goal, context, checkpoint).
    """

    station: str = ""
    """Canonical station id from :mod:`soothe.sloop.orchestrator.stations`."""

    call_kind: GraphCallKind | None = None  # type: ignore[assignment]
    """LLM call discriminator for ``GraphPromptWrapper``. ``None`` for non-LLM
    nodes (``validate_plan``, ``execute``, ``intake``, ``commit_plan``,
    ``check_limits``)."""

    #: Human-readable label for the ``plan_phase_status`` card. ``None`` = no
    #: status emission. Subclasses override or set as a class attribute.
    status_label: str | None = None

    # ------------------------------------------------------------------ #
    # Stages — subclasses override what they need
    # ------------------------------------------------------------------ #

    def pre(self, ctx: LoopRuntimeContext, state: dict[str, Any]) -> GuardOutcome | None:
        """Guards and setup. Return ``GuardOutcome`` to short-circuit.

        P1 default: no-op (returns ``None`` = proceed). P2–P3 centralize the
        fatal / pending-clarification / resume-skip / phase-status guards here.
        Subclasses may override to add specific prereq checks immediately.
        """
        return None

    def project(self, ctx: LoopRuntimeContext, state: dict[str, Any]) -> ProjectionResult:
        """DAG projection. Default: no-op for non-LLM nodes.

        P2 LLM-node migration overrides this to call
        ``GraphPromptWrapper.project_ledger(kind=self.call_kind, ...)``. P1
        returns an empty :class:`ProjectionResult` — no node uses the base yet.
        """
        from soothe.sloop.prompts.graph_wrapper import ProjectionResult

        return ProjectionResult()

    def prompt(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        proj: ProjectionResult,
    ) -> list[BaseMessage]:
        """Message assembly. Default: empty for non-LLM nodes.

        P2 LLM-node migration overrides this to call
        ``GraphPromptWrapper.build_messages(kind=self.call_kind, ...)`` with
        call-specific parameters (goal, context, checkpoint). P1 returns
        ``[]`` — no node uses the base yet.
        """
        return []

    @abstractmethod
    async def process(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        messages: list[BaseMessage],
    ) -> NodeResult:
        """Core work. The one abstract method every node must implement.

        Calls ``ctx.strange_loop.<phase>`` or ``ctx.strange_loop.executor``.
        May call ``interrupt()`` for return-to-sender clarification origins
        (P6). Returns a :class:`NodeResult` for :meth:`post` to act on.
        """

    def post(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        result: NodeResult,
    ) -> RouteDecision:
        """Writes, emit, route. Default: proceed with no state patch.

        P2–P3 migration overrides this to write scratch/state, emit events
        (the ``__call__`` driver emits ``result.events`` before calling
        ``post``), and return a typed :class:`RouteDecision` with the
        appropriate ``kind`` / ``next_phase``. P1 default is a no-op proceed
        — no node uses the base yet.
        """
        return RouteDecision(kind="proceed")

    # ------------------------------------------------------------------ #
    # Driver
    # ------------------------------------------------------------------ #

    async def __call__(self, ctx: LoopRuntimeContext, state: dict[str, Any]) -> dict[str, Any]:
        """Run the lifecycle: ``pre -> project -> prompt -> process -> post``.

        Returns the LangGraph state-dict patch. If ``pre`` short-circuits,
        skips the remaining stages.
        """
        guard = self.pre(ctx, state)
        if guard is not None:
            return guard.as_state_patch()
        proj = self.project(ctx, state)
        messages = self.prompt(ctx, state, proj)
        result = await self.process(ctx, state, messages)
        # Emit any events ``process`` queued (sync ``post`` can't await).
        for event_type, payload in result.events:
            await ctx.emit(event_type, payload)
        decision = self.post(ctx, state, result)
        return decision.as_state_patch()


# --------------------------------------------------------------------------- #
# Builder adapter
# --------------------------------------------------------------------------- #


def wrap_node(
    station: str,
    node: LoopNode | Any,
    ctx: LoopRuntimeContext,
) -> Any:
    """Adapt a ``LoopNode`` or legacy node function for LangGraph ``add_node``.

    LangGraph expects ``async def(state) -> dict``. StrangeLoop nodes are
    ``async def(ctx, state) -> dict``; the builder wraps each in a closure
    binding ``ctx``. This adapter detects whether ``node`` is a ``LoopNode``
    instance (uses the lifecycle driver) or a legacy callable (current
    behavior), so the graph can adopt the new base incrementally without
    touching existing nodes (IG P1 — non-breaking).

    Args:
        station: Canonical station id (for logging/debugging only).
        node: Either a :class:`LoopNode` instance or a legacy
            ``async def(ctx, state) -> dict`` function.
        ctx: The :class:`LoopRuntimeContext` to bind.

    Returns:
        ``async def(state) -> dict`` suitable for ``graph.add_node``.
    """

    if isinstance(node, LoopNode):
        # New lifecycle path — the driver runs pre/project/prompt/process/post.
        async def wrapped(state: dict[str, Any]) -> dict[str, Any]:
            return await node(ctx, state)

        wrapped.__name__ = f"node_{station}"
        wrapped.__doc__ = node.__doc__
        return wrapped

    # Legacy path — unchanged behavior (async def(ctx, state) -> dict).
    async def wrapped_legacy(state: dict[str, Any]) -> dict[str, Any]:
        return await node(ctx, state)

    wrapped_legacy.__name__ = f"node_{station}"
    wrapped_legacy.__doc__ = getattr(node, "__doc__", None)
    return wrapped_legacy


__all__ = [
    "GuardKind",
    "GuardOutcome",
    "LoopNode",
    "NodeResult",
    "RouteDecision",
    "RouteKind",
    "wrap_node",
]

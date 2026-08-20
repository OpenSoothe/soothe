"""Generalized StrangeLoop graph node lifecycle (RFC-903).

``LoopNode`` provides ``pre`` / ``project`` / ``prompt`` / ``process`` / ``post``.
``wrap_node`` adapts ``LoopNode`` instances or legacy ``async def(ctx, state)``
callables for LangGraph ``add_node``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from soothe.prompts.graph_wrapper import (
        GraphCallKind,
        ProjectionResult,
    )

    from .runtime_context import LoopRuntimeContext

_RouteKind = Literal["proceed", "await_user", "deferred", "fatal", "terminal"]
_GuardKind = Literal["fatal", "deferred", "skip"]


@dataclass
class RouteDecision:
    """Typed route return from :meth:`LoopNode.post`."""

    kind: _RouteKind
    next_phase: str | None = None
    clarification_origin: str | None = None
    state_patch: dict[str, Any] = field(default_factory=dict)

    def as_state_patch(self) -> dict[str, Any]:
        """Convert to the LangGraph state-dict the node returns."""
        patch: dict[str, Any] = dict(self.state_patch)
        if self.kind == "fatal":
            patch.setdefault("last_outcome", "fatal")
        elif self.kind == "deferred":
            patch.setdefault("last_outcome", "deferred")
        # ``terminal`` / ``proceed`` / ``await_user``: callers set channel keys
        # in ``state_patch`` explicitly when routers need them.
        return patch


@dataclass
class GuardOutcome:
    """Short-circuit result from :meth:`LoopNode.pre`."""

    kind: _GuardKind
    state_patch: dict[str, Any] = field(default_factory=dict)

    def as_state_patch(self) -> dict[str, Any]:
        """Convert to the LangGraph state-dict the node returns."""
        patch: dict[str, Any] = dict(self.state_patch)
        if self.kind == "fatal":
            patch.setdefault("last_outcome", "fatal")
        elif self.kind == "deferred":
            patch.setdefault("last_outcome", "deferred")
        return patch


@dataclass
class NodeResult:
    """Result from :meth:`LoopNode.process`, fed to :meth:`post`."""

    payload: Any = None
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


class LoopNode(ABC):
    """Base class for StrangeLoop graph nodes."""

    station: str = ""
    call_kind: GraphCallKind | None = None  # type: ignore[assignment]

    async def pre(self, ctx: LoopRuntimeContext, state: dict[str, Any]) -> GuardOutcome | None:
        """Guards and setup. Return ``GuardOutcome`` to short-circuit."""
        return None

    def project(self, ctx: LoopRuntimeContext, state: dict[str, Any]) -> ProjectionResult:
        """DAG projection. Default no-op for non-LLM nodes."""
        from soothe.prompts.graph_wrapper import ProjectionResult

        return ProjectionResult()

    def prompt(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        proj: ProjectionResult,
    ) -> list[BaseMessage]:
        """Message assembly. Default empty for non-LLM nodes."""
        return []

    @abstractmethod
    async def process(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        messages: list[BaseMessage],
    ) -> NodeResult:
        """Core work. Every node must implement this."""

    def post(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        result: NodeResult,
    ) -> RouteDecision:
        """Writes, emit, route. Default: proceed with no state patch."""
        return RouteDecision(kind="proceed")

    async def __call__(self, ctx: LoopRuntimeContext, state: dict[str, Any]) -> dict[str, Any]:
        """Run ``pre -> project -> prompt -> process -> post``."""
        guard = await self.pre(ctx, state)
        if guard is not None:
            return guard.as_state_patch()
        proj = self.project(ctx, state)
        messages = self.prompt(ctx, state, proj)
        result = await self.process(ctx, state, messages)
        for event_type, payload in result.events:
            await ctx.emit(event_type, payload)
        decision = self.post(ctx, state, result)
        return decision.as_state_patch()


def wrap_node(
    station: str,
    node: LoopNode | Any,
    ctx: LoopRuntimeContext,
) -> Any:
    """Adapt a ``LoopNode`` or legacy node function for LangGraph ``add_node``.

    Args:
        station: Canonical station id (for logging/debugging only).
        node: A :class:`LoopNode` instance or legacy ``async def(ctx, state)``.
        ctx: The :class:`LoopRuntimeContext` to bind.

    Returns:
        ``async def(state) -> dict`` suitable for ``graph.add_node``.
    """

    if isinstance(node, LoopNode):

        async def wrapped(state: dict[str, Any]) -> dict[str, Any]:
            return await node(ctx, state)

        wrapped.__name__ = f"node_{station}"
        wrapped.__doc__ = node.__doc__
        return wrapped

    async def wrapped_legacy(state: dict[str, Any]) -> dict[str, Any]:
        return await node(ctx, state)

    wrapped_legacy.__name__ = f"node_{station}"
    wrapped_legacy.__doc__ = getattr(node, "__doc__", None)
    return wrapped_legacy


__all__ = [
    "GuardOutcome",
    "LoopNode",
    "NodeResult",
    "RouteDecision",
    "wrap_node",
]

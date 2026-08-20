"""Unified loop-context projection: CE ledger → phase-adapted message list.

The Context Engine owns the raw phase-tagged message ledger (Source of Truth);
this module is the single projection layer that composes the history slice for
each StrangeLoop LLM call. Every phase produces the same shape:

    [preamble (ancestor pairs)] + [prior-goal terminal units] + [current-goal step history]

The phase envelope (system prompt + human message) is NOT the projector's job —
the caller appends it around the projected messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import BaseMessage

from soothe.sloop.orchestrator.stations import PHASE_PREAMBLE

if TYPE_CHECKING:
    from soothe.sloop.state.schemas import AgentDecision, LoopState, StepAction

ProjectionPhase = Literal["intake", "execute", "synthesis"]


@dataclass
class ProjectionSpec:
    """Inputs describing one LLM call's projection.

    ``loop_messages`` is passed separately to :meth:`LoopContextProjector.project`
    so callers can materialize the CE-backed ledger async (``await
    state.get_loop_messages()``) before projecting.
    """

    phase: ProjectionPhase
    state: LoopState | None = None  # execute only (mode resolution)
    step: StepAction | None = None  # execute only
    decision: AgentDecision | None = None  # execute only
    checkpoint: Any = None  # execute only
    checkpoint_message_ids: frozenset[str] | None = None  # execute only


@dataclass
class ProjectedContext:
    """Projected history messages plus provenance flags."""

    messages: list[BaseMessage] = field(default_factory=list)
    cross_goal_projected: bool = False
    predecessor_projected: bool = False
    mode: str | None = None
    completion_in_ledger: bool = False


def project_preamble_messages(
    loop_messages: list[BaseMessage],
    *,
    max_turns: int,
) -> list[BaseMessage]:
    """Return ancestor (user/ai) preamble pairs projected from the ledger.

    Preamble pairs are recorded with ``phase="preamble"`` by the daemon/autopilot
    before the graph runs; they are the cross-loop ancestor transcript. Bounded
    to the last ``max_turns`` turns (2 messages per turn).
    """
    if max_turns <= 0 or not loop_messages:
        return []
    preamble = [m for m in loop_messages if getattr(m, "phase", None) == PHASE_PREAMBLE]
    cap = max_turns * 2
    if len(preamble) <= cap:
        return preamble
    return preamble[-cap:]


class LoopContextProjector:
    """Single entry point for projecting the CE ledger into a message list."""

    def __init__(self, config: Any | None = None) -> None:
        self.config = config

    def project(
        self,
        loop_messages: list[BaseMessage],
        spec: ProjectionSpec,
        *,
        plan_cfg: Any | None = None,
    ) -> ProjectedContext:
        """Project the ledger history slice for one phase.

        Args:
            loop_messages: Materialized CE-backed ledger (``state.loop_messages``
                or ``await state.get_loop_messages()``).
            spec: Phase + execute-specific context.
            plan_cfg: Optional ``PlanPromptLedgerConfig`` override; defaults to the
                one derived from ``self.config``.

        Returns:
            :class:`ProjectedContext` with ordered history messages and flags.
        """
        from soothe.prompts.plan_ledger_projection import (
            project_execute_step_graph_input,
            project_last_goal_completion_for_intake,
            project_loop_messages_for_synthesis,
            projected_ledger_has_goal_completion,
        )

        cfg = plan_cfg if plan_cfg is not None else self._plan_cfg()
        prior_goal_tail = self._prior_goal_tail(cfg)
        preamble = project_preamble_messages(
            loop_messages,
            max_turns=self._preamble_max_turns(cfg),
        )

        if spec.phase == "intake":
            tail = project_last_goal_completion_for_intake(loop_messages, cfg, k=prior_goal_tail)
            return ProjectedContext(messages=[*preamble, *tail])

        if spec.phase == "execute":
            projected = project_execute_step_graph_input(
                loop_messages,
                state=spec.state,
                step=spec.step,
                decision=spec.decision,
                checkpoint=spec.checkpoint,
                soothe_config=self.config,
                checkpoint_message_ids=spec.checkpoint_message_ids,
            )
            return ProjectedContext(
                messages=[*preamble, *projected.messages],
                cross_goal_projected=projected.cross_goal_projected,
                predecessor_projected=projected.predecessor_projected,
                mode=projected.mode,
            )

        tail = project_loop_messages_for_synthesis(
            loop_messages,
            cfg,
            prior_goal_tail=prior_goal_tail,
        )
        messages = [*preamble, *tail]
        return ProjectedContext(
            messages=messages,
            completion_in_ledger=projected_ledger_has_goal_completion(messages),
        )

    def _plan_cfg(self) -> Any:
        if self.config is None:
            return None
        loop_cfg = getattr(getattr(self.config, "agent", None), "loop", None)
        return getattr(loop_cfg, "plan_prompt_ledger", None) if loop_cfg else None

    def _preamble_max_turns(self, cfg: Any | None) -> int:
        if cfg is None:
            return 12
        return int(getattr(cfg, "preamble_max_turns", 12) or 12)

    def _prior_goal_tail(self, cfg: Any | None) -> int:
        if cfg is None:
            return 3
        return int(getattr(cfg, "prior_goal_tail", 3) or 3)


__all__ = [
    "LoopContextProjector",
    "ProjectedContext",
    "ProjectionPhase",
    "ProjectionSpec",
    "project_preamble_messages",
]

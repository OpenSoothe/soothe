"""Hierarchical prompt builder with fragment composition.

Refactored to delegate to :class:`GraphPromptWrapper` so prompt injection
and message projection logic lives in exactly one place. ``PromptBuilder``
remains the public API consumed by ``planner.py``; it forwards to the
centralized wrapper internally.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import BaseMessage

from soothe.sloop.prompts.graph_wrapper import GraphPromptWrapper

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from soothe_sdk.protocols.planner import PlanContext

    from soothe.config import SootheConfig
    from soothe.context.projection import ContextBundle
    from soothe.sloop.state.schemas import LoopState

PlanPromptPhase = Literal["assess", "generate"]


class PromptBuilder:
    """Composes hierarchical prompts from fragments.

    Thin facade over :class:`GraphPromptWrapper`. The wrapper centralizes
    projection mode resolution, ledger slicing, system-message fragment
    selection, and human-message scenario assembly so all LLM-invoking
    nodes share one assembly pipeline.

    Structure (RFC-207):
        SystemMessage: environment, workspace, policies, instructions (static)
        HumanMessage: goal, evidence, prior conversation (dynamic)

    Uses prefetched fragments for cache optimization.
    """

    def __init__(self, config: SootheConfig | None = None) -> None:
        """Initialize builder with optional config.

        Args:
            config: Optional Soothe configuration
        """
        self.config = config
        self._wrapper = GraphPromptWrapper(config)

    def build_plan_messages(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        *,
        plan_phase: PlanPromptPhase = "assess",
        call_kind: PlannerCallKind | None = None,
        dag_context: str | None = None,
        context_bundle: ContextBundle | None = None,
        checkpoint: Any | None = None,
        exclude_goal_id: str | None = None,
        inline_assessment: Any | None = None,
        plan_gap: Any | None = None,
    ) -> list[BaseMessage]:
        """Build SystemMessage + projected ledger + task envelope (RFC-214 §4).

        Delegates to :class:`GraphPromptWrapper` for centralized projection
        and injection. The wrapper resolves projection mode, slices the ledger,
        selects the system-prompt fragment, and builds the scenario human message
        uniformly across all planner call kinds.
        """

        kind: PlannerCallKind = call_kind or ("generate" if plan_phase == "generate" else "assess")

        # Resolve assess-prompt config for plan_coverage and omit_prior_progress_hint.
        assess_prompt_cfg = (
            self.config.agent.loop.plan_evaluate_prompt if self.config is not None else None
        )
        plan_coverage = None
        if kind in ("assess", "gap"):
            from soothe.sloop.cognition.plan_step_safety import render_plan_coverage

            include_coverage = (
                assess_prompt_cfg.include_plan_coverage if assess_prompt_cfg is not None else True
            )
            if include_coverage:
                plan_coverage = render_plan_coverage(state) or None

        omit_prior_progress_hint = (
            assess_prompt_cfg.omit_prior_progress_hint if assess_prompt_cfg is not None else True
        )

        return self._wrapper.build_messages(
            kind=kind,
            goal=goal,
            state=state,
            context=context,
            context_bundle=context_bundle,
            checkpoint=checkpoint,
            exclude_goal_id=exclude_goal_id,
            dag_context=dag_context,
            inline_assessment=inline_assessment,
            plan_gap=plan_gap,
            plan_coverage=plan_coverage,
            omit_prior_progress_hint=omit_prior_progress_hint,
            recent_messages=context.recent_messages if context is not None else None,
        )

    def _build_system_message(
        self,
        context: PlanContext,
        state: LoopState | None = None,
        *,
        plan_phase: PlanPromptPhase = "assess",
        call_kind: PlannerCallKind | None = None,
        context_bundle: ContextBundle | None = None,
    ) -> str:
        """Construct static context: policies and phase instructions.

        Delegates to :class:`GraphPromptWrapper.build_system_message`.
        """

        kind: PlannerCallKind = call_kind or ("generate" if plan_phase == "generate" else "assess")
        return self._wrapper.build_system_message(
            kind=kind,
            context=context,
            state=state,
            context_bundle=context_bundle,
            recent_messages=context.recent_messages if context is not None else None,
        )

    def _build_plan_context_human_text(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        *,
        plan_phase: PlanPromptPhase = "assess",
        call_kind: PlannerCallKind | None = None,
        dag_context: str | None = None,
        context_bundle: ContextBundle | None = None,
        projection_mode: str | None = None,
        completion_in_ledger: bool = False,
        prior_goals_override: list[Any] | None = None,
        inline_assessment: Any | None = None,
        plan_coverage: str | None = None,
        omit_prior_progress_hint: bool = True,
        plan_gap: Any | None = None,
    ) -> str:
        """Construct plan-context human text without ledger (RFC-214).

        Delegates to :class:`GraphPromptWrapper._build_human_text`.
        """

        kind: PlannerCallKind = call_kind or ("generate" if plan_phase == "generate" else "assess")
        return self._wrapper._build_human_text(
            kind=kind,
            goal=goal,
            state=state,
            context=context,
            dag_context=dag_context,
            context_bundle=context_bundle,
            projection_mode=projection_mode,
            completion_in_ledger=completion_in_ledger,
            prior_goals_override=prior_goals_override,
            inline_assessment=inline_assessment,
            plan_coverage=plan_coverage,
            omit_prior_progress_hint=omit_prior_progress_hint,
            plan_gap=plan_gap,
        )


# Backward-compatible re-exports for existing callers (executor.py, planner.py,
# tests) that import these helpers from ``builder``. The canonical definitions
# now live in ``graph_wrapper`` alongside the centralized assembly pipeline.
from soothe.sloop.prompts.graph_wrapper import (  # noqa: E402, F401
    _format_dag_context,
    _prior_goals_from_checkpoint,
)
from soothe.sloop.prompts.planner_assembly import (  # noqa: E402
    PlannerCallKind,
)

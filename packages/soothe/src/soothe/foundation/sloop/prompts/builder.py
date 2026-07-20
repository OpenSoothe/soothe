"""Hierarchical prompt builder with fragment composition."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import BaseMessage, SystemMessage

from soothe.foundation.sloop.prompts.plan_ledger_projection import (
    project_continuation_assess_ledger,
    project_planner_ledger,
    project_planner_ledger_for_assess,
    projected_ledger_has_goal_completion,
    resolve_planner_projection_mode,
)
from soothe.foundation.sloop.prompts.planner_assembly import (
    PlannerCallKind,
    goal_preview_text,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from soothe_nano.protocols.planner import PlanContext

    from soothe.config import SootheConfig
    from soothe.foundation.context.projection import ContextBundle
    from soothe.foundation.sloop.state.schemas import LoopState

PlanPromptPhase = Literal["assess", "generate"]

_PRIOR_CONVERSATION_TAGS: tuple[tuple[str, Literal["human", "ai"]], ...] = (
    ("USER", "human"),
    ("ASSISTANT", "ai"),
)


def _parse_prior_conversation_xml(msg_xml: str) -> tuple[Literal["human", "ai"], str] | None:
    """Parse ``<USER>`` / ``<ASSISTANT>`` blocks from prior conversation projection."""
    msg_xml = msg_xml.strip()
    for tag, role in _PRIOR_CONVERSATION_TAGS:
        open_tag, close_tag = f"<{tag}>", f"</{tag}>"
        if msg_xml.startswith(open_tag) and msg_xml.endswith(close_tag):
            return role, msg_xml[len(open_tag) : -len(close_tag)].strip()
    return None


def _prior_goals_from_checkpoint(
    checkpoint: Any | None,
    *,
    exclude_goal_id: str | None,
) -> list[Any]:
    """Build ``PriorGoalSummary`` rows from checkpoint goal index (metadata only)."""
    from soothe.foundation.context.projection import PriorGoalSummary

    if checkpoint is None:
        return []
    out: list[PriorGoalSummary] = []
    for rec in checkpoint.goal_history:
        if exclude_goal_id and rec.goal_id == exclude_goal_id:
            continue
        if rec.status not in ("completed", "cancelled", "failed"):
            continue
        out.append(
            PriorGoalSummary(
                goal_id=rec.goal_id,
                description=rec.goal_id,
                status=rec.status,
                step_summary="",
                completion_text="",
            )
        )
    return out


def _enrich_prior_goals(
    prior_goals: list[Any],
    checkpoint: Any | None,
    *,
    exclude_goal_id: str | None,
) -> list[Any]:
    """Return prior goals unchanged — completion text is resolved from CE/ledger."""
    _ = checkpoint, exclude_goal_id
    return prior_goals


def _format_dag_context(dag_ctx: Any) -> str:
    """Format DagPlanningContext as plain-text DAG STATUS section for prompt injection."""
    if not dag_ctx or not dag_ctx.has_prior_state:
        return ""
    from soothe.foundation.sloop.prompts.user_message import _render_dag_status as _render

    return _render(dag_ctx)


class PromptBuilder:
    """Composes hierarchical prompts from fragments.

    Internal API for Soothe prompt construction.
    Not exposed to users for configuration.

    Structure (RFC-207):
        SystemMessage: environment, workspace, policies, instructions (static)
        HumanMessage: goal, evidence, prior conversation (dynamic)

    IG-183: Uses prefetched fragments for cache optimization.
    """

    def __init__(self, config: SootheConfig | None = None) -> None:
        """Initialize builder with optional config.

        Args:
            config: Optional Soothe configuration
        """
        self.config = config

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
        """Build SystemMessage + projected ledger + task envelope (RFC-214 §4, IG-538)."""
        from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage

        kind: PlannerCallKind = call_kind or ("generate" if plan_phase == "generate" else "assess")
        projection_mode = resolve_planner_projection_mode(state)
        ledger_cfg = self.config.agent.loop.plan_prompt_ledger if self.config is not None else None
        assess_prompt_cfg = (
            self.config.agent.loop.plan_assess_prompt if self.config is not None else None
        )
        if kind == "continuation":
            projected = project_continuation_assess_ledger(state.loop_messages, ledger_cfg)
        elif kind in ("assess", "gap"):
            projected = project_planner_ledger_for_assess(
                state.loop_messages,
                projection_mode,
                ledger_cfg,
                soothe_config=self.config,
            )
        else:
            projected = project_planner_ledger(
                state.loop_messages,
                projection_mode,
                ledger_cfg,
                soothe_config=self.config,
            )
        completion_in_ledger = projected_ledger_has_goal_completion(projected)

        prior_goals = _enrich_prior_goals(
            list(context_bundle.prior_goals)
            if context_bundle and context_bundle.prior_goals
            else [],
            checkpoint,
            exclude_goal_id=exclude_goal_id,
        )
        if not prior_goals and projection_mode == "new_goal":
            prior_goals = _prior_goals_from_checkpoint(checkpoint, exclude_goal_id=exclude_goal_id)

        system_content = self._build_system_message(
            context,
            state,
            call_kind=kind,
            context_bundle=None if kind in ("assess", "gap") else context_bundle,
        )
        plan_coverage = None
        if kind in ("assess", "gap"):
            from soothe.foundation.sloop.cognition.plan_step_safety import render_plan_coverage

            include_coverage = (
                assess_prompt_cfg.include_plan_coverage if assess_prompt_cfg is not None else True
            )
            if include_coverage:
                plan_coverage = render_plan_coverage(state) or None
        human_content = self._build_plan_context_human_text(
            goal,
            state,
            context,
            call_kind=kind,
            dag_context=dag_context,
            context_bundle=context_bundle,
            projection_mode=projection_mode,
            completion_in_ledger=completion_in_ledger,
            prior_goals_override=prior_goals or None,
            inline_assessment=inline_assessment,
            plan_coverage=plan_coverage,
            omit_prior_progress_hint=(
                assess_prompt_cfg.omit_prior_progress_hint
                if assess_prompt_cfg is not None
                else True
            ),
            plan_gap=plan_gap,
        )

        out: list[BaseMessage] = [SystemMessage(content=system_content)]
        out.extend(projected)
        if len(projected) != len(state.loop_messages):
            logger.debug(
                "Plan messages: ledger projection len=%d (raw=%d) kind=%s mode=%s",
                len(projected),
                len(state.loop_messages),
                kind,
                projection_mode,
            )

        if context.recent_messages and kind not in ("assess", "gap"):
            for msg_xml in context.recent_messages:
                parsed = _parse_prior_conversation_xml(msg_xml)
                if parsed is None:
                    continue
                role, content = parsed
                if role == "human":
                    out.append(
                        LoopHumanMessage(
                            content=content,
                            thread_id=state.thread_id,
                            iteration=None,
                            phase="execute_step",
                        )
                    )
                else:
                    out.append(
                        LoopAIMessage(
                            content=content,
                            thread_id=state.thread_id,
                            iteration=None,
                            phase="execute_step",
                        )
                    )

        if human_content.strip():
            phase = (
                "plan_gap_analysis"
                if kind == "gap"
                else ("plan_assess" if kind in ("assess", "continuation") else "plan_generate")
            )
            out.append(
                LoopHumanMessage(
                    content=human_content,
                    thread_id=state.thread_id,
                    iteration=state.iteration,
                    goal_summary=goal[:200],
                    phase=phase,
                )
            )
        return out

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

        Maps RFC-206 SYSTEM_CONTEXT + INSTRUCTIONS layers to SystemMessage.
        Uses prefetched fragments for cache optimization (IG-183).

        Workspace path semantics, ENVIRONMENT, WORKSPACE metadata, and
        AGENT_INSTRUCTIONS live on execute-step CoreAgent system prompts only —
        plan-assess / plan-generate stay lean and workspace-agnostic for cache
        stability.

        Section ordering:
        - **assess** (IG-372): PLAN_ASSESS_INSTRUCTIONS, then conditional blocks.
        - **generate**: EXECUTION_POLICIES, PLAN_GENERATE_INSTRUCTIONS, conditional blocks.
        - **continuation**: PLAN_CONTINUATION_DISCRIMINATE, conditional blocks.

        Goal is supplied in the plan-context user message (``GOAL:``), not in the system prompt.

        Args:
            context: Planning context with workspace, capabilities
            state: Optional loop state for iteration limits and capability context
            plan_phase: Which planner LLM call this system prompt serves (IG-372).
            context_bundle: Optional ContextBundle (RFC-624). When provided, project/agent/memory
                instructions from the bundle replace or supplement disk reads.
        """
        from soothe.foundation.sloop.prompts.fragments import (
            EXECUTION_POLICIES_FRAGMENT,
            PLAN_ASSESS_INSTRUCTIONS_FRAGMENT,
            PLAN_CONTINUATION_DISCRIMINATE_FRAGMENT,
            PLAN_GAP_ANALYSIS_INSTRUCTIONS_FRAGMENT,
            PLAN_GENERATE_INSTRUCTIONS_FRAGMENT,
        )
        from soothe.foundation.sloop.prompts.system_templates import build_response_language_hint

        parts: list[str] = []
        kind: PlannerCallKind = call_kind or ("generate" if plan_phase == "generate" else "assess")

        if kind == "continuation":
            parts.append(PLAN_CONTINUATION_DISCRIMINATE_FRAGMENT + "\n")
        elif kind == "assess":
            parts.append(PLAN_ASSESS_INSTRUCTIONS_FRAGMENT + "\n")
        elif kind == "gap":
            parts.append(PLAN_GAP_ANALYSIS_INSTRUCTIONS_FRAGMENT + "\n")
        else:
            parts.append(EXECUTION_POLICIES_FRAGMENT + "\n")
            parts.append(PLAN_GENERATE_INSTRUCTIONS_FRAGMENT + "\n")

        language = getattr(state, "response_language", None) if state is not None else None
        parts.append(build_response_language_hint(language) + "\n")

        # RFC-624: Supplementary instructions from ContextBundle (plan cache-stable:
        # agent/project rules stay on execute-type system prompts only).
        if context_bundle is not None and kind not in ("assess", "gap"):
            if context_bundle.memory_instructions:
                parts.append(
                    "<MEMORY_INSTRUCTIONS>\n"
                    + context_bundle.memory_instructions
                    + "\n</MEMORY_INSTRUCTIONS>\n"
                )

        # Prior conversation follow-up policy (static when prior conversation exists)
        if context.recent_messages and kind not in ("assess", "gap"):
            parts.append(
                "<FOLLOW_UP_POLICY>\n"
                'Prior-thread goals: status MUST NOT be "done" until execution produced the '
                "requested output; include at least one execute_steps item that performs the work; "
                "do not claim completion without execution evidence.\n"
                "</FOLLOW_UP_POLICY>\n"
            )

        return "\n".join(parts)

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

        StrangeLoop ledger messages are appended separately in ``build_plan_messages`` so the
        plan model sees native human/AI turns instead of a single flattened block.
        Execute-step evidence lives in those ledger messages (IG-368).

        Uses scenario-based structured text (GOAL/CONTEXT/TASK) instead
        of XML envelopes.

        Args:
            goal: User's goal description
            state: Current loop state with optional plan snapshot
            context: Planning context (unused now - prior conversation is in ledger)
            plan_phase: When ``generate``, append step-id hint and optional DAG context.
            dag_context: Optional plain-text DAG context for progressive planning.
            context_bundle: Optional ContextBundle from ContextEngine.project().

        Returns:
            Formatted prompt string for the plan-context ``LoopHumanMessage``.
        """
        from soothe.foundation.sloop.prompts.user_message import UserMessageBuilder
        from soothe.foundation.sloop.state.schemas import next_goal_local_step_id_start

        builder = UserMessageBuilder()
        kind: PlannerCallKind = call_kind or ("generate" if plan_phase == "generate" else "assess")
        mode = projection_mode or resolve_planner_projection_mode(state)

        if kind == "continuation":
            return builder.build_plan_continuation_message(
                goal,
                context_bundle=context_bundle,
                display_goal=goal_preview_text(goal) if mode == "new_goal" else None,
                completion_in_ledger=completion_in_ledger,
                prior_goals_override=prior_goals_override,
            )

        step_id_hint = None
        step_anchor_registry = None
        if kind == "generate":
            from soothe.foundation.sloop.cognition.step_anchor_registry import (
                build_step_anchor_registry,
            )

            goal_node = context_bundle.active_goal if context_bundle is not None else None
            if goal_node is not None or state.step_results:
                step_anchor_registry = build_step_anchor_registry(
                    goal_node=goal_node,
                    state=state,
                )
            nxt = next_goal_local_step_id_start(state)
            if nxt > 1:
                width = max(2, len(str(nxt + 1)))
                ex_a = str(nxt).zfill(width)
                ex_b = str(nxt + 1).zfill(width)
                step_id_hint = (
                    f"This goal already used lower step indices; use the next unused local "
                    f"step ids starting with {ex_a} (e.g. {ex_a}, {ex_b}, …), not 01/02 again."
                )

        common_kwargs = dict(
            goal=goal,
            dag_context=dag_context,
            skill_context=state.skill_context,
            prior_progress=getattr(state, "prior_progress", None),
            current_iteration=state.iteration,
            context_bundle=context_bundle,
            display_goal=goal_preview_text(goal) if mode == "new_goal" else None,
            projection_mode=mode,
            completion_in_ledger=completion_in_ledger,
            prior_goals_override=prior_goals_override,
        )

        if kind == "assess":
            last_assessment = None
            if context_bundle is not None and context_bundle.active_goal is not None:
                last_assessment = context_bundle.active_goal.last_assessment
            return builder.build_plan_assess_message(
                **common_kwargs,
                plan_coverage=plan_coverage,
                omit_prior_progress_hint=omit_prior_progress_hint,
                last_assessment=last_assessment,
                plan_gap=plan_gap,
            )
        if kind == "gap":
            return builder.build_plan_gap_message(
                goal=goal,
                prior_progress=getattr(state, "prior_progress", None),
                current_iteration=state.iteration,
                projection_mode=mode,
                plan_coverage=plan_coverage,
                omit_prior_progress_hint=omit_prior_progress_hint,
            )
        generate_kwargs: dict[str, Any] = {
            **common_kwargs,
            "step_id_hint": step_id_hint,
            "step_anchor_registry": step_anchor_registry,
        }
        if inline_assessment is not None:
            generate_kwargs["assessment_status"] = getattr(inline_assessment, "status", None)
            generate_kwargs["assessment_progress"] = getattr(
                inline_assessment, "goal_progress", None
            )
        if plan_gap is not None:
            generate_kwargs["plan_gap"] = plan_gap
        from soothe.foundation.sloop.engine.thread_selection import (
            resolve_user_requested_wire_subagent,
        )

        generate_kwargs["user_wire_subagent"] = resolve_user_requested_wire_subagent(
            routing_classification=context.routing_classification,
            intent=getattr(state, "intent", None),
        )
        return builder.build_plan_generate_message(**generate_kwargs)

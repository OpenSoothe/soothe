"""Hierarchical prompt builder with fragment composition."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import BaseMessage, SystemMessage

from soothe.foundation.sloop.prompts.plan_ledger_projection import (
    project_planner_ledger,
    projected_ledger_has_goal_completion,
    resolve_planner_projection_mode,
)
from soothe.foundation.sloop.prompts.planner_assembly import (
    PlannerCallKind,
    goal_preview_text,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.foundation.context.projection import ContextBundle
    from soothe.foundation.sloop.state.schemas import LoopState
    from soothe.protocols.planner import PlanContext

PlanPromptPhase = Literal["assess", "generate"]


def _prior_goals_from_checkpoint(
    checkpoint: Any | None,
    *,
    exclude_goal_id: str | None,
) -> list[Any]:
    """Build ``PriorGoalSummary`` rows from checkpoint goal history for envelope trees."""
    from soothe.foundation.context.projection import PriorGoalSummary

    if checkpoint is None:
        return []
    out: list[PriorGoalSummary] = []
    for rec in checkpoint.goal_history:
        if exclude_goal_id and rec.goal_id == exclude_goal_id:
            continue
        if rec.status not in ("completed", "cancelled", "failed"):
            continue
        description = (rec.goal_text or "").strip()
        if not description:
            continue
        out.append(
            PriorGoalSummary(
                goal_id=rec.goal_id,
                description=description,
                status=rec.status,
                step_summary="",
                completion_text=(rec.goal_completion or "").strip(),
            )
        )
    return out


def _enrich_prior_goals(
    prior_goals: list[Any],
    checkpoint: Any | None,
    *,
    exclude_goal_id: str | None,
) -> list[Any]:
    """Fill missing ``completion_text`` from checkpoint goal records."""
    if not prior_goals or checkpoint is None:
        return prior_goals
    from soothe.foundation.sloop.engine.continuation_context import (
        checkpoint_completions_by_goal_text,
    )

    by_text = checkpoint_completions_by_goal_text(checkpoint, exclude_goal_id=exclude_goal_id)
    enriched: list[Any] = []
    for pg in prior_goals:
        completion = (pg.completion_text or "").strip()
        if not completion:
            completion = by_text.get((pg.description or "").strip(), "")
        if completion and completion != (pg.completion_text or ""):
            enriched.append(pg.model_copy(update={"completion_text": completion}))
        else:
            enriched.append(pg)
    return enriched


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
    ) -> list[BaseMessage]:
        """Build SystemMessage + projected ledger + task envelope (RFC-214 §4, IG-538)."""
        from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage

        kind: PlannerCallKind = call_kind or ("generate" if plan_phase == "generate" else "assess")
        projection_mode = resolve_planner_projection_mode(state)
        ledger_cfg = self.config.agent.loop.plan_prompt_ledger if self.config is not None else None
        projected = project_planner_ledger(state.loop_messages, projection_mode, ledger_cfg)
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
            context_bundle=context_bundle,
        )
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

        if context.recent_messages:
            for msg_xml in context.recent_messages:
                msg_xml = msg_xml.strip()
                if msg_xml.startswith("<user>") and msg_xml.endswith("</user>"):
                    content = msg_xml[6:-7].strip()
                    out.append(
                        LoopHumanMessage(
                            content=content,
                            thread_id=state.thread_id,
                            iteration=None,
                            phase="execute_step",
                        )
                    )
                elif msg_xml.startswith("<assistant>") and msg_xml.endswith("</assistant>"):
                    content = msg_xml[11:-12].strip()
                    out.append(
                        LoopAIMessage(
                            content=content,
                            thread_id=state.thread_id,
                            iteration=None,
                            phase="execute_step",
                        )
                    )

        if human_content.strip():
            phase = "plan_assess" if kind in ("assess", "continuation") else "plan_generate"
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
        """Construct static context: policies, instructions, environment, workspace.

        Maps RFC-206 SYSTEM_CONTEXT + INSTRUCTIONS layers to SystemMessage.
        Uses prefetched fragments for cache optimization (IG-183).

        Reordered per IG-364: Static-always fragments first, conditional static sections,
        then ENVIRONMENT (global), then WORKSPACE (dynamic project-specific).

        Section ordering (optimized for prompt caching):
        - **assess** (IG-372): PLAN_ASSESS_INSTRUCTIONS only, then conditional blocks, ENVIRONMENT,
          WORKSPACE.
        - **generate**: EXECUTION_POLICIES, PLAN_GENERATE_INSTRUCTIONS (schema-aligned PlanGeneration
          only), then conditional blocks, ENVIRONMENT, WORKSPACE.

        Goal is supplied in the plan-context user message
        (``GOAL:``), not in the system prompt.

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
            PLAN_GENERATE_INSTRUCTIONS_FRAGMENT,
        )
        from soothe.foundation.sloop.prompts.system_templates import RESPONSE_LANGUAGE_HINT_FRAGMENT

        parts: list[str] = []
        kind: PlannerCallKind = call_kind or ("generate" if plan_phase == "generate" else "assess")

        if kind == "continuation":
            parts.append(PLAN_CONTINUATION_DISCRIMINATE_FRAGMENT + "\n")
        elif kind == "assess":
            parts.append(PLAN_ASSESS_INSTRUCTIONS_FRAGMENT + "\n")
        else:
            parts.append(EXECUTION_POLICIES_FRAGMENT + "\n")
            parts.append(PLAN_GENERATE_INSTRUCTIONS_FRAGMENT + "\n")

        # Language directive: cache-stable, applies to all phases.
        parts.append(RESPONSE_LANGUAGE_HINT_FRAGMENT + "\n")

        # Conditional static sections (present based on context).
        # WORKSPACE_RULES apply only to plan-generate: plan-assess is a meta-decision
        # (status/progress/next_action) that does not author steps touching the workspace.
        # Project rules (AGENTS.md / CLAUDE.md) are injected on execute via CoreAgent
        # system prompt, not plan-generate — keeps the planner cache-stable and lean.
        if context.workspace and kind == "generate":
            parts.append(
                "<WORKSPACE_RULES>\n"
                "Project root is under <WORKSPACE><root>. Filesystem tools: workspace-relative "
                "or host-absolute paths under that root. Shell tools (run_command, run_python): "
                "cwd = workspace root; leading '/' in shell = host root — use '.' or relative paths.\n"
                "- For architecture/codebase/structure goals: inspect this directory immediately.\n"
                "- Do NOT ask the user for a local path, GitHub URL, or file upload unless the goal "
                "names a different project outside this directory.\n"
                "- Do NOT tell the user you need them to share the project first — it is already here.\n"
                "</WORKSPACE_RULES>\n"
            )

        # RFC-624: Supplementary instructions from ContextBundle
        if context_bundle is not None:
            if context_bundle.agent_instructions:
                parts.append(
                    "<AGENT_INSTRUCTIONS>\n"
                    + context_bundle.agent_instructions
                    + "\n</AGENT_INSTRUCTIONS>\n"
                )
            if context_bundle.memory_instructions:
                parts.append(
                    "<MEMORY_INSTRUCTIONS>\n"
                    + context_bundle.memory_instructions
                    + "\n</MEMORY_INSTRUCTIONS>\n"
                )

        # Prior conversation follow-up policy (static when prior conversation exists)
        if context.recent_messages:
            parts.append(
                "<FOLLOW_UP_POLICY>\n"
                'Prior-thread goals: status MUST NOT be "done" until execution produced the '
                "requested output; include at least one execute_steps item that performs the work; "
                "do not claim completion without execution evidence.\n"
                "</FOLLOW_UP_POLICY>\n"
            )

        # Environment section (after REASONING_STANDARDS, before WORKSPACE)
        if self.config is not None:
            from soothe.foundation.sloop.prompts.context_xml import build_soothe_environment_section

            model = self.config.resolve_model("default")
            parts.append(build_soothe_environment_section(model=model) + "\n")

        # Workspace section (dynamic, placed last)
        if context.workspace:
            from soothe.foundation.sloop.prompts.context_xml import build_soothe_workspace_section

            parts.append(build_soothe_workspace_section(Path(context.workspace)) + "\n")

        return "\n".join(parts)

    def _build_human_message(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> str:
        """Construct dynamic task: goal, working memory, prior conversation.

        Maps RFC-206 USER_TASK layer to HumanMessage.

        Execution narrative for Plan is supplied via ``state.loop_messages`` in
        ``build_plan_messages`` (RFC-214), not duplicated here (IG-368).
        """
        parts: list[str] = []

        # Goal line for non-plan human paths (plan phase uses ``GOAL:`` on plan-context human).
        parts.append(f"Goal: {goal}\n")

        # Working memory excerpt (RFC-203)
        if context.working_memory_excerpt:
            parts.append("\n<WORKING_MEMORY>")
            parts.append(
                "Structured scratchpad for this goal — treat as authoritative for what was already inspected. "
                "Prefer read_file on referenced paths instead of repeating large listings.\n"
            )
            parts.append(context.working_memory_excerpt)
            parts.append("</WORKING_MEMORY>\n")

        # Prior conversation (IG-128, RFC-209)
        # Always inject prior conversation when available (same thread_id for all executions)
        if context.recent_messages:
            parts.append("\n<PRIOR_CONVERSATION>\n")
            parts.append(
                "Recent messages in this thread before the current goal. The user may refer to this content "
                '(e.g. "translate that", "summarize the above", "shorter").\n\n'
            )
            for msg_xml in context.recent_messages:
                parts.append(msg_xml)
                parts.append("\n")
            parts.append("</PRIOR_CONVERSATION>\n")

        # IG-148: Simplified previous plan assessment (status + progress + next action only)
        prev = state.previous_plan
        if prev:
            from soothe.foundation.sloop.utils.plan_action_text import resolve_plan_action_text

            parts.append("\nPREVIOUS ASSESSMENT (continuity):")
            parts.append(f"- Status: {prev.status}, Progress: {prev.goal_progress:.0%}")
            prev_action = resolve_plan_action_text(prev)
            if prev_action:
                parts.append(f"- Next action: {prev_action}")

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
        display_goal = goal_preview_text(goal) if mode == "new_goal" else None

        if kind == "continuation":
            return builder.build_plan_continuation_message(
                goal,
                context_bundle=context_bundle,
                display_goal=display_goal,
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
            display_goal=display_goal,
            projection_mode=mode,
            completion_in_ledger=completion_in_ledger,
            prior_goals_override=prior_goals_override,
        )

        if kind == "assess":
            return builder.build_plan_assess_message(**common_kwargs)
        return builder.build_plan_generate_message(
            **common_kwargs,
            step_id_hint=step_id_hint,
            step_anchor_registry=step_anchor_registry,
        )

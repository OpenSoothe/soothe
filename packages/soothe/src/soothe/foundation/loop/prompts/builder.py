"""Hierarchical prompt builder with fragment composition."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import BaseMessage, SystemMessage

from soothe.foundation.loop.prompts.plan_ledger_projection import project_loop_messages_for_plan

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.context.projection import ContextBundle
    from soothe.foundation.loop.state.schemas import LoopState
    from soothe.protocols.planner import PlanContext

PlanPromptPhase = Literal["assess", "generate"]


def _format_dag_context(dag_ctx: Any) -> str:
    """Format DagPlanningContext as plain-text DAG STATUS section for prompt injection."""
    if not dag_ctx or not dag_ctx.has_prior_state:
        return ""
    from soothe.foundation.loop.prompts.user_message import _render_dag_status as _render

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
        dag_context: str | None = None,
        context_bundle: ContextBundle | None = None,
    ) -> list[BaseMessage]:
        """Build SystemMessage + plan context + ledger for Plan phase (RFC-207, RFC-214).

        Constructs proper message type separation:
        - SystemMessage: environment, workspace, policies, instructions, loop config, capabilities.
        - Projected ``state.loop_messages`` ledger (IG-380): native ``LoopHumanMessage`` /
          ``LoopAIMessage`` turns, optionally tail-trimmed when ``agentic.plan_prompt_ledger`` caps
          are set; persisted ``loop_messages`` are never modified.
        - LoopHumanMessage: ``GOAL:`` (goal) for both ``assess`` and
          ``generate``, plus optional ``<PRIOR_CONVERSATION>`` when ``recent_messages`` is set
          (IG-371: no WM block on this human), and optional ``DAG STATUS:`` for generate phase.

        Ledger precedes the plan-context human so ``plan-assess`` / ``plan-generate`` see execute
        evidence as prior turns, then goal/iteration context in the following user message.

        Args:
            goal: User's goal description
            state: Current loop state with ledger, plan metadata
            context: Planning context with workspace, capabilities
            plan_phase: ``assess`` = instructions aligned to ``StatusAssessment``; ``generate`` =
                execution policies + instructions aligned to ``PlanGeneration`` only (IG-372, IG-329).
            dag_context: Optional XML-formatted DAG context for progressive planning (generate phase).
            context_bundle: Optional ContextBundle from ContextEngine.project() (RFC-624).
                When provided, supplementary context (goal lineage, progress, instructions)
                is injected into the prompt. When None, behavior is unchanged.

        Returns:
            Messages to send to the plan LLM: system, ledger copies, prior thread messages,
            then optional plan-context human.
        """
        from soothe.foundation.loop.utils.messages import LoopAIMessage, LoopHumanMessage

        system_content = self._build_system_message(
            context,
            state,
            plan_phase=plan_phase,
            context_bundle=context_bundle,
        )
        human_content = self._build_plan_context_human_text(
            goal,
            state,
            context,
            plan_phase=plan_phase,
            dag_context=dag_context,
            context_bundle=context_bundle,
        )

        out: list[BaseMessage] = [SystemMessage(content=system_content)]
        # RFC-214: execute ledger as real messages (IG-380: optional projection for plan caps).
        ledger_cfg = None
        if self.config is not None:
            ledger_cfg = self.config.agent.loop.plan_prompt_ledger
        projected = project_loop_messages_for_plan(state.loop_messages, ledger_cfg)
        out.extend(projected)
        if len(projected) != len(state.loop_messages):
            logger.debug(
                "Plan messages: ledger projection len=%d (raw=%d) phase=%s",
                len(projected),
                len(state.loop_messages),
                plan_phase,
            )

        # RFC-214: Convert prior thread messages from XML strings to native ledger turns
        # This maximizes cache hits - prior conversation is native message turns, not XML block
        if context.recent_messages:
            for msg_xml in context.recent_messages:
                # Parse XML strings like "<user>\n...\n</user>" into proper messages
                msg_xml = msg_xml.strip()
                if msg_xml.startswith("<user>") and msg_xml.endswith("</user>"):
                    content = msg_xml[6:-7].strip()  # Strip <user> and </user> tags
                    out.append(
                        LoopHumanMessage(
                            content=content,
                            thread_id=state.thread_id,
                            iteration=None,
                            phase="execute_step",  # Prior thread messages are execute-phase
                        )
                    )
                elif msg_xml.startswith("<assistant>") and msg_xml.endswith("</assistant>"):
                    content = msg_xml[11:-12].strip()  # Strip <assistant> and </assistant> tags
                    out.append(
                        LoopAIMessage(
                            content=content,
                            thread_id=state.thread_id,
                            iteration=None,
                            phase="execute_step",
                        )
                    )

        if human_content.strip():
            out.append(
                LoopHumanMessage(
                    content=human_content,
                    thread_id=state.thread_id,
                    iteration=state.iteration,
                    goal_summary=goal[:200],
                    phase="plan_assess" if plan_phase == "assess" else "plan_generate",  # RFC-214
                )
            )
        return out

    def _build_system_message(
        self,
        context: PlanContext,
        state: LoopState | None = None,
        *,
        plan_phase: PlanPromptPhase = "assess",
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
        from soothe.foundation.loop.prompts.fragments import (
            EXECUTION_POLICIES_FRAGMENT,
            PLAN_ASSESS_INSTRUCTIONS_FRAGMENT,
            PLAN_GENERATE_INSTRUCTIONS_FRAGMENT,
        )
        from soothe.foundation.loop.prompts.system_templates import RESPONSE_LANGUAGE_HINT_FRAGMENT

        parts: list[str] = []

        if plan_phase == "assess":
            parts.append(PLAN_ASSESS_INSTRUCTIONS_FRAGMENT + "\n")
        else:
            # Plan generation: step policy + schema-aligned PlanGeneration only (IG-329)
            parts.append(EXECUTION_POLICIES_FRAGMENT + "\n")
            parts.append(PLAN_GENERATE_INSTRUCTIONS_FRAGMENT + "\n")

        # Language directive: cache-stable, applies to all phases.
        parts.append(RESPONSE_LANGUAGE_HINT_FRAGMENT + "\n")

        # Conditional static sections (present based on context).
        # Workspace rules + WORKSPACE_INSTRUCTIONS apply only to plan-generate:
        # plan-assess is a meta-decision (status/progress/next_action) that does
        # not author steps touching the workspace, so the rules/conventions
        # blocks are wasted tokens and pollute the cache key.
        if context.workspace and plan_phase == "generate":
            parts.append(
                "<WORKSPACE_RULES>\n"
                "The open project root (absolute path) is under <WORKSPACE><root> above.\n\n"
                "Rules:\n"
                "- Filesystem tools (ls, read_file, write_file, edit_file, glob, grep) take "
                "workspace-relative paths (e.g. 'src/main.py') or host-absolute paths under the "
                "workspace root.\n"
                "- Shell tools (run_command, run_python, run_background) run with cwd set to the "
                "workspace root. In shell commands, a leading '/' means the HOST filesystem root, "
                "NOT the workspace. Use '.' or workspace-relative paths (e.g. 'find . -type f', "
                "'cat src/main.py'), or the host-absolute workspace path from <WORKSPACE><root>.\n"
                "- For goals about architecture, structure, or the codebase: inspect this directory immediately.\n"
                "- Do NOT ask the user for a local path, GitHub URL, or file upload unless the goal explicitly names "
                "a different project outside this directory.\n"
                "- Do NOT tell the user you need them to share the project first — it is already available here.\n"
                "</WORKSPACE_RULES>\n"
            )
            # Workspace instructions (CLAUDE.md / AGENTS.md) - goal-stable
            # RFC-624: Use context_bundle.project_instructions when available (skip disk read)
            if context_bundle is not None and context_bundle.project_instructions:
                parts.append(context_bundle.project_instructions + "\n")
            else:
                from soothe.foundation.loop.prompts.project_instructions import (
                    load_workspace_project_instructions,
                )

                ws_instructions = load_workspace_project_instructions(context.workspace)
                if ws_instructions:
                    parts.append(ws_instructions + "\n")

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
                '- If the goal depends on prior conversation text, status MUST NOT be "done" until CoreAgent execution '
                "has produced the requested output (translation, summary, etc.).\n"
                '- With plan_action "new", include at least one concrete execute_steps item that performs the work '
                "(e.g. invoke the main assistant to translate or rewrite the relevant excerpt).\n"
                "- Do not claim the task is finished in next_action unless the evidence or step output contains "
                "the actual result.\n"
                "</FOLLOW_UP_POLICY>\n"
            )

        # Environment section (after REASONING_STANDARDS, before WORKSPACE)
        if self.config is not None:
            from soothe.foundation.loop.prompts.context_xml import build_soothe_environment_section

            model = self.config.resolve_model("default")
            parts.append(build_soothe_environment_section(model=model) + "\n")

        # Workspace section (dynamic, placed last)
        if context.workspace:
            from soothe.foundation.loop.prompts.context_xml import build_soothe_workspace_section

            parts.append(
                build_soothe_workspace_section(Path(context.workspace), context.git_status) + "\n"
            )

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

        # IG-148: Simplified previous plan assessment (status + progress + next_action only)
        prev = state.previous_plan
        if prev:
            parts.append("\nPREVIOUS ASSESSMENT (continuity):")
            parts.append(f"- Status: {prev.status}, Progress: {prev.goal_progress:.0%}")
            if prev.next_action:
                parts.append(f"- Next action: {prev.next_action}")

        return "\n".join(parts)

    def _build_plan_context_human_text(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        *,
        plan_phase: PlanPromptPhase = "assess",
        dag_context: str | None = None,
        context_bundle: ContextBundle | None = None,
    ) -> str:
        """Construct plan-context human text without ledger (RFC-214).

        StrangeLoop ledger messages are appended separately in ``build_plan_messages`` so the
        plan model sees native human/AI turns instead of a single flattened block.
        Execute-step evidence lives in those ledger messages (IG-368).

        Uses scenario-based structured text (GOAL/INTENT/CONTEXT/TASK) instead
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
        from soothe.foundation.loop.prompts.user_message import UserMessageBuilder
        from soothe.foundation.loop.state.schemas import next_goal_local_step_id_start

        builder = UserMessageBuilder()

        # Extract intent from state
        intent_type = "agentic"
        task_complexity = "medium"
        if state.intent and hasattr(state.intent, "intent_type"):
            intent_type = state.intent.intent_type
            task_complexity = getattr(state.intent, "task_complexity", "medium")

        # Build step ID hint for generate phase
        step_id_hint = None
        if plan_phase == "generate":
            nxt = next_goal_local_step_id_start(state)
            if nxt > 1:
                width = max(2, len(str(nxt + 1)))
                ex_a = str(nxt).zfill(width)
                ex_b = str(nxt + 1).zfill(width)
                step_id_hint = (
                    f'This goal already used lower step indices; for plan_action "new", '
                    f"use the next unused local step ids starting with {ex_a} "
                    f"(e.g. {ex_a}, {ex_b}, …), not 01/02 again."
                )

        common_kwargs = dict(
            goal=goal,
            dag_context=dag_context,
            skill_context=state.skill_context,
            prior_progress=getattr(state, "prior_progress", None),
            current_iteration=state.iteration,
            context_bundle=context_bundle,
            intent_type=intent_type,
            task_complexity=task_complexity,
        )

        if plan_phase == "assess":
            return builder.build_plan_assess_message(**common_kwargs)
        else:
            return builder.build_plan_generate_message(
                **common_kwargs,
                step_id_hint=step_id_hint,
            )

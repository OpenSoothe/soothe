"""Hierarchical prompt builder with fragment composition."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from langchain_core.messages import BaseMessage, SystemMessage

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.core.agent_loop.state.schemas import LoopState
    from soothe.protocols.planner import PlanContext

PlanPromptPhase = Literal["assess", "generate"]


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
    ) -> list[BaseMessage]:
        """Build SystemMessage + plan context + ledger for Plan phase (RFC-207, RFC-214).

        Constructs proper message type separation:
        - SystemMessage: environment, workspace, policies, instructions, loop config, capabilities.
        - ``state.loop_messages``: ledger as native ``LoopHumanMessage`` / ``LoopAIMessage`` turns
        - LoopHumanMessage: ``<GOAL_PROGRESS>`` (goal + execute iteration) for both ``assess`` and
          ``generate``, plus optional ``<PRIOR_CONVERSATION>`` when ``recent_messages`` is set
          (IG-371: no WM block on this human).

        Ledger precedes the plan-context human so ``plan-assess`` / ``plan-generate`` see execute
        evidence as prior turns, then goal/iteration context in the following user message.

        Args:
            goal: User's goal description
            state: Current loop state with ledger, plan metadata
            context: Planning context with workspace, capabilities
            plan_phase: ``assess`` = instructions aligned to ``StatusAssessment``; ``generate`` =
                execution policies + instructions aligned to ``PlanGeneration`` only (IG-372, IG-329).

        Returns:
            Messages to send to the plan LLM: system, ledger copies, then optional plan-context human.
        """
        from soothe.core.agent_loop.utils.messages import LoopHumanMessage

        system_content = self._build_system_message(
            context,
            state,
            plan_phase=plan_phase,
        )
        human_content = self._build_plan_context_human_text(goal, state, context)

        out: list[BaseMessage] = [SystemMessage(content=system_content)]
        # RFC-214: full execute (and future) ledger as real messages — better cache boundaries
        # than a single human blob embedding ``<AGENTLOOP_HISTORY>``.
        out.extend(state.loop_messages)
        if human_content.strip():
            out.append(
                LoopHumanMessage(
                    content=human_content,
                    thread_id=state.thread_id,
                    iteration=state.iteration,
                    goal_summary=goal[:200],
                    phase="plan",  # RFC-214: Plan phase marker
                )
            )
        return out

    def _build_system_message(
        self,
        context: PlanContext,
        state: LoopState | None = None,
        *,
        plan_phase: PlanPromptPhase = "assess",
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

        Goal and execute iteration are supplied in the plan-context user message
        (``<GOAL_PROGRESS>``), not in the system prompt.

        Args:
            context: Planning context with workspace, capabilities
            state: Optional loop state for iteration limits and capability context
            plan_phase: Which planner LLM call this system prompt serves (IG-372).
        """
        from soothe.core.prompts.fragments import (
            EXECUTION_POLICIES_FRAGMENT,
            PLAN_ASSESS_INSTRUCTIONS_FRAGMENT,
            PLAN_GENERATE_INSTRUCTIONS_FRAGMENT,
        )

        parts: list[str] = []

        if plan_phase == "assess":
            parts.append(PLAN_ASSESS_INSTRUCTIONS_FRAGMENT + "\n")
        else:
            # Plan generation: step policy + schema-aligned PlanGeneration only (IG-329)
            parts.append(EXECUTION_POLICIES_FRAGMENT + "\n")
            parts.append(PLAN_GENERATE_INSTRUCTIONS_FRAGMENT + "\n")

        # Conditional static sections (present based on context)
        # Workspace rules (static when workspace present)
        if context.workspace:
            parts.append(
                "<WORKSPACE_RULES>\n"
                "The open project root (absolute path) is under <WORKSPACE><root> above.\n\n"
                "Rules:\n"
                "- Use file tools (list_files, read_file, grep, glob, run_command) against this directory.\n"
                "- For goals about architecture, structure, or the codebase: inspect this directory immediately.\n"
                "- Do NOT ask the user for a local path, GitHub URL, or file upload unless the goal explicitly names "
                "a different project outside this directory.\n"
                "- Do NOT tell the user you need them to share the project first — it is already available here.\n"
                "</WORKSPACE_RULES>\n"
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
            from soothe.core.prompts.context_xml import build_soothe_environment_section

            model = self.config.resolve_model("default")
            parts.append(build_soothe_environment_section(model=model) + "\n")

        # Workspace section (dynamic, placed last)
        if context.workspace:
            from soothe.core.prompts.context_xml import build_soothe_workspace_section

            parts.append(
                build_soothe_workspace_section(Path(context.workspace), context.git_status) + "\n"
            )

        return "\n".join(parts)

    @staticmethod
    def _format_goal_progress_footer(goal: str, state: LoopState) -> str:
        """``<GOAL_PROGRESS>`` block for plan-context user message (RFC-214, IG-376)."""
        cur_iter = state.iteration if state.iteration is not None else 0
        max_iter = state.max_iterations if state.max_iterations is not None else "?"
        cycle_one_based = int(cur_iter) + 1
        return (
            "<GOAL_PROGRESS>\n"
            f"Goal: {goal}\n"
            f"Execute iteration: {cycle_one_based}/{max_iter}\n"
            "</GOAL_PROGRESS>\n"
        )

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

        # Goal line for non-plan human paths (plan phase uses ``<GOAL_PROGRESS>`` on plan-context human).
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
    ) -> str:
        """Construct plan-context human text without ledger (RFC-214).

        AgentLoop ledger messages are appended separately in ``build_plan_messages`` so the
        plan model sees native human/AI turns instead of a single flattened ``<AGENTLOOP_HISTORY>`` block.
        Execute-step evidence lives in those ledger messages (IG-368). Working memory is not duplicated
        here; the ledger carries execution narrative (IG-371).

        Always opens with ``<GOAL_PROGRESS>`` (goal + execute iteration). Optional
        ``<PRIOR_CONVERSATION>`` follows when ``recent_messages`` is set.

        Args:
            goal: User's goal description
            state: Current loop state with optional plan snapshot
            context: Planning context (prior thread XML, etc.)

        Returns:
            Formatted prompt string for the plan-context ``LoopHumanMessage``.
        """
        parts: list[str] = [self._format_goal_progress_footer(goal, state).rstrip("\n")]

        # Prior conversation (IG-128, RFC-209)
        if context.recent_messages:
            parts.append("\n<PRIOR_CONVERSATION>\n")
            parts.append(
                'Prior thread (same session); user may reference "that" / "the above".\n\n'
            )
            for msg_xml in context.recent_messages:
                parts.append(msg_xml)
                parts.append("\n")
            parts.append("</PRIOR_CONVERSATION>\n")

        return "\n".join(parts)

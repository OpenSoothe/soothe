"""Hierarchical prompt builder with fragment composition."""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

if TYPE_CHECKING:
    from soothe.cognition.loop_agent.schemas import LoopState
    from soothe.config import SootheConfig
    from soothe.protocols.planner import PlanContext

logger = logging.getLogger(__name__)


class PromptBuilder:
    """Composes hierarchical prompts from fragments.

    Internal API for Soothe prompt construction.
    Not exposed to users for configuration.

    Structure:
        <SOOTHE_PROMPT>
          <SYSTEM_CONTEXT>...</SYSTEM_CONTEXT>
          <USER_TASK>...</USER_TASK>
          <INSTRUCTIONS>...</INSTRUCTIONS>
        </SOOTHE_PROMPT>
    """

    def __init__(self, config: SootheConfig | None = None) -> None:
        """Initialize builder with optional config.

        Args:
            config: Optional Soothe configuration
        """
        self.config = config
        self._fragments_dir = Path(__file__).parent / "fragments"

    def build_reason_messages(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> list[BaseMessage]:
        """Build SystemMessage + HumanMessage for Reason phase (RFC-207).

        Constructs proper message type separation:
        - SystemMessage: environment, workspace, policies, instructions, loop config, capabilities
        - HumanMessage: goal, evidence, working memory, prior conversation

        Args:
            goal: User's goal description
            state: Current loop state with iteration, evidence, working memory
            context: Planning context with workspace, capabilities

        Returns:
            List of [SystemMessage, HumanMessage] to send to LLM.
        """
        system_content = self._build_system_message(context, state)
        human_content = self._build_human_message(goal, state, context)

        return [
            SystemMessage(content=system_content),
            HumanMessage(content=human_content),
        ]

    def _build_system_message(
        self,
        context: PlanContext,
        state: LoopState | None = None,
    ) -> str:
        """Construct static context: environment, workspace, policies, instructions.

        Maps RFC-206 SYSTEM_CONTEXT + INSTRUCTIONS layers to SystemMessage.

        Args:
            context: Planning context with workspace, capabilities
            state: Optional loop state for iteration limits and capability context
        """
        parts: list[str] = []

        # Environment/workspace prefix (RFC-104)
        if self.config is not None:
            from soothe.core.prompts.context_xml import build_shared_environment_workspace_prefix

            parts.append(
                build_shared_environment_workspace_prefix(
                    self.config,
                    context.workspace,
                    context.git_status,
                    include_workspace_extras=False,
                )
            )
        elif context.workspace:
            from soothe.core.prompts.context_xml import build_soothe_workspace_section

            parts.append(build_soothe_workspace_section(Path(context.workspace), context.git_status) + "\n")

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
                "</WORKSPACE_RULES>"
            )

        # Loop iteration limits (system-level configuration context)
        if state is not None:
            parts.append(f"<LOOP_CONFIG>\nIteration: {state.iteration} (max {state.max_iterations})\n</LOOP_CONFIG>")

        # Available capabilities (system-level resource context)
        if context.available_capabilities:
            parts.append(
                f"<AVAILABLE_CAPABILITIES>\n"
                f"Tools/subagents: {', '.join(context.available_capabilities)}\n"
                f"</AVAILABLE_CAPABILITIES>"
            )

        # Prior conversation follow-up policy (static)
        if context.recent_messages:
            parts.append(
                "<FOLLOW_UP_POLICY>\n"
                '- If the goal depends on prior conversation text, status MUST NOT be "done" until CoreAgent execution '
                "has produced the requested output (translation, summary, etc.).\n"
                '- With plan_action "new", include at least one concrete execute_steps item that performs the work '
                "(e.g. invoke the main assistant to translate or rewrite the relevant excerpt).\n"
                "- Do not claim the task is finished in soothe_next_action unless the evidence or step output contains "
                "the actual result.\n"
                "</FOLLOW_UP_POLICY>"
            )

        # Static policy fragments (delegation, granularity)
        parts.append(self._load_fragment("system/policies/delegation.xml"))
        parts.append(self._load_fragment("system/policies/granularity.xml"))

        # Output format specification
        parts.append(self._load_fragment("instructions/output_format.xml"))

        return "\n".join(parts)

    def _build_human_message(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> str:
        """Construct dynamic task: goal, evidence, working memory, prior conversation.

        Maps RFC-206 USER_TASK layer to HumanMessage.
        """
        parts: list[str] = []

        # Goal (iteration info moved to SystemMessage per RFC-207 optimization)
        parts.append(f"Goal: {goal}\n")

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

        # Evidence from steps
        if state.step_results:
            parts.append("\nEvidence from steps run so far in this goal:")
            parts.extend(r.to_evidence_string() for r in state.step_results)

        # Completed steps summary
        if context.completed_steps:
            parts.append("\nPlanner context — completed step summaries (do not repeat work):")
            for step in context.completed_steps:
                status = "✓" if step.success else "✗"
                # RFC-211: Use outcome metadata instead of output field
                outcome_preview = step.to_evidence_string(truncate=True)
                parts.append(f"- {step.step_id}: {status} {outcome_preview}")

        # Working memory excerpt (RFC-203)
        if context.working_memory_excerpt:
            parts.append("\n<WORKING_MEMORY>")
            parts.append(
                "Structured scratchpad for this goal — treat as authoritative for what was already inspected. "
                "Prefer read_file on referenced paths instead of repeating large listings.\n"
            )
            parts.append(context.working_memory_excerpt)
            parts.append("</WORKING_MEMORY>\n")

        # Previous reason assessment
        prev = state.previous_reason
        if prev:
            parts.append("\nYour previous assessment (for continuity):")
            parts.append(f"- Status: {prev.status}")
            parts.append(f"- Progress estimate: {prev.goal_progress:.0%}")
            parts.append(f"- Summary: {prev.soothe_next_action or prev.reasoning[:200]}")

        return "\n".join(parts)

    def build_reason_prompt(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> str:
        """Build hierarchical Reason prompt with dynamic sections.

        **DEPRECATED**: Use build_reason_messages() instead (RFC-207).

        This method returns a single concatenated string for backward compatibility.
        The new build_reason_messages() returns proper SystemMessage/HumanMessage types.

        Args:
            goal: User's goal description
            state: Current loop state with iteration, evidence, wave metrics
            context: Planning context with workspace, capabilities, working memory

        Returns:
            Complete hierarchical prompt string with all dynamic sections

        Warns:
            DeprecationWarning: This method is deprecated per RFC-207.
        """
        warnings.warn(
            "build_reason_prompt() is deprecated, use build_reason_messages() per RFC-207",
            DeprecationWarning,
            stacklevel=2,
        )

        # Use new method for implementation, concatenate for compatibility
        messages = self.build_reason_messages(goal, state, context)
        return "\n\n".join([m.content for m in messages])

    def _load_fragment(self, relative_path: str) -> str:
        """Load fragment file content.

        Args:
            relative_path: Path relative to fragments directory

        Returns:
            Fragment content
        """
        fragment_path = self._fragments_dir / relative_path

        if not fragment_path.exists():
            logger.warning("Fragment not found: %s", fragment_path)
            return f"<!-- Fragment not found: {relative_path} -->\n"

        return fragment_path.read_text(encoding="utf-8")

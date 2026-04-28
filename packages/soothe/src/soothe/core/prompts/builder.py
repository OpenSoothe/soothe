"""Hierarchical prompt builder with fragment composition."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

if TYPE_CHECKING:
    from soothe.cognition.agent_loop.state.schemas import LoopState
    from soothe.config import SootheConfig
    from soothe.protocols.planner import PlanContext

logger = logging.getLogger(__name__)


class PromptBuilder:
    """Composes hierarchical prompts from fragments.

    Internal API for Soothe prompt construction.
    Not exposed to users for configuration.

    Structure (RFC-207):
        SystemMessage: environment, workspace, policies, instructions (static)
        HumanMessage: goal, evidence, working memory, prior conversation (dynamic)

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
    ) -> list[BaseMessage]:
        """Build SystemMessage + HumanMessage for Plan phase (RFC-207).

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
        Uses prefetched fragments for cache optimization (IG-183).

        Args:
            context: Planning context with workspace, capabilities
            state: Optional loop state for iteration limits and capability context
        """
        from soothe.core.prompts.fragments import (
            EXECUTION_POLICIES_FRAGMENT,
            PLAN_EXECUTE_INSTRUCTIONS_FRAGMENT,
        )

        parts: list[str] = []

        # Environment/workspace prefix (RFC-104)
        if self.config is not None:
            from soothe.core.prompts.context_xml import (
                build_shared_environment_workspace_prefix,
            )

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

            parts.append(
                build_soothe_workspace_section(Path(context.workspace), context.git_status) + "\n"
            )

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

        # Available capabilities (system-level resource context with metadata)
        if context.available_capabilities:
            capabilities_text = self._format_capabilities_with_metadata(
                context.available_capabilities, context
            )
            parts.append(
                f"<AVAILABLE_CAPABILITIES>\n{capabilities_text}\n</AVAILABLE_CAPABILITIES>\n"
            )

        # Prior conversation follow-up policy (static)
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

        # Static policy fragments (prefetched, IG-183)
        parts.append(EXECUTION_POLICIES_FRAGMENT + "\n")

        # Plan-Execute instructions (prefetched, IG-183)
        parts.append(PLAN_EXECUTE_INSTRUCTIONS_FRAGMENT + "\n")

        return "\n".join(parts)

    def _format_capabilities_with_metadata(
        self, capabilities: list[str], context: PlanContext
    ) -> str:
        """Format capabilities with metadata from loaded plugins.

        IG-183: Dynamic assembly from plugin system for extensibility.

        Args:
            capabilities: List of capability names (tools/subagents)
            context: PlanContext with optional subagent configs

        Returns:
            Formatted capabilities text with descriptions and metadata
        """
        from soothe.plugin.global_registry import get_plugin_registry

        # Try to get plugin registry (may not be loaded during tests)
        try:
            registry = get_plugin_registry()
        except RuntimeError:
            # Plugin registry not initialized (tests or early startup)
            # Fallback to simple format
            return "\n".join(f"- {cap} (capability)" for cap in sorted(capabilities))

        # Build metadata from registered subagents
        lines = []
        for cap_name in sorted(capabilities):
            # Check if this is a registered subagent
            subagent_factories = registry.get_all_subagents()
            matching_subagent = None

            for factory in subagent_factories:
                # Factory is a method decorated with @subagent
                # Extract metadata from decorator
                if hasattr(factory, "_subagent_metadata"):
                    metadata = factory._subagent_metadata
                    if metadata.get("name") == cap_name:
                        matching_subagent = metadata
                        break

            if matching_subagent:
                # Enriched format from plugin metadata
                lines.append(f"- {cap_name} (subagent)")
                description = matching_subagent.get("description", "")
                if description:
                    # Truncate description for token efficiency (max 80 chars)
                    desc_preview = description[:80] if len(description) > 80 else description
                    lines.append(f"  Description: {desc_preview}")

                # Add model info if available
                model = matching_subagent.get("model", "")
                if model:
                    lines.append(f"  Model: {model}")
            else:
                # Generic format for tools or unknown capabilities
                lines.append(f"- {cap_name} (capability)")

        return "\n".join(lines)

    def _build_human_message(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> str:
        """Construct dynamic task: goal, evidence, working memory, prior conversation.

        Maps RFC-206 USER_TASK layer to HumanMessage.

        IG-148: Enhanced evidence ordering - concrete findings first, working memory,
        prior conversation, then previous assessment. Removed redundant completed_steps.
        """
        parts: list[str] = []

        # Goal (iteration info moved to SystemMessage per RFC-207 optimization)
        parts.append(f"Goal: {goal}\n")

        # IG-148: Evidence from steps (using detailed evidence with CoreAgent input/output)
        if state.step_results:
            parts.append("\nCONCRETE EVIDENCE (highest priority):")
            parts.extend(r.get_detailed_evidence_string() for r in state.step_results)

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

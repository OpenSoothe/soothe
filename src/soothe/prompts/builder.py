"""Hierarchical prompt builder with fragment composition."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

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

    def build_reason_prompt(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> str:
        """Build hierarchical Reason prompt.

        Args:
            goal: User's goal description
            state: Current loop state with iteration, evidence
            context: Planning context with workspace, capabilities

        Returns:
            Complete hierarchical prompt string
        """
        parts = ["<SOOTHE_PROMPT>"]

        # System context
        parts.append("<SYSTEM_CONTEXT>")
        parts.append(self._render_environment())
        if context.workspace:
            parts.append(self._render_workspace(context))
        parts.append(self._render_capabilities(context))
        parts.append(self._render_policies())
        parts.append("</SYSTEM_CONTEXT>")

        # User task
        parts.append("<USER_TASK>")
        parts.append(f"<GOAL>{goal}</GOAL>")
        if context.recent_messages:
            parts.append(self._render_prior_conversation(context))
        if state.step_results:
            parts.append(self._render_evidence(state))
        parts.append("</USER_TASK>")

        # Instructions
        parts.append("<INSTRUCTIONS>")
        parts.append(self._render_output_format())
        parts.append(self._render_execution_rules())
        parts.append("</INSTRUCTIONS>")

        parts.append("</SOOTHE_PROMPT>")
        return "\n".join(parts)

    def _render_environment(self) -> str:
        """Render environment metadata."""
        from soothe.core.prompts.context_xml import build_shared_environment_workspace_prefix

        if self.config is None:
            return ""

        # Use existing environment builder
        return build_shared_environment_workspace_prefix(
            self.config,
            workspace=None,
            git_status=None,
            include_workspace_extras=False,
        )

    def _render_workspace(self, context: PlanContext) -> str:
        """Render workspace metadata."""
        from soothe.core.prompts.context_xml import build_soothe_workspace_section

        if not context.workspace:
            return ""

        workspace_xml = build_soothe_workspace_section(
            Path(context.workspace),
            context.git_status,
        )
        return workspace_xml + "\n"

    def _render_capabilities(self, context: PlanContext) -> str:
        """Render available capabilities."""
        capabilities = context.available_capabilities
        if not capabilities:
            return ""

        return f"<CAPABILITIES>\n{', '.join(capabilities)}\n</CAPABILITIES>\n"

    def _render_policies(self) -> str:
        """Render system policies."""
        parts = ["<POLICIES>"]

        # Delegation policy
        parts.append(self._load_fragment("system/policies/delegation.xml"))

        # Granularity policy
        parts.append(self._load_fragment("system/policies/granularity.xml"))

        parts.append("</POLICIES>\n")
        return "\n".join(parts)

    def _render_prior_conversation(self, context: PlanContext) -> str:
        """Render prior conversation section."""
        if not context.recent_messages:
            return ""

        parts = ["<PRIOR_CONVERSATION>"]
        parts.append("Recent messages in this thread before the current goal. The user may refer to this content.\n")

        for msg_xml in context.recent_messages:
            parts.append(msg_xml)
            parts.append("\n")

        parts.append("</PRIOR_CONVERSATION>\n")
        return "\n".join(parts)

    def _render_evidence(self, state: LoopState) -> str:
        """Render evidence from step results."""
        if not state.step_results:
            return ""

        parts = ["<EVIDENCE>"]
        parts.append("Evidence from steps run so far in this goal:\n")

        for result in state.step_results:
            parts.append(result.to_evidence_string())
            parts.append("\n")

        parts.append("</EVIDENCE>\n")
        return "\n".join(parts)

    def _render_output_format(self) -> str:
        """Render output format specification."""
        return self._load_fragment("instructions/output_format.xml")

    def _render_execution_rules(self) -> str:
        """Render execution rules."""
        return self._load_fragment("instructions/execution_rules.xml")

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

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
        """Build hierarchical Reason prompt with dynamic sections.

        Replaces legacy build_loop_reason_prompt() function.
        Combines fragment-based static policies with dynamic state injections.

        Args:
            goal: User's goal description
            state: Current loop state with iteration, evidence, wave metrics
            context: Planning context with workspace, capabilities, working memory

        Returns:
            Complete hierarchical prompt string with all dynamic sections
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

            parts.append(build_soothe_workspace_section(Path(context.workspace), context.git_status) + "\n\n")

        # Goal and iteration info
        parts.extend(
            [
                f"Goal: {goal}\n",
                f"Loop iteration: {state.iteration} (max {state.max_iterations})\n",
            ]
        )

        # Wave metrics section (IG-132)
        if state.last_wave_tool_call_count > 0:
            cap_status = "Yes" if state.last_wave_hit_subagent_cap else "No"
            context_pct = f"{state.context_percentage_consumed:.1%}" if state.context_percentage_consumed > 0 else "N/A"
            context_tokens = f"{state.total_tokens_used:,}" if state.total_tokens_used > 0 else "N/A"

            parts.append("\n<SOOTHE_WAVE_METRICS>\n")
            parts.append("Last Act wave completed:\n")
            parts.append(f"- Subagent calls: {state.last_wave_subagent_task_count}\n")
            parts.append(f"- Tool calls: {state.last_wave_tool_call_count}\n")
            parts.append(f"- Output length: {state.last_wave_output_length:,} characters\n")
            parts.append(f"- Errors: {state.last_wave_error_count}\n")
            parts.append(f"- Cap hit: {cap_status}\n")
            parts.append(f"- Context used: {context_pct} ({context_tokens} tokens)\n")
            parts.append("</SOOTHE_WAVE_METRICS>\n")

        # Prior conversation (IG-133) - only if Act won't have checkpoint access
        if context.recent_messages and not state.act_will_have_checkpoint_access:
            parts.append("\n<SOOTHE_PRIOR_CONVERSATION>\n")
            parts.append(
                "Recent messages in this thread before the current goal. The user may refer to this content "
                '(e.g. "translate that", "summarize the above", "shorter").\n\n'
            )
            for msg_xml in context.recent_messages:
                parts.append(msg_xml)
                parts.append("\n")
            parts.append(
                "\n<SOOTHE_FOLLOW_UP_POLICY>\n"
                '- If the goal depends on this prior text, status MUST NOT be "done" until CoreAgent execution '
                "has produced the requested output (translation, summary, etc.).\n"
                '- With plan_action "new", include at least one concrete execute_steps item that performs the work '
                "(e.g. invoke the main assistant to translate or rewrite the relevant excerpt).\n"
                "- Do not claim the task is finished in user_summary unless the evidence or step output contains "
                "the actual result.\n"
                "</SOOTHE_FOLLOW_UP_POLICY>\n"
                "</SOOTHE_PRIOR_CONVERSATION>\n"
            )

        # Workspace rules
        if context.workspace:
            parts.append(
                "\n<SOOTHE_REASON_WORKSPACE_RULES>\n"
                "The open project root (absolute path) is under <SOOTHE_WORKSPACE><root> above.\n\n"
                "Rules:\n"
                "- Use file tools (list_files, read_file, grep, glob, run_command) against this directory.\n"
                "- For goals about architecture, structure, or the codebase: inspect this directory immediately.\n"
                "- Do NOT ask the user for a local path, GitHub URL, or file upload unless the goal explicitly names "
                "a different project outside this directory.\n"
                "- Do NOT tell the user you need them to share the project first — it is already available here.\n"
                "</SOOTHE_REASON_WORKSPACE_RULES>\n"
            )

        # Evidence from steps
        if state.step_results:
            parts.append("\nEvidence from steps run so far in this goal:")
            parts.extend(r.to_evidence_string() for r in state.step_results)

        # Last act wave metrics
        if state.last_wave_subagent_task_count or state.last_wave_tool_call_count:
            parts.append("\n<SOOTHE_LAST_ACT_WAVE_METRICS>")
            parts.append(f"- Layer 1 tool results processed (approx): {state.last_wave_tool_call_count}")
            parts.append(f"- Subagent task tool completions (root graph): {state.last_wave_subagent_task_count}")
            if state.last_wave_hit_subagent_cap:
                parts.append(
                    "- The previous Act wave hit the configured subagent task cap. If more delegation is needed, "
                    "plan **one** follow-up step; avoid describing multiple serial subagent calls in a single Act turn."
                )
            parts.append("</SOOTHE_LAST_ACT_WAVE_METRICS>\n")

        # Completed steps summary
        if context.completed_steps:
            parts.append("\nPlanner context — completed step summaries (do not repeat work):")
            for step in context.completed_steps:
                status = "✓" if step.success else "✗"
                output_preview = step.output[:100] if step.output else "no output"
                parts.append(f"- {step.step_id}: {status} {output_preview}")

        # Working memory excerpt (RFC-203)
        if context.working_memory_excerpt:
            parts.append("\n<SOOTHE_LOOP_WORKING_MEMORY>")
            parts.append(
                "Structured scratchpad for this goal — treat as authoritative for what was already inspected. "
                "Prefer read_file on referenced paths instead of repeating large listings.\n"
            )
            parts.append(context.working_memory_excerpt)
            parts.append("</SOOTHE_LOOP_WORKING_MEMORY>\n")

        # Previous reason assessment
        prev = state.previous_reason
        if prev:
            parts.append("\nYour previous assessment (for continuity):")
            parts.append(f"- Status: {prev.status}")
            parts.append(f"- Progress estimate: {prev.goal_progress:.0%}")
            parts.append(f"- Summary: {prev.user_summary or prev.reasoning[:200]}")
            if prev.next_steps_hint:
                parts.append(f"- Hint: {prev.next_steps_hint}")

        # Plan continue policy
        if state.has_remaining_steps():
            parts.append(
                "\n<PLAN_CONTINUE_POLICY>\n"
                "The current AgentDecision still has unfinished steps. If the latest Act results fit the plan, "
                'you MUST prefer plan_action "keep" and omit "decision" so the executor runs the remaining '
                'steps in the next wave. Use plan_action "new" only when evidence proves the plan is wrong, '
                "blocked, or obsolete.\n"
                "</PLAN_CONTINUE_POLICY>\n"
            )

        # Available capabilities
        if context.available_capabilities:
            parts.append(f"\nAvailable tools/subagents: {', '.join(context.available_capabilities)}")

        # Static policy fragments (delegation, granularity)
        parts.append(self._load_fragment("system/policies/delegation.xml"))
        parts.append(self._load_fragment("system/policies/granularity.xml"))

        # Output format specification
        parts.append(self._load_fragment("instructions/output_format.xml"))

        return "\n".join(parts)

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

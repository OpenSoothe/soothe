"""Goal-level context management for AgentLoop (RFC-609)."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.cognition.agent_loop.state.state_manager import AgentLoopStateManager
    from soothe.config.models import GoalContextConfig

logger = logging.getLogger(__name__)


class GoalContextManager:
    """Unified goal-level context provider for AgentLoop.

    Mirrors CoreAgent's separation: conversation history (thread state) vs
    goal-level summaries (loop checkpoint). Provides previous goal context
    for LLM reasoning while keeping CoreAgent conversation isolated.

    Injection rules:
    - Plan phase: ALWAYS inject previous goal summaries (LLM needs goal-level
      context for strategy decisions, regardless of thread continuity)
    - Execute phase: ONLY inject on thread switch (when CoreAgent conversation
      history is lost, goal briefing provides essential knowledge transfer)

    Same-thread constraint: Plan phase only injects goals from current thread.
    Cross-thread scope: Execute briefing includes goals from all threads.

    Attributes:
        state_manager: AgentLoopStateManager for checkpoint access
        config: GoalContextConfig with plan_limit and execute_limit
    """

    def __init__(
        self,
        state_manager: AgentLoopStateManager,
        config: GoalContextConfig | None = None,
    ) -> None:
        """Initialize with state manager and configuration.

        Args:
            state_manager: Checkpoint manager for goal_history access
            config: Goal context configuration (defaults to enabled=True, limits=10)
        """
        self._state_manager = state_manager
        # Use default config if not provided
        if config is None:
            from soothe.config.models import GoalContextConfig

            config = GoalContextConfig()
        self._config = config

    async def get_plan_context(self, limit: int | None = None) -> list[str]:
        """Get previous goal summaries for Plan phase (XML blocks).

        Always injects - Plan phase needs goal-level strategy context
        for LLM planning decisions, even when CoreAgent has conversation
        continuity.

        Same-thread constraint: Only goals from checkpoint.current_thread_id.
        Completed-only constraint: Only goals with status="completed".

        Args:
            limit: Maximum previous goals to inject (default: config.plan_limit)

        Returns:
            XML-formatted goal summaries for PlanContext.recent_messages:
            <previous_goal>
            Goal: <query>
            Status: completed
            Thread: <thread_id>
            Output: <goal_completion>
            </previous_goal>
        """
        # Check if feature enabled
        if not self._config.enabled:
            return []

        try:
            checkpoint = await self._state_manager.load()
            if not checkpoint or not checkpoint.goal_history:
                return []

            # Filter: same-thread + completed only
            current_thread = checkpoint.current_thread_id
            actual_limit = limit or self._config.plan_limit
            completed_goals = [
                g
                for g in checkpoint.goal_history
                if g.thread_id == current_thread and g.status == "completed"
            ][-actual_limit:]

            if not completed_goals:
                return []

            # Format as XML blocks
            context_blocks = []
            for goal in completed_goals:
                context_block = (
                    f"<previous_goal>\n"
                    f"Goal: {goal.goal_text}\n"
                    f"Status: {goal.status}\n"
                    f"Thread: {goal.thread_id}\n"
                    f"Output:\n{goal.goal_completion}\n"
                    f"</previous_goal>"
                )
                context_blocks.append(context_block)

            logger.info(
                "Plan context: %d previous goals from thread %s",
                len(context_blocks),
                current_thread,
            )

            return context_blocks

        except Exception as e:
            logger.warning("Failed to load plan context: %s, continuing without goal context", e)
            return []

    async def get_execute_briefing(self, limit: int | None = None) -> str | None:
        """Get goal briefing for Execute phase (only on thread switch).

        Thread-switch constraint: Only inject when CoreAgent conversation
        history is lost (checkpoint.thread_switch_pending == True).

        Cross-thread scope: Includes goals from all threads for knowledge
        transfer during thread switch recovery.

        Args:
            limit: Maximum previous goals for briefing (default: config.execute_limit)

        Returns:
            Goal briefing markdown string or None (if no thread switch)
        """
        # Check if feature enabled
        if not self._config.enabled:
            return None

        try:
            checkpoint = await self._state_manager.load()
            if not checkpoint:
                return None

            # Check thread switch flag
            if not checkpoint.thread_switch_pending:
                logger.debug("Execute briefing skipped: no thread switch")
                return None

            # Clear flag (briefing will be injected this execution)
            checkpoint.thread_switch_pending = False
            await self._state_manager.save(checkpoint)

            logger.info(
                "Execute briefing: thread switch detected (thread %s), generating briefing",
                checkpoint.current_thread_id,
            )

            # Get previous goals (cross-thread for knowledge transfer)
            actual_limit = limit or self._config.execute_limit
            previous_goals = [g for g in checkpoint.goal_history if g.status == "completed"][
                -actual_limit:
            ]

            if not previous_goals:
                logger.warning("Thread switch but no completed goals for briefing")
                return None

            # Format as condensed briefing
            return self._format_execute_briefing(previous_goals, checkpoint.current_thread_id)

        except Exception as e:
            logger.error("Failed to generate execute briefing: %s", e)
            return None

    def _format_execute_briefing(self, goals: list, current_thread: str) -> str:
        """Format previous goals as condensed Execute briefing.

        Args:
            goals: Completed GoalExecutionRecord instances
            current_thread: Current thread_id (new thread after switch)

        Returns:
            Markdown-formatted briefing string
        """
        sections = ["## Previous Goal Context (Thread Switch Recovery)\n\n"]

        for i, goal in enumerate(goals, 1):
            key_findings = self._extract_key_findings(goal.goal_completion)
            critical_files = self._extract_critical_files(goal.goal_completion)
            result_summary = self._extract_result_summary(goal.goal_completion)

            sections.append(
                f"**Goal {i}** ({goal.thread_id}, {goal.status} in {goal.iteration} iterations):\n"
                f"Query: {goal.goal_text}\n"
                f"Key findings: {key_findings}\n"
                f"Critical files: {critical_files}\n"
                f"Result: {result_summary}\n\n"
            )

        sections.append(
            f"**Current thread**: {current_thread} (new thread, no conversation history)\n"
            f"**Instruction**: Use previous goal context to inform step execution strategy.\n"
            f"Reference critical files discovered in prior work. Avoid re-exploring solved problems."
        )

        return "".join(sections)

    def _extract_key_findings(self, report: str) -> str:
        """Extract key findings summary from final report.

        Heuristic: Extract first 3 bullet points or numbered items.

        Args:
            report: Goal completion content

        Returns:
            Condensed key findings (max 150 chars)
        """
        if not report:
            return "No findings"

        # Look for bullet/number patterns
        patterns = [
            r"^(\d+)\.\s+(.+)",  # "1. item"
            r"^-\s+(.+)",  # "- item"
            r"^\*\s+(.+)",  # "* item"
        ]

        findings = []
        for line in report.split("\n")[:20]:  # Scan first 20 lines
            line = line.strip()
            for pattern in patterns:
                match = re.match(pattern, line)
                if match:
                    # For numbered patterns, extract the text after the number
                    text = match.group(2) if len(match.groups()) > 1 else match.group(1)
                    findings.append(text.strip())
                    if len(findings) >= 3:
                        break

        if not findings:
            # Fallback: first 150 chars
            return report[:150].rstrip() + "..."

        return "; ".join(findings[:3])

    def _extract_critical_files(self, report: str) -> str:
        """Extract critical file paths from final report.

        Pattern: filename.py:number or filename.py

        Args:
            report: Goal completion content

        Returns:
            Comma-separated file list (max 5 files)
        """
        if not report:
            return "None identified"

        # Pattern: file.ext or file.ext:number
        pattern = r"\b([a-zA-Z_][a-zA-Z0-9_-]*\.[a-zA-Z]{1,10})(:\d+)?\b"
        matches = re.findall(pattern, report)

        files = [f[0] for f in matches[:5]]

        if not files:
            return "None identified"

        return ", ".join(files)

    def _extract_result_summary(self, report: str) -> str:
        """Extract result/outcome summary from final report.

        Heuristic: Look for "Result:", "Outcome:", "Completed:", or
        last substantive line before trailing whitespace.

        Args:
            report: Goal completion content

        Returns:
            Result summary (max 100 chars)
        """
        if not report:
            return "Completed"

        # Look for explicit result markers
        markers = ["Result:", "Outcome:", "Completed:", "Performance:", "Summary:"]
        for marker in markers:
            if marker in report:
                start = report.find(marker) + len(marker)
                end = report.find("\n", start)
                if end == -1:
                    end = len(report)
                result = report[start:end].strip()
                return result[:100].rstrip() + "..." if len(result) > 100 else result

        # Fallback: last non-empty line
        lines = [line.strip() for line in report.split("\n") if line.strip()]
        if lines:
            return lines[-1][:100].rstrip() + "..."

        return "Completed"


__all__ = ["GoalContextManager"]

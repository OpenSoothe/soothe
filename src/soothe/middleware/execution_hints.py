"""ExecutionHintsMiddleware for Layer 2 → Layer 1 integration (RFC-0023)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain.agents.middleware import AgentMiddleware

if TYPE_CHECKING:
    from langchain.agents.types import AgentState
    from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)


class ExecutionHintsMiddleware(AgentMiddleware):
    """Process Layer 2 execution hints and inject into system prompt.

    Reads from config.configurable:
        - soothe_step_tools: Optional suggested tools (list[str])
        - soothe_step_subagent: Optional suggested subagent (str)
        - soothe_step_expected_output: Expected result description (str)

    Injects into agent context:
        - Enhances system prompt with natural hint text
        - Format: "Suggested tools: X, Y. Expected output: Z."
        - LLM sees hints and decides whether to use suggested approach

    Advisory Nature:
        - Hints are suggestions, not directives
        - LLM can override hints if inappropriate
        - Execution logic unchanged (LLM makes final tool selection)

    Example:
        config.configurable = {
            "thread_id": "thread-123",
            "soothe_step_tools": ["glob", "grep"],
            "soothe_step_expected_output": "Config file list"
        }

        → System prompt enhanced:
        "Execution hints: Suggested tools: glob, grep. Expected output: Config file list.
         Consider using the suggested approach first, but decide based on what works best."

    Reference: RFC-0023 Layer 1 CoreAgent Runtime Architecture
    """

    async def process_agent_input(
        self,
        state: AgentState,
        config: RunnableConfig,
    ) -> None:
        """Process hints and inject into agent state.

        Args:
            state: Agent state (will be modified)
            config: Runnable config with hints in configurable
        """
        hints = self._extract_hints(config)

        if not hints:
            # No hints present, skip processing
            return

        # Format hints for LLM consumption
        hint_text = self._format_hints(hints)

        # Inject into system prompt
        if "system_prompt" in state:
            state["system_prompt"] += f"\n\nExecution hints: {hint_text}"
            logger.debug("Injected execution hints into system prompt: %s", hint_text)

        # Also add to state for potential logging/inspection
        state["execution_hints_received"] = hints

    def _extract_hints(self, config: RunnableConfig) -> dict | None:
        """Extract Layer 2 hints from config.configurable.

        Args:
            config: Runnable config

        Returns:
            Hints dict if any hints present, None otherwise
        """
        configurable = config.get("configurable", {})

        tools = configurable.get("soothe_step_tools")
        subagent = configurable.get("soothe_step_subagent")
        expected = configurable.get("soothe_step_expected_output")

        # Only return if at least one hint present
        if not any([tools, subagent, expected]):
            return None

        return {
            "tools": tools,
            "subagent": subagent,
            "expected_output": expected,
        }

    def _format_hints(self, hints: dict) -> str:
        """Format hints for system prompt injection.

        Args:
            hints: Hints dict from _extract_hints

        Returns:
            Formatted hint text for LLM
        """
        parts = []

        if hints.get("tools"):
            tools_str = ", ".join(hints["tools"])
            parts.append(f"Suggested tools: {tools_str}")

        if hints.get("subagent"):
            parts.append(f"Suggested subagent: {hints['subagent']}")

        if hints.get("expected_output"):
            parts.append(f"Expected output: {hints['expected_output']}")

        hint_str = ". ".join(parts)

        # Add advisory guidance
        return f"{hint_str}. Consider using the suggested approach first, but decide based on what works best."

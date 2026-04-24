"""ExecutionHintsMiddleware for Layer 2 → Layer 1 integration (RFC-0023)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware

if TYPE_CHECKING:
    from langchain.agents.middleware.types import AgentState
    from langgraph.runtime import Runtime

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

    async def abefore_agent(
        self,
        state: AgentState,
        runtime: Runtime,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """Process hints and inject into agent state.

        Args:
            state: Agent state (will be modified).
            runtime: The runtime context.

        Returns:
            State updates with execution hints if present.
        """
        from langgraph.config import get_config

        # Get config from langgraph context
        try:
            config = get_config()
        except Exception:
            return None

        hints = self._extract_hints(config)

        if not hints:
            return None

        # Format hints for LLM consumption
        hint_text = self._format_hints(hints)

        # Inject into system prompt (state may have system_prompt key)
        updates: dict[str, Any] = {}
        if "system_prompt" in state:
            state["system_prompt"] += f"\n\nExecution hints: {hint_text}"
            logger.debug("Injected execution hints into system prompt: %s", hint_text)

        # Also add to state for potential logging/inspection
        updates["execution_hints_received"] = hints
        return updates

    def _extract_hints(self, config: dict) -> dict | None:
        """Extract Layer 2 hints from config.

        Args:
            config: Either a full config dict with "configurable" key,
                    or just the configurable dict itself.

        Returns:
            Hints dict if any hints present, None otherwise.
        """
        # Handle both full config and just configurable
        configurable = config.get("configurable", config)

        if not isinstance(configurable, dict):
            return None

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
            hints: Hints dict from _extract_hints.

        Returns:
            Formatted hint text for LLM.
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

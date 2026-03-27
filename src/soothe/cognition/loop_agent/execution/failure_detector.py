"""Failure mode detection for LoopAgent guardrails.

Detects and handles failure modes:
- Degenerate retries (same action repeated)
- Tool hallucinations (tool doesn't exist)
- Silent failures (tool returns success but no data)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.cognition.loop_agent.core.schemas import (
        AgentDecision,
        ToolOutput,
    )
    from soothe.cognition.loop_agent.core.state import LoopState


logger = logging.getLogger(__name__)


class FailureDetector:
    """Detect and handle failure modes in agentic loop.

    Implements guardrails to prevent:
    1. Infinite loops via max_iterations
    2. Degenerate retries (same action repeated 3+ times)
    3. Tool hallucinations (calling non-existent tools)
    4. Silent failures (success=True but no data)
    """

    def __init__(
        self,
        max_iterations: int = 3,
        max_repeated_actions: int = 3,
        tool_registry: set[str] | None = None,
    ) -> None:
        """Initialize failure detector.

        Args:
            max_iterations: Maximum loop iterations
            max_repeated_actions: Threshold for degenerate retry detection
            tool_registry: Set of valid tool names (for hallucination detection)
        """
        self.max_iterations = max_iterations
        self.max_repeated_actions = max_repeated_actions
        self.tool_registry = tool_registry or set()

    def check_failures(
        self,
        loop_state: LoopState,
        decision: AgentDecision,
        result: ToolOutput | None = None,
    ) -> str | None:
        """Check for failure modes.

        Args:
            loop_state: Current loop state
            decision: Current decision
            result: Tool execution result (if available)

        Returns:
            Error message if failure detected, None otherwise
        """
        # Check max iterations
        if loop_state.iteration >= self.max_iterations:
            return f"Max iterations reached: {self.max_iterations}"

        # Check tool hallucination
        if decision.is_tool_call():
            hallucination_error = self.detect_hallucination(decision.tool)
            if hallucination_error:
                return hallucination_error

        # Check degenerate retry
        if loop_state.history:
            degenerate_error = self.detect_degenerate_retry(loop_state, decision)
            if degenerate_error:
                return degenerate_error

        # Check silent failure
        if result:
            silent_error = self.detect_silent_failure(result)
            if silent_error:
                return silent_error

        return None

    def detect_hallucination(self, tool_name: str) -> str | None:
        """Check if tool exists in registry.

        Args:
            tool_name: Name of tool to check

        Returns:
            Error message if hallucination detected, None otherwise
        """
        if self.tool_registry and tool_name not in self.tool_registry:
            error = f"Tool hallucination: tool '{tool_name}' not found in registry"
            logger.warning(error)
            return error

        return None

    def detect_degenerate_retry(
        self,
        loop_state: LoopState,
        decision: AgentDecision,
    ) -> str | None:
        """Detect same action repeated 3+ times.

        Args:
            loop_state: Current loop state
            decision: Current decision

        Returns:
            Error message if degenerate retry detected, None otherwise
        """
        if not decision.is_tool_call():
            return None

        if len(loop_state.history) < self.max_repeated_actions - 1:
            return None

        # Check last N decisions
        recent_history = loop_state.history[-(self.max_repeated_actions - 1) :]

        # Check if all recent decisions + current decision are the same tool+args
        all_same = True
        for record in recent_history:
            if not record.decision.is_tool_call():
                all_same = False
                break

            if record.decision.tool != decision.tool or record.decision.args != decision.args:
                all_same = False
                break

        if all_same:
            error = (
                f"Degenerate retry detected: tool '{decision.tool}' "
                f"called {self.max_repeated_actions} times with same args"
            )
            logger.warning(error)
            return error

        return None

    def detect_silent_failure(self, result: ToolOutput) -> str | None:
        """Detect tool that returned success but no data.

        Args:
            result: Tool execution result

        Returns:
            Error message if silent failure detected, None otherwise
        """
        if result.is_silent_failure():
            error = "Silent failure: tool returned success=True but data=None"
            logger.warning(error)
            return error

        return None

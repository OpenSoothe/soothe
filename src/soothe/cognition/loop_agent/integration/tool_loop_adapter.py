"""Tool loop adapter for Layer 1 (DeepAgents) integration.

Wraps DeepAgents graph execution with context borrowing from Layer 2.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.cognition.loop_agent.core.schemas import (
    ToolOutput,
)

if TYPE_CHECKING:
    from langgraph.constants import CompiledStateGraph

    from soothe.cognition.loop_agent.core.schemas import (
        AgentDecision,
    )
    from soothe.cognition.loop_agent.core.state import LoopState
    from soothe.cognition.loop_agent.integration.context_borrower import ContextBorrower


logger = logging.getLogger(__name__)


class ToolLoopAdapter:
    """Wrap DeepAgents graph execution with context borrowing.

    Implements the Layer 2 → Layer 1 tool execution protocol:
    - Borrows iteration summaries from Layer 2
    - Executes tools via DeepAgents graph
    - Wraps tool outputs in ToolOutput schema
    """

    def __init__(
        self,
        agent: CompiledStateGraph,
        context_borrower: ContextBorrower,
    ) -> None:
        """Initialize tool loop adapter.

        Args:
            agent: Compiled DeepAgents state graph
            context_borrower: Context borrower for Layer 2 → Layer 1
        """
        self.agent = agent
        self.context_borrower = context_borrower

    async def execute_tool(
        self,
        decision: AgentDecision,
        loop_state: LoopState,
    ) -> ToolOutput:
        """Execute tool via DeepAgents with borrowed context.

        Args:
            decision: AgentDecision with tool name and args
            loop_state: Current loop state

        Returns:
            Structured ToolOutput
        """
        if not decision.is_tool_call():
            msg = f"Expected tool decision, got {decision.type}"
            raise ValueError(msg)

        # Generate context for Layer 1
        context_summary = self.context_borrower.generate_tool_context(loop_state, decision)

        logger.debug("Executing tool %s with context summary (%d chars)", decision.tool, len(context_summary))

        # NOTE: DeepAgents graph integration pending
        # Implementation needed:
        # 1. Inject context_summary into agent's message context
        # 2. Invoke agent with tool call request
        # 3. Extract tool result
        # 4. Wrap in ToolOutput

        return ToolOutput.fail(error="Tool loop adapter not fully implemented yet", error_type="permanent")

    def _wrap_tool_output(self, result: Any) -> ToolOutput:
        """Wrap tool result in ToolOutput schema.

        Args:
            result: Raw tool result (string, dict, or ToolOutput)

        Returns:
            Structured ToolOutput
        """
        # Import here to avoid circular dependency
        from soothe.cognition.loop_agent.core.schemas import ToolOutput

        if isinstance(result, ToolOutput):
            return result
        if isinstance(result, str):
            # Wrap string output
            return ToolOutput.ok(data={"result": result}, legacy=True)
        if isinstance(result, dict):
            # Wrap dict output
            return ToolOutput.ok(data=result)
        # Unknown type
        return ToolOutput.fail(error=f"Unexpected tool output type: {type(result)}", error_type="permanent")

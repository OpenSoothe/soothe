"""ExecutionHintsMiddleware for Layer 2 → Layer 1 integration.

RFC-214: This middleware is now DEPRECATED and does nothing.
Execution hints are now built directly into the user message envelope
by the executor, not injected into the system prompt.

The middleware remains in the stack for backwards compatibility but
returns None from abefore_agent(), having no effect on prompts.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware

if TYPE_CHECKING:
    from langchain.agents.middleware.types import AgentState
    from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class ExecutionHintsMiddleware(AgentMiddleware):
    """Process Layer 2 execution hints (DEPRECATED per RFC-214).

    Previously injected hints into system_prompt. Now does nothing -
    the executor builds hints directly into the user message
    EXECUTION HINTS: section.

    This class remains in the middleware stack for backwards compatibility
    but has no effect on prompts.
    """

    async def abefore_agent(
        self,
        state: AgentState,
        runtime: Runtime,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """No-op: hints now handled by executor in user envelope (RFC-214)."""
        # RFC-214: Execution hints are built directly into the user message
        # envelope by the executor. This middleware no longer mutates system_prompt.
        return None

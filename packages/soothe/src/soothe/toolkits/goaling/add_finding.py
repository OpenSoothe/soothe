"""add_finding tool for recording insights during execution."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AddFindingInput(BaseModel):
    """Input schema for add_finding tool."""

    summary: str = Field(
        description="Brief description of the finding. Max 2000 chars.",
        max_length=2000,
    )
    relevance_score: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="How relevant this finding is to the overall goal. 0.0-1.0, default 0.7.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Optional categorization tags for filtering and search.",
    )


class AddFindingTool(BaseTool):
    """Tool for recording findings during execution.

    Use this tool when you discover information that may be useful for
    downstream goals or future context. Findings are persisted in the
    GoalDispatchContextContribution and available to child goals via
    ContextProjector.

    Example use cases:
    - You found the location of an important file
    - You discovered a pattern in the data
    - You identified a key insight about the problem domain
    - You learned something that would help subsequent goals

    Findings flow through the context projection system and are available
    to child goals without re-discovery.

    The proposal_queue is accessed via ToolRuntime.state["proposal_queue"]
    (injected by AgentLoop executor) or via direct attribute (factory pattern).
    """

    name: str = "add_finding"
    description: str = (
        "Record a finding for context projection to child goals. "
        "Use when you discover information that may be useful for "
        "downstream goals. The finding persists and is available "
        "to child goals via the context bundle."
    )
    args_schema: type[BaseModel] = AddFindingInput

    # ProposalQueue injected at runtime by the runner (factory pattern)
    proposal_queue: Any = None

    def _run(
        self,
        summary: str,
        relevance_score: float = 0.7,
        tags: list[str] = [],
        runtime: Any | None = None,  # ToolRuntime injection
    ) -> str:
        """Record a finding (synchronous).

        Args:
            summary: Finding description (max 2000 chars).
            relevance_score: Relevance 0.0-1.0.
            tags: Optional categorization tags.
            runtime: ToolRuntime with state["proposal_queue"] from executor.
        """
        # Resolve proposal_queue: try runtime.state first, then direct attribute
        queue = None
        if runtime is not None and hasattr(runtime, "state"):
            queue = runtime.state.get("proposal_queue")
        if queue is None:
            queue = self.proposal_queue

        if queue is None:
            logger.warning("add_finding: proposal_queue not available")
            return "Error: proposal_queue not configured for this execution context"

        from soothe.foundation.autopilot.engine.proposal_queue import Proposal

        # Truncate summary to 2000 chars
        truncated_summary = summary[:2000]

        queue.enqueue(
            Proposal(
                type="add_finding",
                goal_id="",  # Filled by runner with source goal
                payload={
                    "summary": truncated_summary,
                    "relevance_score": relevance_score,
                    "tags": list(tags),
                },
            )
        )

        preview = (
            truncated_summary[:50] + "..." if len(truncated_summary) > 50 else truncated_summary
        )
        logger.info("add_finding queued: '%s' (relevance=%.1f)", preview, relevance_score)
        return f"Finding queued: '{preview}' (relevance={relevance_score:.1f}). Will be added to context contribution."

    async def _arun(
        self,
        summary: str,
        relevance_score: float = 0.7,
        tags: list[str] = [],
        runtime: Any | None = None,  # ToolRuntime injection
    ) -> str:
        """Record a finding (async)."""
        return self._run(summary, relevance_score, tags, runtime)


def create_add_finding_tool(proposal_queue: Any) -> AddFindingTool:
    """Factory for add_finding tool with injected proposal queue.

    Args:
        proposal_queue: ProposalQueue instance from the runner.

    Returns:
        AddFindingTool with queue attached.
    """
    tool = AddFindingTool()
    tool.proposal_queue = proposal_queue
    return tool

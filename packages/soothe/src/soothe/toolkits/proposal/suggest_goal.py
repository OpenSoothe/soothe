"""suggest_goal tool for proactive subgoal creation (RFC-204 Group C)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SuggestGoalInput(BaseModel):
    """Input schema for suggest_goal tool."""

    description: str = Field(
        description="What the suggested goal should accomplish. Be specific about the expected outcome."
    )
    priority: int = Field(
        default=50,
        ge=0,
        le=100,
        description="Urgency level: 0-100, higher = more urgent. Default 50.",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="Optional list of goal IDs this suggestion depends on.",
    )
    rationale: str = Field(
        default="",
        description="Why this goal is needed. Helps the scheduler understand context.",
    )


class SuggestGoalTool(BaseTool):
    """Tool for suggesting new subgoals during execution.

    Use this tool when you identify a prerequisite, dependency, or subtask
    that should be handled separately before continuing the current goal.
    The suggestion is queued and processed after iteration completion.

    Example use cases:
    - A file is missing and needs to be created first
    - A dependency needs to be installed
    - A separate analysis task would benefit the current goal
    - You discover a blocker that requires investigation

    The suggested goal will be created as a child of the current goal,
    inheriting the parent's context and priority (adjusted by +10 by default).
    """

    name: str = "suggest_goal"
    description: str = (
        "Suggest a new subgoal for the current goal's DAG. "
        "Use when you identify a prerequisite or subtask that should be "
        "handled separately before continuing. The suggestion is queued "
        "and creates a goal after this iteration completes."
    )
    args_schema: type[BaseModel] = SuggestGoalInput

    # ProposalQueue injected at runtime by the runner
    proposal_queue: Any = None

    def _run(
        self,
        description: str,
        priority: int = 50,
        depends_on: list[str] = [],
        rationale: str = "",
    ) -> str:
        """Suggest a new subgoal (synchronous)."""
        if self.proposal_queue is None:
            logger.warning("suggest_goal: proposal_queue not available")
            return "Error: proposal_queue not configured for this execution context"

        from soothe.core.goal_engine.proposal_queue import Proposal

        self.proposal_queue.enqueue(
            Proposal(
                type="suggest_goal",
                goal_id="",  # Filled by runner with source goal
                payload={
                    "description": description,
                    "priority": priority,
                    "depends_on": list(depends_on),
                    "rationale": rationale,
                },
            )
        )

        preview = description[:50] + "..." if len(description) > 50 else description
        logger.info("suggest_goal queued: '%s' (priority=%d)", preview, priority)
        return f"Suggested goal queued: '{preview}' (priority={priority}). Will be created after this iteration."

    async def _arun(
        self,
        description: str,
        priority: int = 50,
        depends_on: list[str] = [],
        rationale: str = "",
    ) -> str:
        """Suggest a new subgoal (async)."""
        return self._run(description, priority, depends_on, rationale)


def create_suggest_goal_tool(proposal_queue: Any) -> SuggestGoalTool:
    """Factory for suggest_goal tool with injected proposal queue.

    Args:
        proposal_queue: ProposalQueue instance from the runner.

    Returns:
        SuggestGoalTool with queue attached.
    """
    tool = SuggestGoalTool()
    tool.proposal_queue = proposal_queue
    return tool

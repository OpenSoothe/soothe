"""Layer 2 Agentic Loop Runner (RFC-0008).

Implements PLAN → ACT → JUDGE loop using LoopAgent.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.backends.judgment.llm_judge import LLMJudgeEngine
from soothe.cognition.loop_agent import LoopAgent
from soothe.core.event_catalog import (
    AgenticLoopCompletedEvent,
    AgenticLoopStartedEvent,
)
from soothe.core.runner._runner_shared import StreamChunk, _custom

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)


class AgenticMixin:
    """Layer 2 agentic loop integration.

    Mixed into SootheRunner -- all self.* attributes are defined
    on the concrete class.
    """

    async def _run_agentic_loop(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
        max_iterations: int = 8,
    ) -> AsyncGenerator[StreamChunk]:
        """Run Layer 2: Agentic Goal Execution Loop (RFC-0008).

        Implements PLAN → ACT → JUDGE via LoopAgent.

        Args:
            user_input: Goal description to execute
            thread_id: Thread context for execution
            max_iterations: Maximum loop iterations (default: 8)

        Yields:
            StreamChunk events during execution
        """
        # Ensure thread_id is always a string
        tid = str(thread_id or self._current_thread_id or "")
        self._current_thread_id = tid or None

        # Emit loop started event
        yield _custom(
            AgenticLoopStartedEvent(
                thread_id=tid,
                goal=user_input[:100],
                max_iterations=max_iterations,
            ).to_dict()
        )

        # Create judge instance
        judge = self._create_judge()

        # Create LoopAgent
        loop_agent = LoopAgent(
            core_agent=self.agent,
            planner=self._planner,
            judge=judge,
            config=self.config,
        )

        # Run PLAN → ACT → JUDGE loop
        logger.info(
            "Starting Layer 2 loop for goal: %s (thread: %s)",
            user_input[:100],
            tid,
        )

        judge_result = await loop_agent.run(
            goal=user_input,
            thread_id=tid,
            max_iterations=max_iterations,
        )

        # Emit loop completed event
        yield _custom(
            AgenticLoopCompletedEvent(
                thread_id=tid,
                status=judge_result.status,
                goal_progress=judge_result.goal_progress,
                evidence_summary=judge_result.evidence_summary[:500],
            ).to_dict()
        )

        logger.info(
            "Layer 2 loop completed: status=%s progress=%.0f%%",
            judge_result.status,
            judge_result.goal_progress * 100,
        )

    def _create_judge(self) -> LLMJudgeEngine:
        """Create judge instance from config.

        Returns:
            LLMJudgeEngine instance
        """
        # Use 'fast' model for judgment (can be configured)
        model = self.config.create_chat_model("fast")
        return LLMJudgeEngine(model)

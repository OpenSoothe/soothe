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
    AgenticStepCompletedEvent,
    AgenticStepStartedEvent,
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

        Implements PLAN → ACT → JUDGE via LoopAgent with RFC-0020 progress events.

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

        # First, classify the query to check for chitchat
        if self._unified_classifier:
            classification = await self._unified_classifier.classify_routing(user_input)
            if classification.task_complexity == "chitchat":
                # Use chitchat fast path
                logger.info("Chitchat detected, using fast path")
                async for chunk in self._run_chitchat(user_input, classification):
                    yield chunk
                return

        # Emit loop started event (Level 1)
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
            core_agent=self._agent,
            planner=self._planner,
            judge=judge,
            config=self._config,
        )

        # Run PLAN → ACT → JUDGE loop with progress events (RFC-0020)
        logger.info(
            "Starting Layer 2 loop for goal: %s (thread: %s)",
            user_input[:100],
            tid,
        )

        async for event_type, event_data in loop_agent.run_with_progress(
            goal=user_input,
            thread_id=tid,
            max_iterations=max_iterations,
        ):
            if event_type == "iteration_started":
                # Internal event - not shown to user
                logger.debug("Iteration %d started", event_data["iteration"])

            elif event_type == "plan_decision":
                # Internal - used for debugging only
                logger.debug(
                    "Plan decision: %d steps, mode=%s",
                    len(event_data["steps"]),
                    event_data["execution_mode"],
                )

            elif event_type == "step_started":
                # Level 2: Step description
                yield _custom(
                    AgenticStepStartedEvent(
                        description=event_data["description"],
                    ).to_dict()
                )

            elif event_type == "step_completed":
                # Level 3: Step result
                success = event_data["success"]
                summary = event_data.get("output_preview") or ("Failed" if not success else "Done")
                if event_data.get("error"):
                    summary = f"Error: {event_data['error'][:50]}"

                yield _custom(
                    AgenticStepCompletedEvent(
                        success=success,
                        summary=summary[:100],
                        duration_ms=event_data["duration_ms"],
                    ).to_dict()
                )

            elif event_type == "iteration_completed":
                # Internal - used for debugging only
                logger.debug(
                    "Iteration %d completed: status=%s progress=%.0f%%",
                    event_data["iteration"],
                    event_data["status"],
                    event_data["progress"] * 100,
                )

            elif event_type == "completed":
                # Final result
                judge_result = event_data

                # Emit final assistant response if goal is done with full output
                if judge_result.is_done() and hasattr(judge_result, "full_output") and judge_result.full_output:
                    # Emit the full output as assistant text using proper format
                    # Format: (namespace: tuple, mode: str, data)
                    from langchain_core.messages import AIMessage

                    yield ((), "messages", [AIMessage(content=judge_result.full_output), {}])

                # Emit loop completed event (Level 1)
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
        model = self._config.create_chat_model("fast")
        return LLMJudgeEngine(model)

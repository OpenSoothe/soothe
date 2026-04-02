"""Layer 2 Agentic Loop Runner (RFC-0008).

Implements Reason → Act (ReAct) loop using LoopAgent.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.cognition.loop_agent import LoopAgent
from soothe.cognition.loop_agent.events import LoopAgentReasonEvent
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
        workspace: str | None = None,
        max_iterations: int = 8,
    ) -> AsyncGenerator[StreamChunk]:
        """Run Layer 2: Agentic Goal Execution Loop (RFC-0008).

        Implements Reason → Act via LoopAgent with RFC-0020 progress events.

        Args:
            user_input: Goal description to execute
            thread_id: Thread context for execution
            workspace: Thread-specific workspace path (RFC-103)
            max_iterations: Maximum loop iterations (default: 8)

        Yields:
            StreamChunk events during execution
        """
        # Ensure thread_id is always a string (caller / daemon sets runner thread id; do not mutate here — IG-110)
        tid = str(thread_id or self._current_thread_id or "")

        # First, classify the query to check for chitchat
        if self._unified_classifier:
            classification = await self._unified_classifier.classify_routing(user_input)
            if classification.task_complexity == "chitchat":
                # Use chitchat fast path
                logger.info("[Router] Chitchat detected → fast path")
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

        if self._planner is None:
            logger.error("[Runner] Agentic loop requires a planner that implements LoopReasonerProtocol.reason")
            return

        loop_agent = LoopAgent(
            core_agent=self._agent,
            loop_reasoner=self._planner,
            config=self._config,
        )

        async for event_type, event_data in loop_agent.run_with_progress(
            goal=user_input,
            thread_id=tid,
            workspace=workspace,
            max_iterations=max_iterations,
        ):
            if event_type == "iteration_started":
                # Internal event - not shown to user
                logger.debug("[Loop] Iteration %d started", event_data["iteration"])

            elif event_type == "plan_decision":
                # Internal - used for debugging only
                logger.debug(
                    "[Loop] Plan: %d steps (%s mode)",
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
                        tool_call_count=event_data.get("tool_call_count", 0),
                    ).to_dict()
                )

            elif event_type == "stream_event":
                # Propagate stream events from tool execution (namespace, mode, data)
                # event_data is a StreamChunk tuple
                yield event_data

            elif event_type == "reason":
                yield _custom(
                    LoopAgentReasonEvent(
                        status=event_data["status"],
                        progress=event_data["progress"],
                        confidence=event_data["confidence"],
                        user_summary=event_data.get("user_summary", ""),
                        soothe_next_action=event_data.get("soothe_next_action", ""),
                        progress_detail=event_data.get("progress_detail"),
                        iteration=event_data["iteration"],
                    ).to_dict()
                )

            elif event_type == "iteration_completed":
                # Internal - used for debugging only
                logger.debug(
                    "[Loop] Iteration %d completed (status=%s, progress=%.0f%%)",
                    event_data["iteration"],
                    event_data["status"],
                    event_data["progress"] * 100,
                )

            elif event_type == "completed":
                final_result = event_data

                if final_result.is_done() and final_result.full_output:
                    from langchain_core.messages import AIMessage

                    yield ((), "messages", [AIMessage(content=final_result.full_output), {}])

                evidence = (final_result.evidence_summary or "")[:500]
                yield _custom(
                    AgenticLoopCompletedEvent(
                        thread_id=tid,
                        status=final_result.status,
                        goal_progress=final_result.goal_progress,
                        evidence_summary=evidence,
                    ).to_dict()
                )

                logger.info(
                    "[Runner] Agentic loop completed (status=%s, progress=%.0f%%)",
                    final_result.status,
                    final_result.goal_progress * 100,
                )

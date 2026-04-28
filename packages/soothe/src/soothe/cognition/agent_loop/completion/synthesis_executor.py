"""Synthesis execution for goal completion (RFC-615, IG-297).

Executes LLM synthesis turn with streaming accumulation, separating execution logic
from policy decisions and orchestration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.cognition.agent_loop.policies.response_length_policy import ResponseLengthCategory
from soothe.cognition.agent_loop.state.schemas import LoopState, PlanResult
from soothe.cognition.agent_loop.utils.messages import LoopHumanMessage
from soothe.cognition.agent_loop.utils.stream_normalize import (
    GoalCompletionAccumState,
    iter_messages_for_act_aggregation,
    resolve_goal_completion_text,
    update_goal_completion_from_message,
)
from soothe.utils.text_preview import log_preview

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.core.agent import CoreAgent

logger = logging.getLogger(__name__)


class SynthesisExecutor:
    """Executes LLM synthesis turn with streaming accumulation.

    Responsibilities:
    - Build synthesis prompt with length guidance
    - Execute CoreAgent streaming synthesis
    - Accumulate stream chunks into final text
    - Yield stream events for CLI/TUI

    Separation of concerns:
    - Execution only (no policy decisions)
    - Depends on CoreAgent for LLM calls
    - Depends on stream_normalize for accumulation
    """

    def __init__(self, core_agent: CoreAgent) -> None:
        """Initialize executor with CoreAgent.

        Args:
            core_agent: Layer 1 CoreAgent for synthesis execution.
        """
        self.core_agent = core_agent

    async def execute_synthesis(
        self,
        goal: str,
        state: LoopState,
        plan_result: PlanResult,
        length_category: ResponseLengthCategory,
    ) -> tuple[str, AsyncGenerator]:
        """Execute synthesis LLM turn and yield stream chunks.

        Args:
            goal: Goal description for synthesis prompt.
            state: Loop state with thread context and iteration.
            plan_result: Plan result (reserved for future hints).
            length_category: Response length category for guidance.

        Returns:
            (final_synthesis_text, async_generator_of_stream_chunks)
        """
        _ = plan_result  # Reserved for future use

        logger.info(
            "Goal completion: branch=synthesis full_output=%d chars evidence=%d chars",
            len(state.step_results),
            len(goal),
        )

        # Build synthesis prompt
        goal_completion_request = self._build_synthesis_prompt(goal, length_category)

        logger.debug(
            "[Human Message] Goal completion request: %s",
            log_preview(goal_completion_request, chars=150),
        )

        # Create human message
        human_msg = LoopHumanMessage(
            content=goal_completion_request,
            thread_id=state.thread_id,
            iteration=state.iteration,  # Final iteration
            goal_summary=state.goal[:200] if state.goal else None,
            phase="goal_completion",
        )

        # Stream and accumulate
        accum = GoalCompletionAccumState()

        # Create async generator for streaming
        async def stream_generator() -> AsyncGenerator:
            """Yield stream chunks for CLI/TUI."""
            chunk_count = 0  # Initialize inside generator
            try:
                async for chunk in self.core_agent.astream(
                    {"messages": [human_msg]},
                    config={"configurable": {"thread_id": state.thread_id}},
                    stream_mode=["messages"],
                    subgraphs=False,
                ):
                    chunk_count += 1
                    for msg in iter_messages_for_act_aggregation(chunk):
                        update_goal_completion_from_message(accum, msg)
                    # Yield stream chunks with special event type for goal completion
                    # This bypasses runner filtering so all AI text reaches CLI/TUI
                    yield ("goal_completion_stream", chunk)

                # Resolve final text after stream exhausted
                last_ai_text = resolve_goal_completion_text(accum)

                logger.info(
                    "Stream: chunks=%d ai_msgs=%d chars=%d",
                    chunk_count,
                    accum.ai_msg_count,
                    len(last_ai_text),
                )

                if last_ai_text:
                    logger.info("Goal completion: synthesis=%d chars", len(last_ai_text))
                else:
                    logger.warning("No AI text from CoreAgent")

            except Exception as e:
                logger.warning("Goal completion synthesis failed: %s", e)

        # Execute generator to get final text
        gen = stream_generator()
        chunks_collected = []

        try:
            async for chunk in gen:
                chunks_collected.append(chunk)
        except Exception as e:
            logger.warning("Synthesis stream failed: %s", e)

        # Resolve final text from accumulation
        final_text = resolve_goal_completion_text(accum)

        # Return final text + replayable generator
        async def replay_generator() -> AsyncGenerator:
            """Replay collected chunks for caller."""
            for chunk in chunks_collected:
                yield chunk

        return final_text, replay_generator()

    def _build_synthesis_prompt(self, goal: str, length_category: ResponseLengthCategory) -> str:
        """Construct synthesis prompt with length guidance.

        Args:
            goal: Goal description.
            length_category: Response length category.

        Returns:
            Complete synthesis prompt text.
        """
        length_guidance = self._get_length_guidance(length_category)

        return f"""Based on the complete execution history in this thread, generate a goal completion response for: {goal}

RESPONSE LENGTH: {length_category.min_words}-{length_category.max_words} words ({length_category.value} category)

{length_guidance}

The response should:
1. Summarize what was accomplished
2. **Include actual content** from content-retrieval tools (read_file, web_search, fetch_url, ls, glob, etc.)
   - ToolMessage.content contains the actual file content, search results, etc.
   - Extract and present this actual content directly, not just summaries
   - For file reading: show the actual file content (with line numbers if applicable)
   - For web/research: show actual search results or fetched content
3. Provide actionable results or deliverables
4. Be well-structured with clear sections
5. Match the response length guidance above

IMPORTANT: The user wants to see the actual content retrieved, not just confirmation messages. Extract content from ToolMessage.content in the conversation history and present it appropriately for the response length category.

Use all tool results and AI responses available in the conversation history."""

    def _get_length_guidance(self, length_category: ResponseLengthCategory) -> str:
        """Get response length guidance text for the given category.

        Args:
            length_category: ResponseLengthCategory enum value.

        Returns:
            Guidance text for the response length category.
        """
        if length_category == ResponseLengthCategory.BRIEF:
            return """Be concise: Lead with answer, no preamble, 1-3 sentences.
Focus on essential information only."""
        elif length_category == ResponseLengthCategory.CONCISE:
            return """Be direct: Brief synthesis, 2-4 key points, avoid repetition.
Provide incremental updates building on prior context."""
        elif length_category == ResponseLengthCategory.STANDARD:
            return """Be comprehensive: 3-5 sections, specific numbers, clear structure.
Include methodology and key findings with concrete evidence."""
        elif length_category == ResponseLengthCategory.COMPREHENSIVE:
            return """Be thorough: Full structured report, concrete examples, detailed breakdown.
Provide complete analysis with all relevant details organized into clear sections."""
        else:
            return """Provide a well-structured response matching the task complexity."""

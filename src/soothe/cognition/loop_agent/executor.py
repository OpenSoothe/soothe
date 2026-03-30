"""ACT phase logic for Layer 2 agentic loop (RFC-0008)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from soothe.cognition.loop_agent.schemas import AgentDecision, LoopState, StepAction, StepResult

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.core.agent import CoreAgent

logger = logging.getLogger(__name__)

_TUPLE_LEN = 3
_LIST_MIN_LEN = 2

# Type for stream events yielded during execution
StreamEvent = tuple[tuple[str, ...], str, Any]  # (namespace, mode, data)


class Executor:
    """ACT phase: Execute steps via Layer 1 CoreAgent.

    This component handles step execution with three modes:
    - parallel: Execute all ready steps concurrently with isolated threads
    - sequential: Execute steps one at a time in one agent turn
    - dependency: Execute steps respecting dependency DAG

    Events from CoreAgent are propagated through for upstream consumption.
    """

    def __init__(self, core_agent: CoreAgent) -> None:
        """Initialize ACT phase.

        Args:
            core_agent: Layer 1 CoreAgent for step execution
        """
        self.core_agent = core_agent

    async def execute(
        self,
        decision: AgentDecision,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult, None]:
        """Execute steps based on execution mode, yielding events and results.

        This method yields stream events (custom events from tool execution)
        during execution, then yields final StepResult objects.

        Args:
            decision: AgentDecision with steps to execute
            state: Current loop state

        Yields:
            StreamEvent during execution, then StepResult for each step.
        """
        ready_steps = decision.get_ready_steps(state.completed_step_ids)

        if not ready_steps:
            logger.warning("No ready steps to execute (all completed or blocked)")
            return

        logger.info(
            "Executing %d steps in mode: %s",
            len(ready_steps),
            decision.execution_mode,
        )

        if decision.execution_mode == "parallel":
            async for item in self._execute_parallel(ready_steps, state):
                yield item
        elif decision.execution_mode == "sequential":
            async for item in self._execute_sequential(ready_steps, state):
                yield item
        elif decision.execution_mode == "dependency":
            async for item in self._execute_dependency(decision, state):
                yield item
        else:
            msg = f"Unknown execution mode: {decision.execution_mode}"
            raise ValueError(msg)

    async def _execute_parallel(
        self,
        steps: list,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult, None]:
        """Execute steps in parallel with isolated threads.

        Note: For parallel execution, we cannot yield events in real-time
        because asyncio.gather runs all tasks concurrently. We collect
        events from each task and yield them after all complete.

        Args:
            steps: Steps to execute
            state: Loop state

        Yields:
            StepResult for each completed step.
        """
        # Create tasks that collect events
        tasks = [
            self._execute_step_collecting_events(step, f"{state.thread_id}__step_{i}") for i, step in enumerate(steps)
        ]

        # Execute concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Parallel step %s failed with exception: %s",
                    steps[i].id,
                    result,
                    exc_info=result,
                )
                yield StepResult(
                    step_id=steps[i].id,
                    success=False,
                    error=str(result),
                    error_type="execution",
                    duration_ms=0,
                    thread_id=f"{state.thread_id}__step_{i}",
                )
            else:
                events, step_result = result
                # Yield collected events first
                for event in events:
                    yield event
                # Then yield the result
                yield step_result

    async def _execute_sequential(
        self,
        steps: list,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult, None]:
        """Execute steps sequentially in one agent turn.

        Args:
            steps: Steps to execute
            state: Loop state

        Yields:
            StreamEvent during execution, then StepResult.
        """
        from langchain_core.messages import HumanMessage

        combined_description = self._build_sequential_input(steps)

        start = time.perf_counter()
        try:
            stream = self.core_agent.astream(
                {"messages": [HumanMessage(content=combined_description)]},
                config={"configurable": {"thread_id": state.thread_id}},
                stream_mode=["messages", "updates", "custom"],
            )

            # Collect results and yield events
            output, events = await self._collect_stream_with_events(stream)

            # Yield collected events
            for event in events:
                yield event

            duration_ms = int((time.perf_counter() - start) * 1000)

            logger.info(
                "Sequential execution completed in %dms - output length: %d",
                duration_ms,
                len(output),
            )

            yield StepResult(
                step_id=steps[0].id,
                success=True,
                output=output,
                duration_ms=duration_ms,
                thread_id=state.thread_id,
            )

        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("Sequential execution failed")

            error_msg = self._extract_error_message(e, "Sequential execution failed")

            yield StepResult(
                step_id=steps[0].id,
                success=False,
                error=error_msg,
                error_type="execution",
                duration_ms=duration_ms,
                thread_id=state.thread_id,
            )

    async def _execute_dependency(
        self,
        decision: AgentDecision,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult, None]:
        """Execute steps respecting dependency DAG.

        Args:
            decision: AgentDecision with dependency information
            state: Loop state

        Yields:
            StreamEvent during execution, then StepResult.
        """
        ready_steps = decision.get_ready_steps(state.completed_step_ids)
        async for item in self._execute_parallel(ready_steps, state):
            yield item

    async def _execute_step_collecting_events(
        self,
        step: StepAction,
        thread_id: str,
    ) -> tuple[list[StreamEvent], StepResult]:
        """Execute single step, collecting events for later yielding.

        Used for parallel execution where we can't yield in real-time.

        Args:
            step: StepAction with description and optional hints
            thread_id: Thread ID for execution

        Returns:
            Tuple of (collected events, StepResult)
        """
        from langchain_core.messages import HumanMessage

        start = time.perf_counter()
        events: list[StreamEvent] = []

        try:
            logger.debug(
                "Executing step %s: %s [hints: tools=%s, subagent=%s]",
                step.id,
                step.description[:100],
                step.tools,
                step.subagent,
            )

            config = {
                "configurable": {
                    "thread_id": thread_id,
                    "soothe_step_tools": step.tools,
                    "soothe_step_subagent": step.subagent,
                    "soothe_step_expected_output": step.expected_output,
                }
            }

            stream = self.core_agent.astream(
                {"messages": [HumanMessage(content=f"Execute: {step.description}")]},
                config=config,
                stream_mode=["messages", "updates", "custom"],
            )

            output, events = await self._collect_stream_with_events(stream)
            duration_ms = int((time.perf_counter() - start) * 1000)

            logger.info(
                "Step %s completed successfully in %dms (hints: tools=%s)",
                step.id,
                duration_ms,
                step.tools or "none",
            )

            return events, StepResult(
                step_id=step.id,
                success=True,
                output=output,
                duration_ms=duration_ms,
                thread_id=thread_id,
            )

        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "Step %s failed after %dms [hints: tools=%s, subagent=%s]",
                step.id,
                duration_ms,
                step.tools,
                step.subagent,
            )

            error_msg = self._extract_error_message(e, "Step execution failed")

            return events, StepResult(
                step_id=step.id,
                success=False,
                error=error_msg,
                error_type="execution",
                duration_ms=duration_ms,
                thread_id=thread_id,
            )

    async def _collect_stream_with_events(self, stream: AsyncGenerator) -> tuple[str, list[StreamEvent]]:
        """Collect output from agent stream while preserving events for display.

        Args:
            stream: Async iterator from agent.astream()

        Returns:
            Tuple of (combined output string, list of events for upstream propagation)
        """
        chunks: list[str] = []
        events: list[StreamEvent] = []

        async for chunk in stream:
            # Handle tuple format (namespace, mode, data) - deepagents canonical
            if isinstance(chunk, tuple) and len(chunk) == _TUPLE_LEN:
                namespace, mode, data = chunk

                # Propagate all events for display (tool calls, custom events, etc.)
                # EventProcessor will handle filtering and rendering
                events.append(chunk)

                # Also extract content for output collection
                if mode == "messages" and not namespace and isinstance(data, list) and len(data) >= _LIST_MIN_LEN:
                    msg_chunk = data[0]
                    if hasattr(msg_chunk, "content"):
                        content = msg_chunk.content
                        if isinstance(content, str):
                            chunks.append(content)
                        elif isinstance(content, list):
                            for c in content:
                                if isinstance(c, str):
                                    chunks.append(c)
                                elif isinstance(c, dict) and "text" in c:
                                    chunks.append(c["text"])
            # Handle dict chunks (standard LangGraph format)
            elif isinstance(chunk, dict):
                if "model" in chunk:
                    model_data = chunk["model"]
                    if isinstance(model_data, dict) and "messages" in model_data:
                        for msg in model_data["messages"]:
                            if hasattr(msg, "content"):
                                content = msg.content
                                if isinstance(content, str) and content:
                                    chunks.append(content)
                                elif isinstance(content, list):
                                    for c in content:
                                        if isinstance(c, str):
                                            chunks.append(c)
                                        elif isinstance(c, dict) and "text" in c:
                                            chunks.append(c["text"])
                elif "content" in chunk:
                    chunks.append(str(chunk["content"]))
                elif "output" in chunk:
                    chunks.append(str(chunk["output"]))
                elif "text" in chunk:
                    chunks.append(str(chunk["text"]))
            elif hasattr(chunk, "content"):
                chunks.append(str(chunk.content))

        return "".join(chunks), events

    def _build_sequential_input(self, steps: list) -> str:
        """Build combined input for sequential execution.

        Args:
            steps: Steps to combine

        Returns:
            Combined input string
        """
        descriptions = [f"{i + 1}. {step.description}" for i, step in enumerate(steps)]
        return "Execute these steps sequentially:\n" + "\n".join(descriptions)

    def _extract_error_message(self, exc: Exception, fallback: str) -> str:
        """Extract meaningful error message from exception.

        Parses common error types (especially OpenAI API errors) to extract
        actionable information for the judge to understand failures.

        Args:
            exc: The exception that occurred
            fallback: Fallback message if no specific info found

        Returns:
            Meaningful error message string
        """
        error_str = str(exc)

        # Check for OpenAIBadRequestError with context length issues
        if "invalid_parameter_error" in error_str or "Range of input length should be" in error_str:
            return "Input exceeded model context limit (too large)"

        # Check for rate limiting
        if "rate_limit" in error_str.lower() or "429" in error_str:
            return "Rate limited - too many requests"

        # Check for authentication/permission errors
        if "401" in error_str or "403" in error_str or "permission" in error_str.lower():
            return "Permission/authentication error"

        # Check for timeout
        if "timeout" in error_str.lower():
            return "Request timed out"

        # Check for connection errors
        if "connection" in error_str.lower() or "network" in error_str.lower():
            return "Network/connection error"

        # For other errors, try to extract the error type but keep it concise
        exc_type = type(exc).__name__
        if exc_type != "Exception":
            # Include exception type but truncate long messages
            return f"{exc_type}: {error_str[:200]}"

        return fallback

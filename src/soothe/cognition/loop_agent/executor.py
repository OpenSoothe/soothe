"""ACT phase logic for Layer 2 agentic loop (RFC-0008)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from soothe.cognition.loop_agent.schemas import AgentDecision, LoopState, StepAction, StepResult

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.core.agent import CoreAgent

logger = logging.getLogger(__name__)

_TUPLE_LEN = 3
_LIST_MIN_LEN = 2


class Executor:
    """ACT phase: Execute steps via Layer 1 CoreAgent.

    This component handles step execution with three modes:
    - parallel: Execute all ready steps concurrently with isolated threads
    - sequential: Execute steps one at a time in one agent turn
    - dependency: Execute steps respecting dependency DAG
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
    ) -> list[StepResult]:
        """Execute steps based on execution mode.

        Args:
            decision: AgentDecision with steps to execute
            state: Current loop state

        Returns:
            List of StepResult (includes errors as failed results)
        """
        ready_steps = decision.get_ready_steps(state.completed_step_ids)

        if not ready_steps:
            logger.warning("No ready steps to execute (all completed or blocked)")
            return []

        logger.info(
            "Executing %d steps in mode: %s",
            len(ready_steps),
            decision.execution_mode,
        )

        if decision.execution_mode == "parallel":
            return await self._execute_parallel(ready_steps, state)
        if decision.execution_mode == "sequential":
            return await self._execute_sequential(ready_steps, state)
        if decision.execution_mode == "dependency":
            return await self._execute_dependency(decision, state)
        msg = f"Unknown execution mode: {decision.execution_mode}"
        raise ValueError(msg)

    async def _execute_parallel(
        self,
        steps: list,
        state: LoopState,
    ) -> list[StepResult]:
        """Execute steps in parallel with isolated threads.

        Args:
            steps: Steps to execute
            state: Loop state

        Returns:
            List of step results
        """
        tasks = [self._execute_step(step, f"{state.thread_id}__step_{i}") for i, step in enumerate(steps)]

        # Execute concurrently, catching exceptions
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error results
        step_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Parallel step %s failed with exception: %s",
                    steps[i].id,
                    result,
                    exc_info=result,
                )
                step_results.append(
                    StepResult(
                        step_id=steps[i].id,
                        success=False,
                        error=str(result),
                        error_type="execution",
                        duration_ms=0,
                        thread_id=f"{state.thread_id}__step_{i}",
                    )
                )
            else:
                step_results.append(result)

        return step_results

    async def _execute_sequential(
        self,
        steps: list,
        state: LoopState,
    ) -> list[StepResult]:
        """Execute steps sequentially in one agent turn.

        Args:
            steps: Steps to execute
            state: Loop state

        Returns:
            List of step results (single combined result)
        """
        from langchain_core.messages import HumanMessage

        combined_description = self._build_sequential_input(steps)

        start = time.perf_counter()
        try:
            # astream returns an async generator, don't await it
            # Input must be a dict with "messages" key for LangGraph agents
            stream = self.core_agent.astream(
                {"messages": [HumanMessage(content=combined_description)]},
                config={"configurable": {"thread_id": state.thread_id}},
            )

            # Collect results from stream
            output = await self._collect_stream(stream)

            duration_ms = int((time.perf_counter() - start) * 1000)

            logger.info(
                "Sequential execution completed in %dms - output length: %d",
                duration_ms,
                len(output),
            )

            # Return single result for all steps
            return [
                StepResult(
                    step_id=steps[0].id,  # Primary step
                    success=True,
                    output=output,
                    duration_ms=duration_ms,
                    thread_id=state.thread_id,
                )
            ]

        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("Sequential execution failed")

            return [
                StepResult(
                    step_id=steps[0].id,
                    success=False,
                    error="Sequential execution failed",
                    error_type="execution",
                    duration_ms=duration_ms,
                    thread_id=state.thread_id,
                )
            ]

    async def _execute_dependency(
        self,
        decision: AgentDecision,
        state: LoopState,
    ) -> list[StepResult]:
        """Execute steps respecting dependency DAG.

        Args:
            decision: AgentDecision with dependency information
            state: Loop state

        Returns:
            List of step results
        """
        # For now, execute ready steps in parallel
        ready_steps = decision.get_ready_steps(state.completed_step_ids)
        return await self._execute_parallel(ready_steps, state)

    async def _execute_step(
        self,
        step: StepAction,
        thread_id: str,
    ) -> StepResult:
        """Execute single step through CoreAgent with Layer 2 hints.

        Args:
            step: StepAction with description and optional hints
            thread_id: Thread ID for execution

        Returns:
            StepResult with success/error
        """
        from langchain_core.messages import HumanMessage

        start = time.perf_counter()

        try:
            logger.debug(
                "Executing step %s: %s [hints: tools=%s, subagent=%s]",
                step.id,
                step.description[:100],
                step.tools,
                step.subagent,
            )

            # Build config with Layer 2 → Layer 1 hints (advisory)
            config = {
                "configurable": {
                    "thread_id": thread_id,
                    # Layer 2 execution hints
                    "soothe_step_tools": step.tools,
                    "soothe_step_subagent": step.subagent,
                    "soothe_step_expected_output": step.expected_output,
                }
            }

            # astream returns an async generator, don't await it
            # Input must be a dict with "messages" key for LangGraph agents
            stream = self.core_agent.astream(
                {"messages": [HumanMessage(content=f"Execute: {step.description}")]},
                config=config,  # Hints passed via config
            )

            output = await self._collect_stream(stream)
            duration_ms = int((time.perf_counter() - start) * 1000)

            logger.info(
                "Step %s completed successfully in %dms (hints: tools=%s)",
                step.id,
                duration_ms,
                step.tools or "none",
            )

            return StepResult(
                step_id=step.id,
                success=True,
                output=output,
                duration_ms=duration_ms,
                thread_id=thread_id,
            )

        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "Step %s failed after %dms [hints: tools=%s, subagent=%s]",
                step.id,
                duration_ms,
                step.tools,
                step.subagent,
            )

            return StepResult(
                step_id=step.id,
                success=False,
                error="Step execution failed",
                error_type="execution",
                duration_ms=duration_ms,
                thread_id=thread_id,
            )

    async def _collect_stream(self, stream: AsyncGenerator) -> str:
        """Collect output from agent stream.

        Args:
            stream: Async iterator from agent.astream()

        Returns:
            Combined output string
        """
        chunks = []
        async for chunk in stream:
            # Handle dict chunks (standard LangGraph format)
            if isinstance(chunk, dict):
                # Look for 'model' key which contains AI messages
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
                # Handle other chunk formats
                elif "content" in chunk:
                    chunks.append(str(chunk["content"]))
                elif "output" in chunk:
                    chunks.append(str(chunk["output"]))
                elif "text" in chunk:
                    chunks.append(str(chunk["text"]))
            # Handle tuple format (namespace, mode, data)
            elif isinstance(chunk, tuple) and len(chunk) == _TUPLE_LEN:
                namespace, mode, data = chunk
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
            elif hasattr(chunk, "content"):
                chunks.append(str(chunk.content))

        return "".join(chunks)

    def _build_sequential_input(self, steps: list) -> str:
        """Build combined input for sequential execution.

        Args:
            steps: Steps to combine

        Returns:
            Combined input string
        """
        descriptions = [f"{i + 1}. {step.description}" for i, step in enumerate(steps)]
        return "Execute these steps sequentially:\n" + "\n".join(descriptions)

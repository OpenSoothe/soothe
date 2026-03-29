"""ACT phase logic for Layer 2 agentic loop (RFC-0008)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from soothe.cognition.loop_agent.schemas import AgentDecision, LoopState, StepAction, StepResult

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langgraph.pregel import CompiledStateGraph

logger = logging.getLogger(__name__)


class Executor:
    """ACT phase: Execute steps via Layer 1 CoreAgent.

    This component handles step execution with three modes:
    - parallel: Execute all ready steps concurrently with isolated threads
    - sequential: Execute steps one at a time in one agent turn
    - dependency: Execute steps respecting dependency DAG
    """

    def __init__(self, core_agent: CompiledStateGraph) -> None:
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
        combined_input = self._build_sequential_input(steps)

        start = time.perf_counter()
        try:
            stream = await self.core_agent.astream(
                input=combined_input,
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

            stream = await self.core_agent.astream(
                input=f"Execute: {step.description}",
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
            if isinstance(chunk, dict):
                # Handle different chunk formats
                if "content" in chunk:
                    chunks.append(str(chunk["content"]))
                elif "output" in chunk:
                    chunks.append(str(chunk["output"]))
                elif "text" in chunk:
                    chunks.append(str(chunk["text"]))
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

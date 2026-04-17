"""ACT phase logic for AgentLoop (RFC-201)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, BaseMessage

from soothe.cognition.agent_loop.schemas import (
    AgentDecision,
    LoopState,
    StepAction,
    StepResult,
)
from soothe.utils.text_preview import create_output_summary, preview_first

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.cognition.agent_loop.goal_context_manager import GoalContextManager
    from soothe.config import SootheConfig
    from soothe.core.agent import CoreAgent

logger = logging.getLogger(__name__)


@dataclass
class _ActStreamBudget:
    """Mutable counters for a single CoreAgent stream (IG-130)."""

    max_subagent_tasks_per_wave: int = 0
    subagent_task_completions: int = 0
    hit_subagent_cap: bool = False


_TUPLE_LEN = 3
_LIST_MIN_LEN = 2
_MSG_TUPLE_LEN = 2  # (msg, metadata) tuple from deepagents streaming

# Type for stream events yielded during execution
StreamEvent = tuple[tuple[str, ...], str, Any]  # (namespace, mode, data)


class Executor:
    """ACT phase: Execute steps via Layer 1 CoreAgent.

    This component handles step execution with three modes:
    - parallel: Execute ready steps concurrently with isolated threads (chunked)
    - sequential: Execute ready steps in combined LLM turns (chunked)
    - dependency: Execute steps respecting dependency DAG (chunked parallel waves)

    Events from CoreAgent are propagated through for upstream consumption.
    """

    def __init__(
        self,
        core_agent: CoreAgent,
        *,
        max_parallel_steps: int = 1,
        config: SootheConfig | None = None,
        goal_context_manager: GoalContextManager | None = None,
    ) -> None:
        """Initialize ACT phase.

        Args:
            core_agent: Layer 1 CoreAgent for step execution
            max_parallel_steps: Max steps per wave; ``0`` means unlimited (RFC-201 / concurrency).
            config: Optional Soothe config for Act wave caps (IG-130).
            goal_context_manager: Optional GoalContextManager for goal briefing injection (RFC-609).
        """
        self.core_agent = core_agent
        self._max_parallel_steps = max_parallel_steps
        self._config = config
        self._goal_context_manager = goal_context_manager

    def _max_subagent_tasks_per_wave(self) -> int:
        """Configured cap on root-level ``task`` tool completions (0 = unlimited)."""
        if self._config is None:
            return 0
        return max(0, int(self._config.agentic.max_subagent_tasks_per_wave))

    def _extract_token_usage(self, messages: list[BaseMessage]) -> dict[str, int]:
        """Extract token usage from last AIMessage response metadata.

        Args:
            messages: List of messages from CoreAgent execution

        Returns:
            Dict with prompt_tokens, completion_tokens, total_tokens (or empty dict if unavailable)
        """
        # Find last AIMessage with usage_metadata
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, "response_metadata"):
                metadata = msg.response_metadata
                token_usage = metadata.get("token_usage", {})
                if token_usage:
                    return {
                        "prompt": token_usage.get("prompt_tokens", 0),
                        "completion": token_usage.get("completion_tokens", 0),
                        "total": token_usage.get("total_tokens", 0),
                    }
        return {}

    def _aggregate_wave_metrics(
        self,
        step_results: list[StepResult],
        output: str,
        messages: list[BaseMessage],
        state: LoopState,
    ) -> None:
        """Aggregate metrics from wave execution into LoopState.

        Called after sequential or parallel wave completes.

        Args:
            step_results: List of step results from the wave
            output: Combined output text from the wave
            messages: Messages from CoreAgent execution (for token extraction)
            state: LoopState to update with aggregated metrics
        """
        # Sum tool calls and subagent tasks
        total_tool_calls = sum(r.tool_call_count for r in step_results)
        total_subagent_tasks = sum(r.subagent_task_completions for r in step_results)

        # OR cap hit (any step hit cap)
        hit_cap = any(r.hit_subagent_cap for r in step_results)

        # Count errors
        error_count = sum(1 for r in step_results if not r.success)

        # Measure output length
        output_length = len(output) if output else 0

        # Update state
        state.last_wave_tool_call_count = total_tool_calls
        state.last_wave_subagent_task_count = total_subagent_tasks
        state.last_wave_hit_subagent_cap = hit_cap
        state.last_wave_output_length = output_length
        state.last_wave_error_count = error_count

        # Context window metrics with actual token usage (IG-151)
        token_usage = self._extract_token_usage(messages)

        if token_usage and "total" in token_usage:
            # Use actual token count from LLM response
            actual_tokens = token_usage["total"]
            state.total_tokens_used += actual_tokens
            logger.debug(
                "[Tokens] LLM actual=%d (prompt=%d completion=%d)",
                actual_tokens,
                token_usage.get("prompt", 0),
                token_usage.get("completion", 0),
            )
        elif output:
            # Fallback: use tiktoken for accurate estimation
            from soothe.utils.token_counting import count_tokens

            estimated_tokens = count_tokens(output)
            state.total_tokens_used += estimated_tokens
            logger.debug("[Tokens] tiktoken estimated=%d", estimated_tokens)

        # Use configurable context limit (IG-151)
        if self._config is not None:
            context_limit = self._config.agentic.context_window_limit
            state.context_percentage_consumed = min(1.0, state.total_tokens_used / context_limit)

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
            "[Execute] steps=%d mode=%s max_parallel=%d",
            len(ready_steps),
            decision.execution_mode,
            self._max_parallel_steps,
        )

        if decision.execution_mode == "parallel":
            async for item in self._execute_parallel_waves(ready_steps, state):
                yield item
        elif decision.execution_mode == "sequential":
            async for item in self._execute_sequential_waves(ready_steps, state):
                yield item
        elif decision.execution_mode == "dependency":
            async for item in self._execute_dependency(decision, state):
                yield item
        else:
            msg = f"Unknown execution mode: {decision.execution_mode}"
            raise ValueError(msg)

    def _wave_size(self, remaining: int) -> int:
        """Steps to schedule in the next wave (``0`` config = unlimited)."""
        if remaining <= 0:
            return 0
        if self._max_parallel_steps <= 0:
            return remaining
        return min(self._max_parallel_steps, remaining)

    async def _execute_parallel_waves(
        self,
        ready_steps: list,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult, None]:
        """Run parallel mode in waves bounded by ``max_parallel_steps``."""
        idx = 0
        n = len(ready_steps)
        while idx < n:
            w = self._wave_size(n - idx)
            chunk = ready_steps[idx : idx + w]
            idx += w
            async for item in self._execute_parallel(chunk, state):
                yield item

    def _step_results_for_chunk(
        self,
        steps: list[StepAction],
        combined_description: str | None = None,
        *,
        success: bool,
        output: str | None,
        error: str | None,
        error_type: str | None,
        duration_ms: int,
        tool_call_count: int,
        thread_id: str,
        subagent_task_completions: int = 0,
        hit_subagent_cap: bool = False,
    ) -> list[StepResult]:
        """One ``StepResult`` per step in a combined sequential turn (scheme B)."""
        n = len(steps)
        if n == 0:
            return []
        base, rem = divmod(max(duration_ms, 0), n)
        durations = [base + (1 if i < rem else 0) for i in range(n)]
        tool_counts = [0] * n
        if n > 0:
            tool_counts[0] = tool_call_count
        results: list[StepResult] = []
        for i, step in enumerate(steps):
            if success:
                # IG-148: Add CoreAgent input/output evidence for sequential execution
                outcome_data = {
                    "type": "generic",
                    "size_bytes": len(output.encode("utf-8")) if output else 0,
                }
                # Add step input (combined_description for sequential waves)
                if combined_description:
                    outcome_data["step_input"] = combined_description
                # Add output summary (truncated)
                if output:
                    outcome_data["output_summary"] = create_output_summary(output)

                results.append(
                    StepResult(
                        step_id=step.id,
                        success=True,
                        outcome=outcome_data,  # RFC-211 + IG-148
                        duration_ms=durations[i],
                        thread_id=thread_id,
                        tool_call_count=tool_counts[i],
                        subagent_task_completions=subagent_task_completions if i == 0 else 0,
                        hit_subagent_cap=hit_subagent_cap if i == 0 else False,
                    )
                )
            else:
                results.append(
                    StepResult(
                        step_id=step.id,
                        success=False,
                        outcome={"type": "error", "error": error or ""},  # RFC-211
                        error=error or "",
                        error_type=error_type,
                        duration_ms=durations[i],
                        thread_id=thread_id,
                        tool_call_count=0,
                        subagent_task_completions=0,
                        hit_subagent_cap=False,
                    )
                )
        return results

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
            asyncio.create_task(
                self._execute_step_collecting_events(step, state.thread_id, state.workspace)
            )
            for step in steps
        ]

        try:
            # Execute concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            # Cancel all child tasks immediately on cancellation (IG-109)
            for task in tasks:
                if not task.done():
                    task.cancel()
            # Wait briefly for tasks to acknowledge cancellation
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        # Process results
        all_step_results: list[StepResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Parallel step %s failed with exception: %s",
                    steps[i].id,
                    result,
                    exc_info=result,
                )
                step_result = StepResult(
                    step_id=steps[i].id,
                    success=False,
                    outcome={"type": "error", "error": str(result)},  # RFC-211
                    error=str(result),
                    error_type=self._classify_error_severity(result),
                    duration_ms=0,
                    thread_id=state.thread_id,
                    subagent_task_completions=0,
                    hit_subagent_cap=False,
                )
                all_step_results.append(step_result)
                yield step_result
            else:
                events, step_result = result
                all_step_results.append(step_result)
                # Yield collected events first
                for event in events:
                    yield event
                # Then yield the result
                yield step_result

        # Aggregate metrics from parallel execution
        if all_step_results:
            # For parallel, use max output length across steps
            # RFC-211: Use outcome metadata to get size
            output_lengths = [
                r.outcome.get("size_bytes", 0) for r in all_step_results if r.success and r.outcome
            ]
            max_output_len = max(output_lengths) if output_lengths else 0
            # IG-151: For parallel execution, we don't have unified messages (each step has its own)
            # This is acceptable as token tracking is more relevant for sequential mode
            self._aggregate_wave_metrics(all_step_results, "", [], state)
            state.last_wave_output_length = max_output_len

    async def _execute_sequential_waves(
        self,
        ready_steps: list,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult, None]:
        """Run sequential mode in waves; each wave yields one result per step (scheme B)."""
        idx = 0
        n = len(ready_steps)
        while idx < n:
            w = self._wave_size(n - idx)
            chunk = ready_steps[idx : idx + w]
            idx += w
            async for item in self._execute_sequential_chunk(chunk, state):
                yield item

    async def _execute_sequential_chunk(
        self,
        steps: list,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult, None]:
        """Execute a wave of steps in one Layer 1 turn; credit every step in the wave.

        Args:
            steps: Non-empty slice of ready steps
            state: Loop state

        Yields:
            StreamEvent during execution, then one StepResult per step in ``steps``.
        """
        from langchain_core.messages import HumanMessage

        combined_description = self._build_sequential_input(steps)

        # Compact input summary log
        logger.debug(
            "[Execute-Seq] steps=%d thread=%s workspace=%s desc_len=%d",
            len(steps),
            state.thread_id[:12] if state.thread_id else "none",
            state.workspace[:30] if state.workspace else "none",
            len(combined_description),
        )

        logger.info(
            "[Execute-Seq] steps=%d mode=%s max_parallel=%d",
            len(steps),
            state.current_decision.execution_mode if state.current_decision else "sequential",
            self._max_parallel_steps,
        )

        start = time.perf_counter()
        output = ""
        event_count = 0  # Track events for debugging
        budget = _ActStreamBudget(max_subagent_tasks_per_wave=self._max_subagent_tasks_per_wave())

        try:
            configurable: dict[str, Any] = {"thread_id": state.thread_id}
            if state.workspace:
                configurable["workspace"] = state.workspace
            # Pass current_decision for middleware to inject agent loop output contract
            if state.current_decision:
                configurable["current_decision"] = state.current_decision
            # RFC-609: Inject goal briefing on thread switch
            if self._goal_context_manager:
                goal_briefing = self._goal_context_manager.get_execute_briefing()
                if goal_briefing:
                    configurable["soothe_goal_briefing"] = goal_briefing
                    logger.info("Execute briefing injected (%d chars)", len(goal_briefing))

            stream = self.core_agent.astream(
                {"messages": [HumanMessage(content=combined_description)]},
                config={"configurable": configurable},
                stream_mode=["messages", "updates", "custom"],
                subgraphs=True,
            )

            tool_call_count = 0
            messages: list[BaseMessage] = []  # IG-151: Collect messages for token extraction
            async for final_output, event, tc_count, msg_list in self._stream_and_collect(
                stream, budget=budget
            ):
                if event is not None:
                    event_count += 1
                    yield event
                elif final_output is not None:
                    output = final_output
                    tool_call_count = tc_count
                    messages = msg_list  # IG-151: Save messages for metrics

            duration_ms = int((time.perf_counter() - start) * 1000)

            # Compact wave completion summary log
            logger.debug(
                "[Wave-Seq] duration=%dms output=%d events=%d tools=%d subagents=%d cap=%s",
                duration_ms,
                len(output),
                event_count,
                tool_call_count,
                budget.subagent_task_completions,
                budget.hit_subagent_cap,
            )
            logger.info(
                "[Wave-Seq] steps=%d duration=%dms output=%d tools=%d subagents=%d cap=%s",
                len(steps),
                duration_ms,
                len(output),
                tool_call_count,
                budget.subagent_task_completions,
                budget.hit_subagent_cap,
            )

            # Collect step results for metrics aggregation
            step_results = list(
                self._step_results_for_chunk(
                    steps,
                    combined_description=combined_description,  # IG-148: CoreAgent input evidence
                    success=True,
                    output=output,
                    error=None,
                    error_type=None,
                    duration_ms=duration_ms,
                    tool_call_count=tool_call_count,
                    thread_id=state.thread_id,
                    subagent_task_completions=budget.subagent_task_completions,
                    hit_subagent_cap=budget.hit_subagent_cap,
                )
            )

            # Aggregate metrics into LoopState
            self._aggregate_wave_metrics(step_results, output, messages, state)

            # Yield step results
            for sr in step_results:
                yield sr

        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("Sequential execution failed")

            error_msg = self._extract_error_message(e, "Sequential execution failed")
            et = self._classify_error_severity(e)

            # Collect failed step results for metrics
            step_results = list(
                self._step_results_for_chunk(
                    steps,
                    success=False,
                    output=None,
                    error=error_msg,
                    error_type=et,
                    duration_ms=duration_ms,
                    tool_call_count=0,
                    thread_id=state.thread_id,
                    subagent_task_completions=0,
                    hit_subagent_cap=False,
                )
            )

            # Aggregate metrics (includes error count)
            self._aggregate_wave_metrics(step_results, "", [], state)  # No messages on error

            # Yield step results
            for sr in step_results:
                yield sr

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
        local_done = set(state.completed_step_ids)
        failed_sticky: set[str] = set()

        while True:
            ready_all = decision.get_ready_steps(local_done)
            ready = [s for s in ready_all if s.id not in failed_sticky]
            if not ready:
                break
            w = self._wave_size(len(ready))
            chunk = ready[:w]
            async for item in self._execute_parallel(chunk, state):
                yield item
                if isinstance(item, StepResult):
                    if item.success:
                        local_done.add(item.step_id)
                    else:
                        failed_sticky.add(item.step_id)

    async def _execute_step_collecting_events(
        self,
        step: StepAction,
        thread_id: str,
        workspace: str | None = None,
    ) -> tuple[list[StreamEvent], StepResult]:
        """Execute single step, collecting events for later yielding.

        Used for parallel execution where we can't yield in real-time.
        Events are collected and returned with the final result.

        RFC-211: Collects outcome metadata instead of full output string.

        Args:
            step: StepAction with description and optional hints
            thread_id: Thread ID for execution
            workspace: Thread-specific workspace path (RFC-103)

        Returns:
            Tuple of (collected events, StepResult with outcome metadata)
        """
        from langchain_core.messages import HumanMessage

        start = time.perf_counter()
        events: list[StreamEvent] = []
        output = ""  # Still collect for Layer 1 final report
        budget = _ActStreamBudget(max_subagent_tasks_per_wave=self._max_subagent_tasks_per_wave())
        outcomes: list[dict] = []  # RFC-211: Collect outcome metadata

        try:
            logger.debug(
                "Executing step %s: %s [hints: tools=%s, subagent=%s]",
                step.id,
                preview_first(step.description, 100),
                step.tools,
                step.subagent,
            )

            configurable: dict[str, Any] = {
                "thread_id": thread_id,
                "soothe_step_tools": step.tools,
                "soothe_step_subagent": step.subagent,
                "soothe_step_expected_output": step.expected_output,
            }
            if workspace:
                configurable["workspace"] = workspace
            # RFC-609: Inject goal briefing on thread switch (for single-step execution)
            if self._goal_context_manager:
                goal_briefing = self._goal_context_manager.get_execute_briefing()
                if goal_briefing:
                    configurable["soothe_goal_briefing"] = goal_briefing
                    logger.info(
                        "Execute briefing injected for step %s (%d chars)",
                        step.id,
                        len(goal_briefing),
                    )
            # Pass current_decision for middleware to inject agent loop output contract
            # Note: For single step execution, we don't have LoopState here
            # The middleware should check for absence and not inject contract
            config = {"configurable": configurable}

            step_body = f"Execute: {step.description}"
            stream = self.core_agent.astream(
                {"messages": [HumanMessage(content=step_body)]},
                config=config,
                stream_mode=["messages", "updates", "custom"],
                subgraphs=True,
            )

            # Stream events and collect outcome metadata (RFC-211)
            tool_call_count = 0
            async for final_output, event, tc_count, _msg_list in self._stream_and_collect(
                stream, budget=budget
            ):
                if event is not None:
                    events.append(event)
                elif final_output is not None:
                    output = final_output
                    tool_call_count = tc_count
                    # Note: Single step execution doesn't need messages for token tracking
                    # Token tracking is primarily for sequential Act waves

            duration_ms = int((time.perf_counter() - start) * 1000)

            # RFC-211: Aggregate outcomes from all tools in this step
            # Use the first outcome as primary (future: merge multiple)
            primary_outcome = (
                outcomes[0]
                if outcomes
                else {
                    "type": "generic",
                    "tool_name": "unknown",
                    "tool_call_id": f"step_{step.id}",
                    "success_indicators": {},
                    "entities": [],
                    "size_bytes": len(output.encode("utf-8")),
                }
            )

            # IG-148: Add CoreAgent input/output evidence
            primary_outcome["step_input"] = step_body  # HumanMessage content sent to Layer 1
            primary_outcome["output_summary"] = create_output_summary(output)  # Truncated findings

            logger.info(
                "Step %s completed successfully in %dms (hints: tools=%s, tool_calls: %d, subagent_cap_hit=%s)",
                step.id,
                duration_ms,
                step.tools or "none",
                tool_call_count,
                budget.hit_subagent_cap,
            )

            return events, StepResult(
                step_id=step.id,
                success=True,
                outcome=primary_outcome,  # RFC-211: outcome metadata
                duration_ms=duration_ms,
                thread_id=thread_id,
                tool_call_count=tool_call_count,
                subagent_task_completions=budget.subagent_task_completions,
                hit_subagent_cap=budget.hit_subagent_cap,
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
                outcome={"type": "error", "error": error_msg},  # RFC-211: error outcome
                error=error_msg,
                error_type=self._classify_error_severity(e),
                duration_ms=duration_ms,
                thread_id=thread_id,
                subagent_task_completions=0,
                hit_subagent_cap=False,
            )

    async def _stream_and_collect(
        self,
        stream: AsyncGenerator,
        *,
        budget: _ActStreamBudget | None = None,
    ) -> AsyncGenerator[tuple[str | None, StreamEvent | None, int, list[BaseMessage]], None]:
        """Stream events immediately while accumulating output and counting tool calls.

        This is the canonical streaming method that yields events as they arrive
        for real-time display, while also collecting output content for the final
        result.

        RFC-211: Also extracts tool_call_id and generates outcome metadata.
        IG-151: Collects AIMessage objects for token usage extraction.

        Args:
            stream: Async iterator from agent.astream()
            budget: Optional Act wave budget (subagent ``task`` cap, IG-130).

        Yields:
            Tuple of (output, event, tool_call_count, messages):
            - When event is not None: yield (None, event, 0, []) for immediate display
            - At end: yield (combined_output, None, tool_call_count, messages) for final result
        """
        from langchain_core.messages import AIMessage, ToolMessage

        from soothe.cognition.agent_loop.result_cache import ToolResultCache
        from soothe.tools.metadata_generator import generate_outcome_metadata

        chunks: list[str] = []
        tool_call_count = 0
        messages: list[BaseMessage] = []  # IG-151: Collect messages for token extraction

        # RFC-211: Initialize cache and collect outcomes
        cache = ToolResultCache(
            budget.thread_id if budget and hasattr(budget, "thread_id") else "unknown"
        )
        outcomes: list[dict] = []

        stream_chunk_count = 0  # Debug counter

        def _maybe_cap_subagent_tasks(msg: ToolMessage) -> bool:
            """Return True if the stream must stop (cap exceeded)."""
            if budget is None:
                return False
            if getattr(msg, "name", "") != "task":
                return False
            budget.subagent_task_completions += 1
            cap = budget.max_subagent_tasks_per_wave
            if cap > 0 and budget.subagent_task_completions > cap:
                budget.hit_subagent_cap = True
                logger.warning(
                    "Subagent task cap reached (%s > %s); stopping Act stream consumption",
                    budget.subagent_task_completions,
                    cap,
                )
                return True
            return False

        async for chunk in stream:
            stream_chunk_count += 1

            # Handle tuple format (namespace, mode, data) - deepagents canonical
            if isinstance(chunk, tuple) and len(chunk) == _TUPLE_LEN:
                namespace, mode, data = chunk

                # Yield event immediately for real-time display
                # EventProcessor will handle filtering and rendering
                yield None, chunk, 0, []

                # Also extract content for output collection
                if mode == "messages" and not namespace:
                    # Handle tuple format (msg, metadata) from deepagents streaming
                    if isinstance(data, tuple) and len(data) >= _MSG_TUPLE_LEN:
                        msg, _metadata = data
                        if isinstance(msg, ToolMessage):
                            # Count tool calls
                            tool_call_count += 1
                            tool_call_id = msg.tool_call_id
                            tool_name = msg.name or "unknown"

                            if _maybe_cap_subagent_tasks(msg):
                                break

                            # Extract tool result content (still needed for Layer 1)
                            content = msg.content
                            if isinstance(content, str) and content:
                                chunks.append(content)
                            elif isinstance(content, list):
                                for c in content:
                                    if isinstance(c, str):
                                        chunks.append(c)
                                    elif isinstance(c, dict) and "text" in c:
                                        chunks.append(c["text"])

                            # RFC-211: Generate structured metadata for agentic loop
                            outcome = generate_outcome_metadata(tool_name, content, tool_call_id)

                            # RFC-211: Cache large results
                            content_str = content if isinstance(content, str) else str(content)
                            file_ref = cache.save(tool_call_id, content_str, outcome)
                            if file_ref:
                                outcome["file_ref"] = file_ref

                            outcomes.append(outcome)

                            # Compact tool execution log: one line with essential info
                            logger.debug(
                                "[Act Phase TOOL] #%d %s(%s) → %s, %dB%s",
                                tool_call_count,
                                tool_name,
                                tool_call_id,
                                outcome.get("type", "unknown"),
                                outcome.get("size_bytes", 0),
                                f", cached={file_ref}" if file_ref else "",
                            )
                        elif isinstance(msg, AIMessage):
                            # IG-151: Collect AIMessage for token extraction
                            messages.append(msg)
                            # Extract AI response content
                            if isinstance(msg.content, str) and msg.content:
                                chunks.append(msg.content)
                            elif isinstance(msg.content, list):
                                for c in msg.content:
                                    if isinstance(c, str):
                                        chunks.append(c)
                                    elif isinstance(c, dict) and "text" in c:
                                        chunks.append(c["text"])
                    # Handle list format [msg, metadata] (legacy compatibility)
                    elif isinstance(data, list) and len(data) >= _LIST_MIN_LEN:
                        msg_chunk = data[0]
                        if isinstance(msg_chunk, ToolMessage):
                            tool_call_count += 1
                            tool_call_id = msg_chunk.tool_call_id
                            tool_name = msg_chunk.name or "unknown"

                            if _maybe_cap_subagent_tasks(msg_chunk):
                                break

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

                            # RFC-211: Generate metadata for legacy format
                            if isinstance(msg_chunk, ToolMessage):
                                outcome = generate_outcome_metadata(
                                    tool_name, content, tool_call_id
                                )

                                content_str = content if isinstance(content, str) else str(content)
                                file_ref = cache.save(tool_call_id, content_str, outcome)
                                if file_ref:
                                    outcome["file_ref"] = file_ref

                                outcomes.append(outcome)
            # Handle dict chunks (standard LangGraph format)
            elif isinstance(chunk, dict):
                if "model" in chunk:
                    model_data = chunk["model"]
                    if isinstance(model_data, dict) and "messages" in model_data:
                        cap_break = False
                        for msg in model_data["messages"]:
                            if isinstance(msg, ToolMessage):
                                tool_call_count += 1
                                tool_call_id = msg.tool_call_id
                                tool_name = msg.name or "unknown"

                                if _maybe_cap_subagent_tasks(msg):
                                    cap_break = True
                                    break

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

                                # RFC-211: Generate metadata for dict format
                                if isinstance(msg, ToolMessage):
                                    outcome = generate_outcome_metadata(
                                        tool_name, content, tool_call_id
                                    )

                                    content_str = (
                                        content if isinstance(content, str) else str(content)
                                    )
                                    file_ref = cache.save(tool_call_id, content_str, outcome)
                                    if file_ref:
                                        outcome["file_ref"] = file_ref

                                    outcomes.append(outcome)

                        if cap_break:
                            break
                elif "content" in chunk:
                    chunks.append(str(chunk["content"]))
                elif "output" in chunk:
                    chunks.append(str(chunk["output"]))
                elif "text" in chunk:
                    chunks.append(str(chunk["text"]))
            elif hasattr(chunk, "content"):
                chunks.append(str(chunk.content))

        # Final yield with combined output and tool call count
        yield "".join(chunks), None, tool_call_count, messages

    def _build_sequential_input(self, steps: list) -> str:
        """Build combined input for sequential execution.

        Args:
            steps: Steps to combine

        Returns:
            Combined input string
        """
        descriptions = [f"{i + 1}. {step.description}" for i, step in enumerate(steps)]
        body = "Execute these steps sequentially:\n" + "\n".join(descriptions)
        return body

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
            return f"{exc_type}: {preview_first(error_str, 200)}"

        return fallback

    def _classify_error_severity(self, exc: Exception) -> str:
        """Classify error severity using structured SDK error codes.

        Determines whether an error is fatal (non-retryable) or retryable
        by checking SDK-specific attributes rather than keyword matching.

        Non-retryable errors:
        - LangChain ContextOverflowError (context limit exceeded)
        - HTTP 401 (authentication error)
        - HTTP 403 (permission denied)
        - HTTP 413 (request too large)
        - OpenAI error code "invalid_parameter_error"

        Args:
            exc: The exception to classify

        Returns:
            "fatal" for non-retryable errors, "execution" for retryable errors
        """
        from langchain_core.exceptions import ContextOverflowError

        # LangChain dedicated context limit exception
        if isinstance(exc, ContextOverflowError):
            return "fatal"

        # Check status_code attribute (OpenAI/Anthropic APIStatusError)
        status_code = getattr(exc, "status_code", None)
        if status_code in (401, 403, 413):  # Auth/Permission/Too Large
            return "fatal"

        # OpenAI error code attribute
        error_code = getattr(exc, "code", None)
        if error_code == "invalid_parameter_error":
            return "fatal"

        return "execution"

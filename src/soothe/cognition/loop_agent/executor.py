"""ACT phase logic for Layer 2 agentic loop (RFC-0008)."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from soothe.cognition.loop_agent.schemas import AgentDecision, LoopState, StepAction, StepResult

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

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
    ) -> None:
        """Initialize ACT phase.

        Args:
            core_agent: Layer 1 CoreAgent for step execution
            max_parallel_steps: Max steps per wave; ``0`` means unlimited (RFC-201 / concurrency).
            config: Optional Soothe config for Act wave caps (IG-130).
        """
        self.core_agent = core_agent
        self._max_parallel_steps = max_parallel_steps
        self._config = config

    def _max_subagent_tasks_per_wave(self) -> int:
        """Configured cap on root-level ``task`` tool completions (0 = unlimited)."""
        if self._config is None:
            return 0
        return max(0, int(self._config.agentic.max_subagent_tasks_per_wave))

    def _layer2_output_contract_suffix(self) -> str:
        """Anti-repetition instructions appended to Layer 2 Act user messages."""
        if self._config is None or not self._config.agentic.layer2_output_contract_enabled:
            return ""
        return (
            "\n\n<SOOTHE_LAYER2_OUTPUT_CONTRACT>\n"
            "- After tool or subagent results arrive, add at most two short wrap-up sentences in your own words.\n"
            "- Do NOT paste the full tool/subagent output again unless the user explicitly asked for a "
            "verbatim repeat.\n"
            "- If the tool output already satisfies the user-visible deliverable, stop there.\n"
            "</SOOTHE_LAYER2_OUTPUT_CONTRACT>\n"
        )

    def _should_use_isolated_sequential_thread(self, steps: list) -> bool:
        """True when this sequential wave should run on a fresh checkpoint branch (IG-131)."""
        if self._config is None or not self._config.agentic.sequential_act_isolated_thread:
            return False
        if self._config.agentic.sequential_act_isolate_when_step_subagent_hint:
            return any(bool(getattr(s, "subagent", None)) for s in steps)
        return True

    async def _merge_isolated_act_into_parent_thread(
        self,
        *,
        parent_thread_id: str,
        child_thread_id: str,
    ) -> None:
        """Append messages from an isolated Act checkpoint branch onto the canonical thread."""
        graph = self.core_agent.graph
        cfg_child = {"configurable": {"thread_id": child_thread_id}}
        cfg_parent = {"configurable": {"thread_id": parent_thread_id}}
        try:
            snap = await graph.aget_state(cfg_child)
        except Exception:
            logger.debug(
                "Isolated Act merge skipped: failed to read child thread %s",
                child_thread_id,
                exc_info=True,
            )
            return
        if snap is None or not getattr(snap, "values", None):
            return
        msgs = snap.values.get("messages")
        if not msgs:
            logger.debug("Isolated Act merge skipped: no messages on child thread %s", child_thread_id)
            return
        try:
            await graph.aupdate_state(cfg_parent, {"messages": list(msgs)})
            logger.info(
                "Merged isolated sequential Act thread %s → %s (%d messages)",
                child_thread_id,
                parent_thread_id,
                len(msgs),
            )
        except Exception:
            logger.exception(
                "Failed merging isolated Act thread %s into parent %s",
                child_thread_id,
                parent_thread_id,
            )

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
            "Executing %d steps in mode: %s (max_parallel_steps=%d)",
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
                results.append(
                    StepResult(
                        step_id=step.id,
                        success=True,
                        output=output,
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
                self._execute_step_collecting_events(step, f"{state.thread_id}__step_{i}", state.workspace)
            )
            for i, step in enumerate(steps)
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
                    error_type=self._classify_error_severity(result),
                    duration_ms=0,
                    thread_id=f"{state.thread_id}__step_{i}",
                    subagent_task_completions=0,
                    hit_subagent_cap=False,
                )
            else:
                events, step_result = result
                # Yield collected events first
                for event in events:
                    yield event
                # Then yield the result
                yield step_result

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

        start = time.perf_counter()
        output = ""
        event_count = 0  # Track events for debugging
        budget = _ActStreamBudget(max_subagent_tasks_per_wave=self._max_subagent_tasks_per_wave())
        act_thread_id = state.thread_id
        isolated_child_id: str | None = None
        if self._should_use_isolated_sequential_thread(steps):
            isolated_child_id = f"{state.thread_id}__l2act{uuid.uuid4().hex[:12]}"
            act_thread_id = isolated_child_id
            logger.info(
                "Sequential Act using isolated thread %s (merge → %s)",
                isolated_child_id,
                state.thread_id,
            )

        try:
            configurable: dict[str, Any] = {"thread_id": act_thread_id}
            if state.workspace:
                configurable["workspace"] = state.workspace
            stream = self.core_agent.astream(
                {"messages": [HumanMessage(content=combined_description)]},
                config={"configurable": configurable},
                stream_mode=["messages", "updates", "custom"],
                subgraphs=True,
            )

            tool_call_count = 0
            async for final_output, event, tc_count in self._stream_and_collect(stream, budget=budget):
                if event is not None:
                    event_count += 1
                    yield event
                elif final_output is not None:
                    output = final_output
                    tool_call_count = tc_count

            if isolated_child_id is not None:
                await self._merge_isolated_act_into_parent_thread(
                    parent_thread_id=state.thread_id,
                    child_thread_id=isolated_child_id,
                )

            duration_ms = int((time.perf_counter() - start) * 1000)

            logger.info(
                "Sequential wave (%d steps) completed in %dms — output len %d, events %d, tool_calls %d "
                "(subagent_tasks=%d cap_hit=%s)",
                len(steps),
                duration_ms,
                len(output),
                event_count,
                tool_call_count,
                budget.subagent_task_completions,
                budget.hit_subagent_cap,
            )

            for sr in self._step_results_for_chunk(
                steps,
                success=True,
                output=output,
                error=None,
                error_type=None,
                duration_ms=duration_ms,
                tool_call_count=tool_call_count,
                thread_id=state.thread_id,
                subagent_task_completions=budget.subagent_task_completions,
                hit_subagent_cap=budget.hit_subagent_cap,
            ):
                yield sr

        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("Sequential execution failed")

            error_msg = self._extract_error_message(e, "Sequential execution failed")
            et = self._classify_error_severity(e)

            for sr in self._step_results_for_chunk(
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
            ):
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

        Args:
            step: StepAction with description and optional hints
            thread_id: Thread ID for execution
            workspace: Thread-specific workspace path (RFC-103)

        Returns:
            Tuple of (collected events, StepResult)
        """
        from langchain_core.messages import HumanMessage

        start = time.perf_counter()
        events: list[StreamEvent] = []
        output = ""
        budget = _ActStreamBudget(max_subagent_tasks_per_wave=self._max_subagent_tasks_per_wave())

        try:
            logger.debug(
                "Executing step %s: %s [hints: tools=%s, subagent=%s]",
                step.id,
                step.description[:100],
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
            config = {"configurable": configurable}

            step_body = f"Execute: {step.description}{self._layer2_output_contract_suffix()}"
            stream = self.core_agent.astream(
                {"messages": [HumanMessage(content=step_body)]},
                config=config,
                stream_mode=["messages", "updates", "custom"],
                subgraphs=True,
            )

            # Stream events and collect for parallel execution
            tool_call_count = 0
            async for final_output, event, tc_count in self._stream_and_collect(stream, budget=budget):
                if event is not None:
                    events.append(event)
                elif final_output is not None:
                    output = final_output
                    tool_call_count = tc_count

            duration_ms = int((time.perf_counter() - start) * 1000)

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
                output=output,
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
    ) -> AsyncGenerator[tuple[str | None, StreamEvent | None, int], None]:
        """Stream events immediately while accumulating output and counting tool calls.

        This is the canonical streaming method that yields events as they arrive
        for real-time display, while also collecting output content for the final
        result.

        Args:
            stream: Async iterator from agent.astream()
            budget: Optional Act wave budget (subagent ``task`` cap, IG-130).

        Yields:
            Tuple of (output, event, tool_call_count):
            - When event is not None: yield (None, event, 0) for immediate display
            - At end: yield (combined_output, None, tool_call_count) for final result
        """
        from langchain_core.messages import AIMessage, ToolMessage

        chunks: list[str] = []
        tool_call_count = 0

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
            # Handle tuple format (namespace, mode, data) - deepagents canonical
            if isinstance(chunk, tuple) and len(chunk) == _TUPLE_LEN:
                namespace, mode, data = chunk

                # Yield event immediately for real-time display
                # EventProcessor will handle filtering and rendering
                yield None, chunk, 0

                # Also extract content for output collection
                if mode == "messages" and not namespace:
                    # Handle tuple format (msg, metadata) from deepagents streaming
                    if isinstance(data, tuple) and len(data) >= _MSG_TUPLE_LEN:
                        msg, _metadata = data
                        if isinstance(msg, ToolMessage):
                            # Count tool calls
                            tool_call_count += 1
                            if _maybe_cap_subagent_tasks(msg):
                                break
                            # Extract tool result content
                            content = msg.content
                            if isinstance(content, str) and content:
                                chunks.append(content)
                            elif isinstance(content, list):
                                for c in content:
                                    if isinstance(c, str):
                                        chunks.append(c)
                                    elif isinstance(c, dict) and "text" in c:
                                        chunks.append(c["text"])
                        elif isinstance(msg, AIMessage):
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
            # Handle dict chunks (standard LangGraph format)
            elif isinstance(chunk, dict):
                if "model" in chunk:
                    model_data = chunk["model"]
                    if isinstance(model_data, dict) and "messages" in model_data:
                        cap_break = False
                        for msg in model_data["messages"]:
                            if isinstance(msg, ToolMessage):
                                tool_call_count += 1
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
        yield "".join(chunks), None, tool_call_count

    def _build_sequential_input(self, steps: list) -> str:
        """Build combined input for sequential execution.

        Args:
            steps: Steps to combine

        Returns:
            Combined input string
        """
        descriptions = [f"{i + 1}. {step.description}" for i, step in enumerate(steps)]
        body = "Execute these steps sequentially:\n" + "\n".join(descriptions)
        return body + self._layer2_output_contract_suffix()

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

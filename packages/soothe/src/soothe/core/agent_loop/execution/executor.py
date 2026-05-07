"""Execute phase logic for AgentLoop (RFC-201)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage

from soothe.core.agent_loop.analysis.metadata_generator import (
    PLANNER_OUTCOME_PREVIEW_CAP,
)
from soothe.core.agent_loop.execution.act_wave_finalize import (
    DELEGATE_FINAL_WAVE_CAP,
    compute_act_wave_finalize,
    provenance_is_task_delegate,
)
from soothe.core.agent_loop.state.schemas import (
    AgentDecision,
    LoopState,
    StepAction,
    StepResult,
)
from soothe.core.agent_loop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.utils.observability.langfuse import merge_langfuse_runnable_config
from soothe.utils.text_preview import create_output_summary, log_preview, preview, preview_first

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.config import SootheConfig
    from soothe.core.agent import CoreAgent
    from soothe.core.agent_loop.context.goal_context_manager import GoalContextManager

logger = logging.getLogger(__name__)


def _log_dependency_execution_residual(
    decision: AgentDecision,
    *,
    local_done: set[str],
    failed_sticky: set[str],
) -> None:
    """Emit a warning when dependency execution stopped with steps never started (IG-379).

    Typical causes: unsatisfied or mistyped dependency ids, cycles, or steps blocked behind
    failures (failed step ids are not in ``local_done`` but are excluded from ``never_started``).
    """
    never_started = [
        s for s in decision.steps if s.id not in local_done and s.id not in failed_sticky
    ]
    if not never_started:
        return
    details: list[str] = []
    for s in never_started:
        deps = s.dependencies or []
        unresolved = [x for x in deps if x not in local_done]
        details.append(f"id={s.id!r} unresolved_dependencies={unresolved!r}")
    logger.warning(
        "[Execute] dependency mode finished with %d/%d step(s) never started: %s",
        len(never_started),
        len(decision.steps),
        "; ".join(details),
    )


@dataclass
class _ActStreamBudget:
    """Mutable counters for a single CoreAgent stream (IG-130)."""

    max_subagent_tasks_per_wave: int = 0
    subagent_task_completions: int = 0
    hit_subagent_cap: bool = False


_TUPLE_LEN = 3
# ``task`` tool return text cap per invocation before joining (delegate finals).
_DELEGATE_FINAL_PER_TASK_CAP = 80_000

# Type for stream events yielded during execution
StreamEvent = tuple[tuple[str, ...], str, Any]  # (namespace, mode, data)


class Executor:
    """Execute phase: Execute steps via Layer 1 CoreAgent.

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
        max_parallel_steps: int = 16,
        config: SootheConfig | None = None,
        goal_context_manager: GoalContextManager | None = None,
    ) -> None:
        """Initialize Execute phase.

        Args:
            core_agent: Layer 1 CoreAgent for step execution
            max_parallel_steps: Max steps per wave; ``0`` means unlimited (RFC-201 / concurrency).
            config: Optional Soothe config for Act wave caps (IG-130).
            goal_context_manager: Optional GoalContextManager for goal briefing injection (RFC-217).
        """
        self.core_agent = core_agent
        self._max_parallel_steps = max_parallel_steps
        self._config = config
        self._goal_context_manager = goal_context_manager

    def _executor_langfuse_merge_for_stream(
        self, base: dict[str, Any], *, thread_id: str | None
    ) -> dict[str, Any]:
        """Merge Langfuse callback into RunnableConfig with execute-phase run name (IG-377)."""
        if self._config is None:
            return base
        tn = (self._config.observability.langfuse.trace_name or "").strip()
        run_name = f"{tn}:execute-step" if tn else "execute-step"
        return merge_langfuse_runnable_config(
            base,
            self._config,
            session_id=thread_id,
            run_name=run_name,
        )

    async def _claude_runner_config_extras(self, thread_id: str) -> dict[str, Any]:
        """Load Claude session ids + durability handle for subagent resume (IG-202)."""
        if not thread_id or self._config is None:
            return {}
        try:
            from soothe.core.resolver import resolve_durability

            d = resolve_durability(self._config)
            info = await d.get_thread(thread_id)
            extras: dict[str, Any] = {"soothe_durability": d}
            if info:
                extras["claude_sessions"] = dict(info.metadata.claude_sessions)
            return extras
        except Exception:
            logger.debug("Claude runner config extras failed", exc_info=True)
            return {}

    def _max_subagent_tasks_per_wave(self) -> int:
        """Configured cap on root-level ``task`` tool completions (0 = unlimited)."""
        if self._config is None:
            return 0
        return max(0, int(self._config.agent_loop.max_subagent_tasks_per_wave))

    @staticmethod
    def _intent_type_for_prompt(state: LoopState) -> str | None:
        """Intent primary label for CoreAgent prompt scenario blocks (IG-384)."""
        intent = getattr(state, "intent", None)
        if intent is not None and hasattr(intent, "intent_type"):
            raw = getattr(intent, "intent_type", None)
            if raw:
                return str(raw)
        return None

    @staticmethod
    def _execute_graph_input(
        messages: list[Any],
        *,
        routing_classification: Any | None = None,
        workspace: str | None = None,
        git_status: dict[str, Any] | None = None,
        intent_type: str | None = None,
        synthesis_scenario: str | None = None,
    ) -> dict[str, Any]:
        """Build LangGraph input for execute waves (mirrors runner ``_stream_phase`` keys; IG-349, IG-383)."""
        out: dict[str, Any] = {"messages": messages}
        if routing_classification is not None:
            out["routing_classification"] = routing_classification
        if workspace:
            out["workspace"] = workspace
        if git_status is not None:
            out["git_status"] = git_status
        if intent_type:
            out["intent_type"] = intent_type
        if synthesis_scenario:
            out["synthesis_scenario"] = synthesis_scenario
        return out

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

    def _record_execute_wave_for_finalize(
        self,
        state: LoopState,
        messages: list[BaseMessage],
        *,
        parallel_multi_step: bool,
        delegate_final_text: str | None = None,
    ) -> None:
        """Apply resolved Act-wave visible text to state (IG-199, IG-355, IG-357).

        Resolution is centralized in :func:`~soothe.core.agent_loop.execution.act_wave_finalize.compute_act_wave_finalize`.
        """
        root_text = (
            ""
            if parallel_multi_step
            else self._assemble_assistant_text_from_stream_messages(messages).strip()
        )
        snap = compute_act_wave_finalize(
            parallel_multi_step=parallel_multi_step,
            root_assistant_text=root_text,
            delegate_final_text=delegate_final_text,
        )
        state.last_execute_wave_parallel_multi_step = parallel_multi_step
        state.last_wave_answer_from_delegate_final = provenance_is_task_delegate(snap)
        state.last_execute_assistant_text = snap.visible_text

    def _assemble_assistant_text_from_stream_messages(self, messages: list[BaseMessage]) -> str:
        """Extract assistant-visible text from CoreAgent stream message list.

        Matches the selection rules used for AgentLoop final-report streaming: prefer
        concatenated ``AIMessageChunk`` text over a trailing non-chunk ``AIMessage``.

        Args:
            messages: Messages collected from ``_stream_and_collect`` (AI entries only).

        Returns:
            Stripped assistant text, or empty string if none.
        """
        accumulated_chunks = ""
        final_ai_message_text = ""
        for msg in messages:
            if not isinstance(msg, (AIMessage, AIMessageChunk)):
                continue
            content = msg.content
            extracted_text = ""
            if isinstance(content, str):
                extracted_text = content
            elif isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        parts.append(block["text"])
                    elif isinstance(block, str):
                        parts.append(block)
                extracted_text = "".join(parts)

            if isinstance(msg, AIMessageChunk) and extracted_text:
                accumulated_chunks += extracted_text
            elif isinstance(msg, AIMessage) and extracted_text:
                final_ai_message_text = extracted_text

        last_ai_text = (
            accumulated_chunks
            if len(accumulated_chunks) >= len(final_ai_message_text)
            else final_ai_message_text
        )
        return last_ai_text.strip()

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
                "tokens: actual=%d prompt=%d completion=%d",
                actual_tokens,
                token_usage.get("prompt", 0),
                token_usage.get("completion", 0),
            )
        elif output:
            # Fallback: use tiktoken for accurate estimation
            from soothe.utils.token_counting import count_tokens

            estimated_tokens = count_tokens(output)
            state.total_tokens_used += estimated_tokens

        # Use configurable context limit (IG-151)
        if self._config is not None:
            context_limit = self._config.agent_loop.context_window_limit
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
        ready_steps = decision.get_ready_steps(state.dependency_completion_ids())

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
                    "type": "subagent" if subagent_task_completions > 0 else "generic",
                    "size_bytes": len(output.encode("utf-8")) if output else 0,
                }
                if subagent_task_completions > 0:
                    outcome_data["tool_name"] = "task"
                # Add step input (combined_description for sequential waves)
                if combined_description:
                    outcome_data["step_input"] = combined_description
                # Add output summary (truncated)
                if output:
                    outcome_data["output_summary"] = create_output_summary(output)
                    stripped = output.strip()
                    if stripped:
                        cap = PLANNER_OUTCOME_PREVIEW_CAP
                        outcome_data["wave_join_preview"] = stripped[:cap] + (
                            "…" if len(stripped) > cap else ""
                        )

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

    def _append_parallel_wave_ledger(
        self,
        state: LoopState,
        steps: list[StepAction],
        gather_results: list[Any],
    ) -> None:
        """Append RFC-214 Human/AI ledger pairs for each parallel step (IG-374).

        Sequential execution records the ledger inside ``_execute_sequential_chunk``. Parallel
        waves historically skipped ``state.loop_messages``, which hid execute evidence from
        subsequent ``plan-assess`` / ``plan-generate`` prompts built in ``PromptBuilder``.

        Args:
            state: Loop state whose ``loop_messages`` list is extended in wave order.
            steps: Ready steps for this wave (same order as ``gather_results``).
            gather_results: Results from ``asyncio.gather`` over per-step tasks — each entry is
                either an exception or the tuple returned by ``_execute_step_collecting_events``.
        """
        from langchain_core.messages import AIMessage

        from soothe.core.agent_loop.utils.stream_normalize import extract_text_from_message_content

        for i, step in enumerate(steps):
            raw = gather_results[i]
            human_msg = LoopHumanMessage(
                content=f"Execute: {step.description}",
                thread_id=state.thread_id,
                iteration=state.iteration,
                goal_summary=(state.goal[:200] if state.goal else None),
                workspace=state.workspace,
                phase="execute_step",
                step_id=step.id,
            )
            if isinstance(raw, Exception):
                err_text = str(raw).strip() or repr(raw)
                state.loop_messages.append(human_msg)
                state.loop_messages.append(
                    LoopAIMessage(
                        content=f"Step failed: {err_text}",
                        thread_id=state.thread_id,
                        iteration=state.iteration,
                        phase="execute_step",
                        step_id=step.id,
                    )
                )
                continue

            _events, step_result, step_messages, delegate_final = raw
            ai_messages = [m for m in step_messages if isinstance(m, AIMessage)]
            final_ai = ai_messages[-1] if ai_messages else None

            if step_result.success:
                content = ""
                if final_ai is not None:
                    ledger_body = self._ledger_execute_ai_content(
                        messages=step_messages,
                        final_ai_msg=final_ai,
                        total_steps=1,
                    )
                    content = (ledger_body or "").strip()
                    if not content:
                        content = extract_text_from_message_content(
                            getattr(final_ai, "content", None)
                        ).strip()
                df = (delegate_final or "").strip()
                if not content and df:
                    content = (
                        df if len(df) <= DELEGATE_FINAL_WAVE_CAP else df[:DELEGATE_FINAL_WAVE_CAP]
                    )
                if not content:
                    content = "Step completed with no AI text captured"
            else:
                content = (step_result.error or "").strip() or "Step failed"
                if final_ai is not None:
                    ledger_body = self._ledger_execute_ai_content(
                        messages=step_messages,
                        final_ai_msg=final_ai,
                        total_steps=1,
                    )
                    lb = (ledger_body or "").strip()
                    if lb:
                        content = lb

            meta = getattr(final_ai, "response_metadata", {}) if final_ai is not None else {}
            state.loop_messages.append(human_msg)
            state.loop_messages.append(
                LoopAIMessage(
                    content=content,
                    thread_id=state.thread_id,
                    iteration=state.iteration,
                    phase="execute_step",
                    step_id=step.id,
                    response_metadata=meta,
                )
            )

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
        # Branched LangGraph thread_id for parallel checkpoint isolation; StepResult keeps logical thread_id.
        logical_tid = state.thread_id
        itype = self._intent_type_for_prompt(state)
        tasks = [
            asyncio.create_task(
                self._execute_step_collecting_events(
                    step,
                    logical_tid,
                    state.workspace,
                    stream_thread_id=(
                        f"{logical_tid}__p{step.id}" if len(steps) > 1 else logical_tid
                    ),
                    routing_classification=getattr(state, "routing_classification", None),
                    git_status=state.git_status,
                    intent_type=itype,
                )
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
        single_wave_messages: list[BaseMessage] = []
        wave_delegate_final = ""
        wave_delegate_parts: list[str] = []
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
                events, step_result, step_messages, delegate_final = result
                if len(steps) == 1:
                    single_wave_messages = step_messages
                    wave_delegate_final = delegate_final
                df = (delegate_final or "").strip()
                if df:
                    wave_delegate_parts.append(df)
                all_step_results.append(step_result)
                # Yield collected events first
                for event in events:
                    yield event
                # Then yield the result
                yield step_result

        # RFC-214: parallel waves must update the ledger like sequential chunks so Plan-assess
        # receives prior execute evidence via ``state.loop_messages`` (IG-374).
        self._append_parallel_wave_ledger(state, steps, results)

        parallel_multi = len(steps) > 1
        merged_parallel_delegate = "\n\n---\n\n".join(wave_delegate_parts)
        if parallel_multi:
            self._record_execute_wave_for_finalize(
                state,
                [],
                parallel_multi_step=True,
                delegate_final_text=merged_parallel_delegate or None,
            )
        else:
            self._record_execute_wave_for_finalize(
                state,
                single_wave_messages,
                parallel_multi_step=False,
                delegate_final_text=wave_delegate_final or None,
            )

        # Aggregate metrics from parallel execution
        if all_step_results:
            # For parallel, use max output length across steps
            # RFC-211: Use outcome metadata to get size
            output_lengths = [
                r.outcome.get("size_bytes", 0) for r in all_step_results if r.success and r.outcome
            ]
            max_output_len = max(output_lengths) if output_lengths else 0
            # Token totals: parallel steps stream independently; per-step messages are not merged here.
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
        """Execute a wave of steps with ledger recording (RFC-214).

        Args:
            steps: Non-empty slice of ready steps
            state: Loop state

        Yields:
            StreamEvent during execution, then one StepResult per step in ``steps``.
        """
        # RFC-214: Build N Human messages (one per step) instead of combined description
        step_messages = self._build_batch_human_messages(steps, state)

        # Compact input summary log
        logger.debug(
            "[Execute-Seq] steps=%d thread=%s workspace=%s",
            len(steps),
            state.thread_id[:12] if state.thread_id else "none",
            state.workspace if state.workspace else "none",
        )

        start = time.perf_counter()
        event_count = 0
        budget = _ActStreamBudget(max_subagent_tasks_per_wave=self._max_subagent_tasks_per_wave())

        try:
            configurable: dict[str, Any] = {"thread_id": state.thread_id}
            if state.workspace:
                configurable["workspace"] = state.workspace
            # Pass current_decision for middleware to inject agent loop output contract
            if state.current_decision:
                configurable["current_decision"] = state.current_decision
            # RFC-217: Inject goal briefing on thread switch
            if self._goal_context_manager:
                goal_briefing = await self._goal_context_manager.get_execute_briefing()
                if goal_briefing:
                    configurable["soothe_goal_briefing"] = goal_briefing
                    logger.info("Execute briefing injected (%d chars)", len(goal_briefing))
            configurable.update(await self._claude_runner_config_extras(state.thread_id))

            # RFC-214: Execute batch with N Human messages
            graph_config: dict[str, Any] = {"configurable": configurable}
            if self._config is not None:
                graph_config = self._executor_langfuse_merge_for_stream(
                    graph_config, thread_id=state.thread_id
                )
            stream = self.core_agent.astream(
                self._execute_graph_input(
                    step_messages,  # N messages instead of combined description
                    routing_classification=getattr(state, "routing_classification", None),
                    workspace=state.workspace,
                    git_status=state.git_status,
                    intent_type=self._intent_type_for_prompt(state),
                ),
                config=graph_config,
                stream_mode=["messages", "updates", "custom"],
                subgraphs=True,
            )

            tool_call_count = 0
            messages: list[BaseMessage] = []
            output = ""
            async for final_output, event, tc_count, msg_list, _ in self._stream_and_collect(
                stream, budget=budget
            ):
                if event is not None:
                    event_count += 1
                    yield event
                elif final_output is not None:
                    output = final_output
                    tool_call_count = tc_count
                    messages = msg_list

            duration_ms = int((time.perf_counter() - start) * 1000)

            logger.info(
                "[Wave-Seq] steps=%d dur=%dms evts=%d tools=%d subagents=%d cap=%s (RFC-214)",
                len(steps),
                duration_ms,
                event_count,
                tool_call_count,
                budget.subagent_task_completions,
                budget.hit_subagent_cap,
            )

            # RFC-214: Extract N outcomes and record N adjacent pairs in ledger
            step_outcomes = self._extract_sequential_outcomes(messages, steps, state)
            step_results = self._record_batch_ledger_pairs(
                state,
                step_messages,
                step_outcomes,
                steps,
                duration_ms=duration_ms,
                subagent_task_completions=budget.subagent_task_completions,
                hit_subagent_cap=budget.hit_subagent_cap,
                tool_call_count=tool_call_count,
            )

            # Aggregate metrics into LoopState
            self._aggregate_wave_metrics(step_results, output, messages, state)
            self._record_execute_wave_for_finalize(
                state,
                messages,
                parallel_multi_step=False,
            )

            # Yield step results
            for sr in step_results:
                yield sr

        except asyncio.CancelledError:
            logger.info("Sequential execution cancelled")
            raise
        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("Sequential execution failed")

            error_msg = self._extract_error_message(e, "Sequential execution failed")
            self._classify_error_severity(e)

            # RFC-214: Record error outcomes in ledger
            step_outcomes = {}
            for step in steps:
                step_outcomes[step.id] = LoopAIMessage(
                    content=f"Step failed: {error_msg}",
                    thread_id=state.thread_id,
                    iteration=state.iteration,
                    phase="execute_step",
                    step_id=step.id,
                )

            # Record error pairs in ledger
            step_messages_err = self._build_batch_human_messages(steps, state)
            from soothe.core.agent_loop.state.schemas import StepResult

            n_err = len(steps)
            eb, er = divmod(max(duration_ms, 0), n_err) if n_err else (0, 0)
            err_durations = [eb + (1 if j < er else 0) for j in range(n_err)]

            step_results = []
            for i, step in enumerate(steps):
                # Append Human-AI error pair
                state.loop_messages.append(step_messages_err[i])
                state.loop_messages.append(step_outcomes[step.id])

                # Build error StepResult
                result = StepResult(
                    step_id=step.id,
                    success=False,
                    outcome={"type": "error", "error": error_msg},
                    duration_ms=err_durations[i],
                    thread_id=state.thread_id,
                    error=error_msg,
                )
                step_results.append(result)

            # Aggregate metrics (includes error count)
            self._aggregate_wave_metrics(step_results, "", [], state)
            self._record_execute_wave_for_finalize(state, [], parallel_multi_step=False)

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
        local_done = set(state.dependency_completion_ids())
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

        _log_dependency_execution_residual(
            decision, local_done=local_done, failed_sticky=failed_sticky
        )

    async def _execute_step_collecting_events(
        self,
        step: StepAction,
        thread_id: str,
        workspace: str | None = None,
        *,
        stream_thread_id: str | None = None,
        routing_classification: Any | None = None,
        git_status: dict[str, Any] | None = None,
        intent_type: str | None = None,
    ) -> tuple[list[StreamEvent], StepResult, list[BaseMessage], str]:
        """Execute single step, collecting events for later yielding.

        Used for parallel execution where we can't yield in real-time.
        Events are collected and returned with the final result.

        RFC-211: Collects outcome metadata instead of full output string.
        IG-355: Fourth tuple element is joined ``task`` tool delegate-final text for finalize.

        Args:
            step: StepAction with description and optional hints
            thread_id: Logical thread ID for StepResult, logs, and durability lookups
            workspace: Thread-specific workspace path (RFC-103)
            stream_thread_id: Optional LangGraph ``thread_id`` for this stream (parallel isolation)
            routing_classification: Loop routing payload for middleware (IG-349, IG-383).
            git_status: Optional git snapshot for prompt XML (RFC-104).
            intent_type: Optional intent label for scenario guidance (IG-384).

        Returns:
            Tuple of ``(events, StepResult, AI messages for IG-199, delegate_final_text)``.
        """
        start = time.perf_counter()
        events: list[StreamEvent] = []
        output = ""  # Still collect for Layer 1 final report
        budget = _ActStreamBudget(max_subagent_tasks_per_wave=self._max_subagent_tasks_per_wave())
        outcomes: list[dict] = []  # RFC-211: Collect outcome metadata

        try:
            logger.debug(
                "execute step: id=%s desc=%s hints: subagent=%s",
                step.id,
                preview_first(step.description, 100),
                step.subagent,
            )

            cfg_thread = stream_thread_id or thread_id
            configurable: dict[str, Any] = {
                "thread_id": cfg_thread,
                "soothe_step_subagent": step.subagent,
                "soothe_step_expected_output": step.expected_output,
            }
            if workspace:
                configurable["workspace"] = workspace
            # RFC-217: Inject goal briefing on thread switch (for single-step execution)
            if self._goal_context_manager:
                goal_briefing = await self._goal_context_manager.get_execute_briefing()
                if goal_briefing:
                    configurable["soothe_goal_briefing"] = goal_briefing
                    logger.info(
                        "Execute briefing injected for step %s (%d chars)",
                        step.id,
                        len(goal_briefing),
                    )
            configurable.update(await self._claude_runner_config_extras(thread_id))
            # Pass current_decision for middleware to inject agent loop output contract
            # Note: For single step execution, we don't have LoopState here
            # The middleware should check for absence and not inject contract
            config: dict[str, Any] = {"configurable": configurable}
            if self._config is not None:
                config = self._executor_langfuse_merge_for_stream(config, thread_id=cfg_thread)

            step_body = f"Execute: {step.description}"
            logger.debug("[Human Message] %s", log_preview(step_body, chars=150))
            human_msg = LoopHumanMessage(
                content=step_body,
                thread_id=thread_id,
                iteration=None,  # Single step doesn't have iteration context
                goal_summary=None,  # Could extract from goal_briefing if needed
                workspace=workspace,
                phase="execute_step",
            )
            stream = self.core_agent.astream(
                self._execute_graph_input(
                    [human_msg],
                    routing_classification=routing_classification,
                    workspace=workspace,
                    git_status=git_status,
                    intent_type=intent_type,
                ),
                config=config,
                stream_mode=["messages", "updates", "custom"],
                subgraphs=True,
            )

            # Stream events and collect outcome metadata (RFC-211)
            tool_call_count = 0
            messages: list[BaseMessage] = []
            delegate_final = ""
            async for final_output, event, tc_count, msg_list, df in self._stream_and_collect(
                stream, budget=budget
            ):
                if event is not None:
                    events.append(event)
                elif final_output is not None:
                    output = final_output
                    tool_call_count = tc_count
                    messages = msg_list
                    delegate_final = df

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
                "Step %s completed successfully in %dms (tool_calls: %d, subagent_cap_hit=%s)",
                step.id,
                duration_ms,
                tool_call_count,
                budget.hit_subagent_cap,
            )

            return (
                events,
                StepResult(
                    step_id=step.id,
                    success=True,
                    outcome=primary_outcome,  # RFC-211: outcome metadata
                    duration_ms=duration_ms,
                    thread_id=thread_id,
                    tool_call_count=tool_call_count,
                    subagent_task_completions=budget.subagent_task_completions,
                    hit_subagent_cap=budget.hit_subagent_cap,
                ),
                messages,
                delegate_final,
            )

        except asyncio.CancelledError:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "Step %s cancelled after %dms [subagent=%s]",
                step.id,
                duration_ms,
                step.subagent,
            )
            raise
        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "Step %s failed after %dms [subagent=%s]",
                step.id,
                duration_ms,
                step.subagent,
            )

            error_msg = self._extract_error_message(e, "Step execution failed")

            return (
                events,
                StepResult(
                    step_id=step.id,
                    success=False,
                    outcome={"type": "error", "error": error_msg},  # RFC-211: error outcome
                    error=error_msg,
                    error_type=self._classify_error_severity(e),
                    duration_ms=duration_ms,
                    thread_id=thread_id,
                    subagent_task_completions=0,
                    hit_subagent_cap=False,
                ),
                [],
                "",
            )

    async def _stream_and_collect(
        self,
        stream: AsyncGenerator,
        *,
        budget: _ActStreamBudget | None = None,
    ) -> AsyncGenerator[
        tuple[str | None, StreamEvent | None, int, list[BaseMessage], str],
        None,
    ]:
        """Stream events immediately while accumulating output and counting tool calls.

        This is the canonical streaming method that yields events as they arrive
        for real-time display, while also collecting output content for the final
        result.

        RFC-211: Also extracts tool_call_id and generates outcome metadata.
        IG-151: Collects AIMessage objects for token usage extraction.
        IG-355: Collects ``task`` tool return text (delegate finals) for goal completion when
        subgraph AIMessages are not folded into root-graph act aggregation.

        Args:
            stream: Async iterator from agent.astream()
            budget: Optional Act wave budget (subagent ``task`` cap, IG-130).

        Yields:
            Tuple of ``(output, event, tool_call_count, messages, delegate_final_text)``:
            - When event is not None: immediate display chunk (delegate_final_text empty).
            - At end: combined_output, ``tool_call_count`` (root graph plus namespaced
              subgraph ``ToolMessage`` totals), root AIMessages list, and joined ``task``
              tool bodies (ordered, capped)—empty string when no ``task`` tools ran.
        """
        from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

        from soothe.core.agent_loop.analysis.metadata_generator import (
            generate_outcome_metadata,
        )
        from soothe.core.agent_loop.utils.stream_normalize import (
            extract_text_from_message_content,
            iter_messages_for_act_aggregation,
            iter_messages_for_delegate_task_scan,
            iter_namespaced_tool_messages,
            join_text_fragments,
        )

        chunks: list[str] = []
        tool_call_count = 0
        subgraph_tool_call_count = 0
        messages: list[BaseMessage] = []  # IG-151: Collect messages for token extraction
        delegate_task_final_parts: list[str] = []
        delegate_task_ids_seen: set[str] = set()

        # RFC-211: Collect per-tool outcome metadata (structured, no filesystem cache; IG-387)
        outcomes: list[dict] = []

        # Track tool call arguments from AI messages for logging
        tool_call_args: dict[str, dict[str, Any]] = {}

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
                # Yield event immediately for real-time display
                yield None, chunk, 0, [], ""

            stop_act_stream = False
            for msg in iter_messages_for_act_aggregation(chunk):
                if isinstance(msg, ToolMessage):
                    tool_call_count += 1
                    tool_call_id = msg.tool_call_id
                    tool_name = msg.name or "unknown"

                    if _maybe_cap_subagent_tasks(msg):
                        stop_act_stream = True
                        break

                    content = msg.content
                    text_out = extract_text_from_message_content(content)
                    if text_out:
                        # Truncate large tool outputs in aggregated stream text; full payloads
                        # remain in CoreAgent graph state (and deepagents eviction when enabled).
                        max_tool_output_chars = 10_000
                        if len(text_out) > max_tool_output_chars:
                            truncated = preview(
                                text_out,
                                mode="chars",
                                first=max_tool_output_chars // 2,
                                last=max_tool_output_chars // 2,
                            )
                            chunks.append(truncated)
                        else:
                            chunks.append(text_out)

                    outcome = generate_outcome_metadata(tool_name, content, tool_call_id)

                    outcomes.append(outcome)

                    if tool_name == "task" and text_out.strip():
                        tc_id = tool_call_id or ""
                        if not (tc_id and tc_id in delegate_task_ids_seen):
                            if tc_id:
                                delegate_task_ids_seen.add(tc_id)
                            clipped = text_out.strip()
                            if len(clipped) > _DELEGATE_FINAL_PER_TASK_CAP:
                                clipped = clipped[:_DELEGATE_FINAL_PER_TASK_CAP]
                            delegate_task_final_parts.append(clipped)

                    # Format arguments for logging
                    args = tool_call_args.get(tool_call_id or "")
                    args_str = log_preview(str(args), chars=100) if args else ""
                    logger.debug(
                        "Tool #%d %s(%s) args=%s → %s, %dB",
                        tool_call_count,
                        tool_name,
                        tool_call_id,
                        args_str,
                        outcome.get("type", "unknown"),
                        outcome.get("size_bytes", 0),
                    )
                elif isinstance(msg, AIMessageChunk):
                    messages.append(msg)  # Collect chunks for assistant text extraction
                    t = extract_text_from_message_content(msg.content)
                    if t:
                        chunks.append(t)
                    # Extract tool call arguments from chunks
                    for tc in getattr(msg, "tool_call_chunks", []):
                        if isinstance(tc, dict) and "id" in tc:
                            tc_id = tc["id"]
                            args_str = tc.get("args", "")
                            if args_str:
                                try:
                                    import json

                                    tool_call_args[tc_id] = json.loads(args_str)
                                except (json.JSONDecodeError, TypeError):
                                    pass  # Args may be partial in streaming
                    # Also check merged tool_calls
                    for tc in getattr(msg, "tool_calls", []):
                        if isinstance(tc, dict) and "id" in tc:
                            tool_call_args[tc["id"]] = tc.get("args", {})
                elif isinstance(msg, AIMessage):
                    messages.append(msg)
                    t = extract_text_from_message_content(msg.content)
                    if t:
                        chunks.append(t)
                        logger.debug("[AI Message] %s", log_preview(t, chars=150))
                    # Extract tool call arguments
                    for tc in getattr(msg, "tool_calls", []):
                        if isinstance(tc, dict) and "id" in tc:
                            tool_call_args[tc["id"]] = tc.get("args", {})

            for ns_tuple, tm in iter_namespaced_tool_messages(chunk):
                subgraph_tool_call_count += 1
                body_preview = log_preview(
                    extract_text_from_message_content(getattr(tm, "content", "")),
                    chars=160,
                )
                logger.info(
                    "[SubagentTool] ns=%s name=%s id=%s preview=%s",
                    "/".join(ns_tuple) if ns_tuple else "()",
                    getattr(tm, "name", "") or "unknown",
                    getattr(tm, "tool_call_id", "") or "",
                    body_preview,
                )

            for task_msg in iter_messages_for_delegate_task_scan(chunk):
                text_out = extract_text_from_message_content(task_msg.content)
                if not text_out.strip():
                    continue
                tc_id = getattr(task_msg, "tool_call_id", "") or ""
                if tc_id and tc_id in delegate_task_ids_seen:
                    continue
                if tc_id:
                    delegate_task_ids_seen.add(tc_id)
                clipped = text_out.strip()
                if len(clipped) > _DELEGATE_FINAL_PER_TASK_CAP:
                    clipped = clipped[:_DELEGATE_FINAL_PER_TASK_CAP]
                delegate_task_final_parts.append(clipped)

            if stop_act_stream:
                break

            if isinstance(chunk, dict) and "model" not in chunk:
                if "content" in chunk:
                    chunks.append(str(chunk["content"]))
                elif "output" in chunk:
                    chunks.append(str(chunk["output"]))
                elif "text" in chunk:
                    chunks.append(str(chunk["text"]))
            elif hasattr(chunk, "content") and not isinstance(chunk, (tuple, dict)):
                chunks.append(str(chunk.content))

        delegate_final_text = ""
        if delegate_task_final_parts:
            delegate_final_text = "\n\n".join(delegate_task_final_parts)
            if len(delegate_final_text) > DELEGATE_FINAL_WAVE_CAP:
                delegate_final_text = delegate_final_text[:DELEGATE_FINAL_WAVE_CAP]

        total_tool_calls = tool_call_count + subgraph_tool_call_count
        # Final yield with combined output and tool call count
        yield join_text_fragments(chunks), None, total_tool_calls, messages, delegate_final_text

    def _build_batch_human_messages(
        self,
        steps: list,
        state: LoopState,
    ) -> list[LoopHumanMessage]:
        """Build N LoopHumanMessage inputs for batch execution (RFC-214).

        Each step gets its own LoopHumanMessage with step_id for ledger pairing.

        Args:
            steps: Steps to execute in this wave
            state: Current loop state with iteration/thread context

        Returns:
            List of LoopHumanMessage instances (one per step)
        """
        messages = []
        for step in steps:
            msg = LoopHumanMessage(
                content=f"Execute: {step.description}",
                thread_id=state.thread_id,
                iteration=state.iteration,
                goal_summary=state.goal[:200] if state.goal else None,
                workspace=state.workspace,
                phase="execute_step",  # RFC-214: per-step phase
                step_id=step.id,  # RFC-214: step_id for pairing
            )
            messages.append(msg)

        return messages

    def _ledger_execute_ai_content(
        self,
        *,
        messages: list[BaseMessage],
        final_ai_msg: BaseMessage,
        total_steps: int,
    ) -> str:
        """Body for ``LoopAIMessage`` ledger entries (RFC-214, IG-373).

        The stream collector may end with an ``AIMessage`` whose ``content`` is empty while
        assistant-visible text lives in earlier ``AIMessageChunk`` entries — same situation as
        ``_assemble_assistant_text_from_stream_messages`` / Act-wave finalize.

        Args:
            messages: Full message list from ``_stream_and_collect`` (AI + chunk entries).
            final_ai_msg: AIMessage chosen for this step by sequential pairing.
            total_steps: Number of steps in this execute wave.

        Returns:
            Non-empty string when any root assistant text exists; otherwise ``""``.
        """
        from soothe.core.agent_loop.utils.stream_normalize import extract_text_from_message_content

        direct = extract_text_from_message_content(getattr(final_ai_msg, "content", None)).strip()
        if direct:
            return direct
        if total_steps != 1:
            return ""
        assembled = self._assemble_assistant_text_from_stream_messages(messages).strip()
        return assembled

    def _extract_sequential_outcomes(
        self,
        messages: list[BaseMessage],
        steps: list,
        state: LoopState,
    ) -> dict[str, LoopAIMessage]:
        """Extract outcomes from sequential batch (RFC-214).

        Sequential execution produces messages in order.
        Rule: For N steps, assign last N AIMessages to steps in order.

        Args:
            messages: All messages from batch execution stream
            steps: Steps being executed (for step_id matching)
            state: Current loop state

        Returns:
            step_id → LoopAIMessage mapping (one outcome per step)
        """
        from langchain_core.messages import AIMessage

        ai_messages = [msg for msg in messages if isinstance(msg, AIMessage)]

        step_outcomes = {}
        if len(ai_messages) >= len(steps):
            # Assign last N AIMessages to steps (sequential order)
            for i, step in enumerate(steps):
                final_ai_msg = ai_messages[-(len(steps) - i)]
                ledger_body = self._ledger_execute_ai_content(
                    messages=messages,
                    final_ai_msg=final_ai_msg,
                    total_steps=len(steps),
                )

                step_outcomes[step.id] = LoopAIMessage(
                    content=ledger_body or final_ai_msg.content,
                    thread_id=state.thread_id,
                    iteration=state.iteration,
                    phase="execute_step",
                    step_id=step.id,
                    response_metadata=getattr(final_ai_msg, "response_metadata", {}),
                )
        else:
            # Fallback: insufficient messages → error outcomes
            for i, step in enumerate(steps):
                if i < len(ai_messages):
                    final_ai_msg = ai_messages[i]
                    ledger_body = self._ledger_execute_ai_content(
                        messages=messages,
                        final_ai_msg=final_ai_msg,
                        total_steps=len(steps),
                    )
                    step_outcomes[step.id] = LoopAIMessage(
                        content=ledger_body or final_ai_msg.content,
                        thread_id=state.thread_id,
                        iteration=state.iteration,
                        phase="execute_step",
                        step_id=step.id,
                    )
                else:
                    # No AIMessage for this step → error outcome
                    step_outcomes[step.id] = LoopAIMessage(
                        content="Step execution failed: no AI response",
                        thread_id=state.thread_id,
                        iteration=state.iteration,
                        phase="execute_step",
                        step_id=step.id,
                    )

        return step_outcomes

    def _record_batch_ledger_pairs(
        self,
        state: LoopState,
        step_messages: list[LoopHumanMessage],
        step_outcomes: dict[str, LoopAIMessage],
        steps: list,
        *,
        duration_ms: int,
        subagent_task_completions: int = 0,
        hit_subagent_cap: bool = False,
        tool_call_count: int = 0,
    ) -> list:
        """Record N adjacent Human-AI pairs in ledger (RFC-214).

        Each step gets paired Human-AI messages in ledger:
        - LoopHumanMessage (input)
        - LoopAIMessage (outcome)
        - Both share same step_id
        - Adjacent in ledger

        Args:
            state: LoopState with ledger (loop_messages field)
            step_messages: Human inputs (one per step)
            step_outcomes: AI outcomes (one per step)
            steps: Step metadata
            duration_ms: Wall time for the whole wave; split across steps so sums match
                goal duration aggregation.
            subagent_task_completions: Count of completed ``task`` tool returns this wave (IG-130).
            hit_subagent_cap: True when the wave stopped early due to subagent cap.
            tool_call_count: Total tool messages observed this wave (first step carries count).

        Returns:
            List of StepResult for metrics/execution tracking
        """
        from soothe.core.agent_loop.state.schemas import StepResult

        # Validate pairing
        assert len(step_messages) == len(steps)
        assert set(step_outcomes.keys()) == {s.id for s in steps}

        n = len(steps)
        base, rem = divmod(max(duration_ms, 0), n) if n else (0, 0)
        step_durations = [base + (1 if j < rem else 0) for j in range(n)]

        # Append N adjacent pairs to ledger
        for i, step in enumerate(steps):
            human_msg = step_messages[i]
            ai_msg = step_outcomes[step.id]

            # Append Human message
            state.loop_messages.append(human_msg)

            # Append AI message (adjacent)
            state.loop_messages.append(ai_msg)

        # Build StepResult for metrics (RFC-211 outcome metadata)
        step_results = []
        for idx, step in enumerate(steps):
            ai_msg = step_outcomes[step.id]

            result = StepResult(
                step_id=step.id,
                success=True,  # Or based on AI message content analysis
                outcome={
                    "type": "generic",
                    "output_summary": ai_msg.content[:300] if ai_msg.content else "",
                },
                duration_ms=step_durations[idx],
                thread_id=state.thread_id,
                tool_call_count=tool_call_count if idx == 0 else 0,
                subagent_task_completions=subagent_task_completions if idx == 0 else 0,
                hit_subagent_cap=hit_subagent_cap if idx == 0 else False,
            )
            step_results.append(result)

        return step_results

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

        IG-295: Enhanced timeout errors include retry metadata for planner revision.

        Args:
            exc: The exception that occurred
            fallback: Fallback message if no specific info found

        Returns:
            Meaningful error message string
        """
        from soothe.middleware.llm_rate_limit import EnhancedTimeoutError

        # IG-295: Enhanced timeout error with metadata
        if isinstance(exc, EnhancedTimeoutError):
            parts = [
                f"Request timed out after {exc.retries} retries",
                f"({exc.timeout_seconds}s timeout)",
            ]
            if exc.prompt_chars > 50000:
                parts.append(f"- large prompt ({exc.prompt_chars:,} chars)")

            return " ".join(parts)

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

        # Check for timeout (generic TimeoutError)
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

        Retryable errors (IG-295):
        - EnhancedTimeoutError (timeout with retries exhausted at middleware)

        Args:
            exc: The exception to classify

        Returns:
            "fatal" for non-retryable errors, "execution" for retryable errors
        """
        from langchain_core.exceptions import ContextOverflowError

        from soothe.middleware.llm_rate_limit import EnhancedTimeoutError

        # Enhanced timeout error (IG-295) - retries exhausted at middleware
        if isinstance(exc, EnhancedTimeoutError):
            # Classified as "execution" (retryable) but retries already attempted
            # Planner can still revise plan based on timeout metadata
            return "execution"

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

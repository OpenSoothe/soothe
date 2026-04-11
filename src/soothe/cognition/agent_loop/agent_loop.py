"""Main AgentLoop orchestration for Layer 2 (RFC-0008)."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.cognition.planning.simple import _default_agent_decision
from soothe.cognition.agent_loop.executor import Executor
from soothe.cognition.agent_loop.reason import ReasonPhase
from soothe.cognition.agent_loop.schemas import AgentDecision, LoopState, ReasonResult
from soothe.cognition.agent_loop.state_manager import Layer2StateManager
from soothe.cognition.agent_loop.working_memory import LoopWorkingMemory
from soothe.protocols.planner import PlanContext, StepResult
from soothe.utils.text_preview import log_preview, preview_first

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.config import SootheConfig
    from soothe.core.agent import CoreAgent
    from soothe.protocols.loop_reasoner import LoopReasonerProtocol

logger = logging.getLogger(__name__)

# Stream chunk format: (namespace: tuple, mode: str, data: Any)
_STREAM_CHUNK_LEN = 3


class AgentLoop:
    """Layer 2: Agentic goal execution as ReAct (Reason then Act).

    Attributes:
        core_agent: Layer 1 CoreAgent for step execution
        loop_reasoner: Protocol for the Reason phase (one LLM call per iteration)
        config: Soothe configuration
    """

    def __init__(
        self,
        core_agent: CoreAgent,
        loop_reasoner: LoopReasonerProtocol,
        config: SootheConfig,
    ) -> None:
        """Initialize AgentLoop.

        Args:
            core_agent: Layer 1 CoreAgent runtime
            loop_reasoner: Reason-phase implementation (planning + assessment)
            config: Soothe configuration
        """
        self.core_agent = core_agent
        self.loop_reasoner = loop_reasoner
        self.config = config

        self.reason_phase = ReasonPhase(loop_reasoner)
        self.executor = Executor(
            core_agent,
            max_parallel_steps=config.execution.concurrency.max_parallel_steps,
            config=config,
        )

    async def run(
        self,
        goal: str,
        thread_id: str,
        max_iterations: int = 8,
    ) -> ReasonResult:
        """Run Reason → Act loop for goal execution.

        Args:
            goal: Goal description to execute
            thread_id: Thread context for execution
            max_iterations: Maximum loop iterations (default: 8)

        Returns:
            ReasonResult with final status and evidence
        """
        final_result = None
        async for event_type, event_data in self.run_with_progress(goal, thread_id, max_iterations=max_iterations):
            if event_type == "completed":
                final_result = event_data["result"] if isinstance(event_data, dict) else event_data
        return final_result or ReasonResult(
            status="replan",
            plan_action="new",
            decision=_default_agent_decision(goal),
            evidence_summary="",
            goal_progress=0.0,
            confidence=0.0,
            reasoning="No result produced",
            soothe_next_action="I need to stop here before completion.",
        )

    async def run_with_progress(
        self,
        goal: str,
        thread_id: str,
        workspace: str | None = None,
        git_status: dict[str, Any] | None = None,
        max_iterations: int = 8,
        reason_conversation_excerpts: list[str] | None = None,  # noqa: ARG002 - Reserved for future use
    ) -> AsyncGenerator[tuple[str, Any], None]:
        """Run loop with progress events (RFC-0020 compliant).

        Yields progress events during execution for display.

        Args:
            goal: Goal description to execute
            thread_id: Thread context for execution
            workspace: Thread-specific workspace path (RFC-103)
            git_status: Optional git snapshot for RFC-104-aligned Reason prompts.
            max_iterations: Maximum loop iterations (default: 8)
            reason_conversation_excerpts: Prior thread lines (User/Assistant) for Reason (IG-128).

        Yields:
            Tuples of (event_type, event_data) for progress updates
        """
        # Initialize Layer 2 state manager (RFC-205)
        state_manager = Layer2StateManager(thread_id, Path(workspace) if workspace else None)

        # Try to recover from checkpoint
        checkpoint = state_manager.load()
        if checkpoint and checkpoint.status == "running":
            logger.info(
                "[Layer2] Recovering from checkpoint at iteration %d",
                checkpoint.iteration,
            )
            # Derive prior conversation from step outputs (RFC-205)
            prior_outputs = state_manager.derive_reason_conversation(limit=10)
            reason_excerpts = prior_outputs
        else:
            # Initialize new checkpoint - NO Layer 1 messages (RFC-205)
            checkpoint = state_manager.initialize(goal, max_iterations)
            reason_excerpts = []  # Start fresh, no prior conversation from Layer 1

        state = LoopState(
            goal=goal,
            thread_id=thread_id,
            workspace=workspace,
            git_status=git_status,
            iteration=checkpoint.iteration,  # Use checkpoint iteration
            max_iterations=max_iterations,
            reason_conversation_excerpts=reason_excerpts,
        )
        wm_cfg = self.config.agentic.working_memory
        if wm_cfg.enabled:
            state.working_memory = LoopWorkingMemory(
                thread_id=thread_id,
                max_inline_chars=wm_cfg.max_inline_chars,
                max_entry_chars_before_spill=wm_cfg.max_entry_chars_before_spill,
            )

        logger.info(
            "[Goal] %s (max_iterations=%d, iteration=%d)", log_preview(goal, 80), max_iterations, state.iteration
        )

        while state.iteration < state.max_iterations:
            iteration_start = time.perf_counter()

            yield (
                "iteration_started",
                {
                    "iteration": state.iteration,
                    "max_iterations": max_iterations,
                },
            )

            reason_result = await self.reason_phase.reason(
                goal=goal,
                state=state,
                context=self._build_plan_context(state),
            )

            yield (
                "reason",
                {
                    "iteration": state.iteration,
                    "status": reason_result.status,
                    "progress": reason_result.goal_progress,
                    "confidence": reason_result.confidence,
                    "soothe_next_action": reason_result.soothe_next_action,
                    "progress_detail": reason_result.progress_detail,
                    "plan_action": reason_result.plan_action,
                },
            )

            import sys as _sys

            print(
                f"[DEBUG-LOOP] reason_result.status={reason_result.status}, is_done()={reason_result.is_done()}",
                file=_sys.stderr,
                flush=True,
            )

            if reason_result.is_done():
                state.previous_reason = reason_result
                state.iteration += 1
                state.total_duration_ms += int((time.perf_counter() - iteration_start) * 1000)

                # RFC-211: Layer 2 signals Layer 1 to generate final report
                final_output = reason_result.full_output or reason_result.evidence_summary
                import sys as _sys

                print(
                    f"[DEBUG-LOOP] is_done=True, full_output={len(reason_result.full_output or '')} chars, evidence={len(reason_result.evidence_summary or '')} chars",
                    file=_sys.stderr,
                    flush=True,
                )
                logger.info(
                    "[Layer1] Starting final report generation (full_output=%d chars, evidence=%d chars)",
                    len(reason_result.full_output or ""),
                    len(reason_result.evidence_summary or ""),
                )

                try:
                    from langchain_core.messages import HumanMessage

                    # Layer 2 sends message to Layer 1 requesting final report
                    report_request = f"""Based on the complete execution history in this thread, generate a comprehensive final report for the goal: {goal}

The report should:
1. Summarize what was accomplished
2. Highlight key findings or outputs
3. Provide actionable results or deliverables
4. Be well-structured with clear sections

Use all tool results and AI responses available in the conversation history to create a comprehensive, coherent final report."""

                    # Send to Layer 1 CoreAgent — accumulate the last complete AI text response
                    last_ai_text = ""
                    chunk_count = 0
                    ai_msg_count = 0
                    async for chunk in self.core_agent.astream(
                        {"messages": [HumanMessage(content=report_request)]},
                        config={"configurable": {"thread_id": state.thread_id}},
                        stream_mode=["messages"],
                        subgraphs=False,
                    ):
                        chunk_count += 1
                        if isinstance(chunk, tuple) and len(chunk) >= 2:
                            mode, data = chunk[0], chunk[1]
                            if mode == "messages":
                                from langchain_core.messages import AIMessage, AIMessageChunk

                                if isinstance(data, tuple) and len(data) >= 2:
                                    msg, _ = data
                                    # AIMessage (non-chunk) marks a completed turn;
                                    # keep the last one with text content.
                                    if isinstance(msg, (AIMessage, AIMessageChunk)):
                                        ai_msg_count += 1
                                        if isinstance(msg, AIMessage) and msg.content:
                                            content = msg.content
                                            if isinstance(content, str):
                                                last_ai_text = content
                                            elif isinstance(content, list):
                                                parts = []
                                                for block in content:
                                                    if isinstance(block, dict) and "text" in block:
                                                        parts.append(block["text"])
                                                    elif isinstance(block, str):
                                                        parts.append(block)
                                                last_ai_text = "".join(parts)

                    logger.info(
                        "[Layer1] Stream completed: %d chunks, %d AI messages, last_ai_text=%d chars",
                        chunk_count,
                        ai_msg_count,
                        len(last_ai_text),
                    )
                    if last_ai_text:
                        final_output = last_ai_text
                        logger.info("[Layer1] Final report generated via CoreAgent (%d chars)", len(final_output))
                    else:
                        logger.warning("[Layer1] No AI text response from CoreAgent, using evidence")

                except Exception as e:
                    # Fallback to evidence on failure
                    logger.warning("[Layer1] Final report generation failed: %s, using evidence", e)

                # Update reason_result with final output
                if final_output != reason_result.full_output:
                    reason_result = reason_result.model_copy(update={"full_output": final_output})

                # Finalize checkpoint (RFC-205)
                state_manager.finalize(status="completed")
                logger.info(
                    "[✓] Goal achieved in %d iterations (%dms)",
                    state.iteration,
                    state.total_duration_ms,
                )
                yield (
                    "completed",
                    {
                        "result": reason_result,
                        "step_results_count": len(state.step_results),
                    },
                )
                return

            decision = self._resolve_decision(reason_result, state)
            if decision is None:
                logger.error("[Reason] No executable decision after reason phase; aborting loop")
                yield (
                    "fatal_error",
                    {"error": "Reason phase returned no executable plan", "step_id": ""},
                )
                return

            if reason_result.plan_action == "new":
                state.completed_step_ids.clear()
                state.current_decision = decision

            yield (
                "plan_decision",
                {
                    "iteration": state.iteration,
                    "steps": [{"id": s.id, "description": preview_first(s.description, 80)} for s in decision.steps],
                    "execution_mode": decision.execution_mode,
                },
            )

            ready_steps = decision.get_ready_steps(state.completed_step_ids)
            for step in ready_steps:
                yield (
                    "step_started",
                    {"description": step.description},
                )

            step_results = []
            async for item in self.executor.execute(
                decision=decision,
                state=state,
            ):
                if isinstance(item, tuple) and len(item) == _STREAM_CHUNK_LEN:
                    yield ("stream_event", item)
                else:
                    step_results.append(item)

            fatal_errors = [r for r in step_results if r.error_type == "fatal"]
            if fatal_errors:
                logger.error(
                    "Fatal error detected, aborting loop: %s",
                    fatal_errors[0].error,
                )
                # Finalize checkpoint on fatal error (RFC-205)
                state_manager.finalize(status="failed")
                yield (
                    "fatal_error",
                    {
                        "error": fatal_errors[0].error,
                        "step_id": fatal_errors[0].step_id,
                    },
                )
                return

            step_desc = {s.id: s.description for s in decision.steps}
            for result in step_results:
                state.add_step_result(result)
                if state.working_memory is not None:
                    # RFC-211: Use outcome metadata for working memory
                    outcome_summary = result.to_evidence_string(truncate=True)
                    state.working_memory.record_step_result(
                        step_id=result.step_id,
                        description=step_desc.get(result.step_id, ""),
                        output=outcome_summary,  # Use outcome summary
                        error=result.error,
                        success=result.success,
                        workspace=state.workspace,
                        thread_id=state.thread_id,
                    )
                yield (
                    "step_completed",
                    {
                        "step_id": result.step_id,
                        "success": result.success,
                        "output_preview": preview_first(result.to_evidence_string(), 100),  # RFC-211: Use outcome
                        "error": result.error or None,
                        "duration_ms": result.duration_ms,
                        "tool_call_count": result.tool_call_count,
                    },
                )

            state.last_wave_tool_call_count = sum(r.tool_call_count for r in step_results)
            state.last_wave_subagent_task_count = sum(r.subagent_task_completions for r in step_results)
            state.last_wave_hit_subagent_cap = any(r.hit_subagent_cap for r in step_results)

            state.previous_reason = reason_result

            # Capture iteration BEFORE increment for event/checkpoint consistency
            iteration_completed = state.iteration
            state.iteration += 1
            state.total_duration_ms += int((time.perf_counter() - iteration_start) * 1000)

            # Record iteration to checkpoint (RFC-205) with pre-increment value
            state_manager.record_iteration(
                iteration=iteration_completed,  # Use pre-increment value
                reason_result=reason_result,
                decision=decision,
                step_results=step_results,
                state=state,
                working_memory=state.working_memory,
            )

            yield (
                "iteration_completed",
                {
                    "iteration": iteration_completed,  # Use pre-increment value
                    "status": reason_result.status,
                    "progress": reason_result.goal_progress,
                    "soothe_next_action": reason_result.soothe_next_action,
                },
            )

            ready_after = decision.get_ready_steps(state.completed_step_ids)
            if ready_after:
                logger.info(
                    "[→] %d step(s) remaining in current plan; next cycle will re-reason",
                    len(ready_after),
                )
            state.current_decision = decision

        logger.warning(
            "[⚠] Max iterations (%d) reached (progress=%.0f%%)",
            state.max_iterations,
            state.previous_reason.goal_progress * 100 if state.previous_reason else 0,
        )

        # Finalize checkpoint (RFC-205)
        state_manager.finalize(status="failed")

        result = state.previous_reason or ReasonResult(
            status="replan",
            plan_action="new",
            decision=_default_agent_decision(state.goal),
            evidence_summary=state.evidence_summary,
            goal_progress=0.0,
            confidence=0.0,
            reasoning="Max iterations reached without completion",
            soothe_next_action="I've hit the iteration limit; I'll pause here.",
        )
        yield (
            "completed",
            {
                "result": result,
                "step_results_count": len(state.step_results),
            },
        )

    def _resolve_decision(
        self,
        reason_result: ReasonResult,
        state: LoopState,
    ) -> AgentDecision | None:
        """Pick the AgentDecision to execute for this Act phase."""
        if reason_result.plan_action == "keep":
            if state.current_decision is None:
                logger.warning("[Reason] plan_action=keep but no current_decision; falling back to new decision")
                return reason_result.decision
            return state.current_decision
        return reason_result.decision

    def _build_plan_context(self, state: LoopState) -> PlanContext:
        """Build planning context with available capabilities and completed steps.

        Args:
            state: Current loop state with step results

        Returns:
            PlanContext with tools, subagents, and completed steps for the reasoner
        """
        available_tools = []
        if hasattr(self.core_agent, "tools") and isinstance(self.core_agent.tools, dict):
            available_tools = list(self.core_agent.tools.keys())

        available_subagents = [name for name, cfg in self.config.subagents.items() if cfg.enabled]

        completed_steps = [
            StepResult(
                step_id=r.step_id,
                outcome=r.outcome if r.success else {"type": "error", "error": r.error or ""},
                success=r.success,
                duration_ms=r.duration_ms,
            )
            for r in state.step_results
        ]

        wm_excerpt: str | None = None
        if state.working_memory is not None:
            rendered = state.working_memory.render_for_reason().strip()
            if rendered:
                wm_excerpt = rendered

        return PlanContext(
            available_capabilities=available_tools + available_subagents,
            recent_messages=list(state.reason_conversation_excerpts),
            completed_steps=completed_steps,
            workspace=state.workspace,
            git_status=state.git_status,
            working_memory_excerpt=wm_excerpt,
        )

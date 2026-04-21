"""Main AgentLoop orchestration (RFC-201)."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.cognition.agent_loop.executor import Executor
from soothe.cognition.agent_loop.final_response_policy import needs_final_thread_synthesis
from soothe.cognition.agent_loop.goal_context_manager import GoalContextManager
from soothe.cognition.agent_loop.planning_utils import _default_agent_decision
from soothe.cognition.agent_loop.reason import PlanPhase
from soothe.cognition.agent_loop.schemas import AgentDecision, LoopState, PlanResult
from soothe.cognition.agent_loop.state_manager import AgentLoopStateManager
from soothe.cognition.agent_loop.stream_chunk_normalize import (
    FinalReportAccumState,
    iter_messages_for_act_aggregation,
    resolve_final_report_text,
    update_final_report_from_message,
)
from soothe.cognition.agent_loop.working_memory import LoopWorkingMemory
from soothe.config.constants import DEFAULT_AGENT_LOOP_MAX_ITERATIONS
from soothe.protocols.planner import PlanContext, StepResult
from soothe.utils.text_preview import log_preview, preview_first

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.config import SootheConfig
    from soothe.core.agent import CoreAgent
    from soothe.protocols.loop_planner import LoopPlannerProtocol

logger = logging.getLogger(__name__)

# Stream chunk format: (namespace: tuple, mode: str, data: Any)
_STREAM_CHUNK_LEN = 3


class AgentLoop:
    """Agentic goal execution using Plan-and-Execute pattern.

    The Plan phase combines planning, progress assessment, and goal-distance estimation.
    The Execute phase runs steps via Layer 1 CoreAgent with thread isolation.

    Attributes:
        core_agent: Layer 1 CoreAgent for step execution
        loop_planner: Protocol for the Plan phase (one LLM call per iteration)
        config: Soothe configuration
    """

    def __init__(
        self,
        core_agent: CoreAgent,
        loop_planner: LoopPlannerProtocol,
        config: SootheConfig,
    ) -> None:
        """Initialize AgentLoop.

        Args:
            core_agent: Layer 1 CoreAgent runtime
            loop_planner: Plan-phase implementation (planning + assessment)
            config: Soothe configuration
        """
        self.core_agent = core_agent
        self.loop_planner = loop_planner
        self.config = config

        self.plan_phase = PlanPhase(loop_planner)
        self.executor = Executor(
            core_agent,
            max_parallel_steps=config.execution.concurrency.max_parallel_steps,
            config=config,
            # Executor receives GoalContextManager per-run (created in run_with_progress)
        )

    async def run(
        self,
        goal: str,
        thread_id: str,
        max_iterations: int = DEFAULT_AGENT_LOOP_MAX_ITERATIONS,
    ) -> PlanResult:
        """Run Plan → Execute loop for goal execution.

        Args:
            goal: Goal description to execute
            thread_id: Thread context for execution
            max_iterations: Maximum loop iterations (default: 8)

        Returns:
            PlanResult with final status and evidence
        """
        final_result = None
        async for event_type, event_data in self.run_with_progress(
            goal, thread_id, max_iterations=max_iterations
        ):
            if event_type == "completed":
                final_result = event_data["result"] if isinstance(event_data, dict) else event_data
        return final_result or PlanResult(
            status="replan",
            plan_action="new",
            decision=_default_agent_decision(goal),
            evidence_summary="",
            goal_progress=0.0,
            confidence=0.0,
            reasoning="No result produced",
            next_action="I need to stop here before completion.",
        )

    async def run_with_progress(
        self,
        goal: str,
        thread_id: str,
        workspace: str | None = None,
        git_status: dict[str, Any] | None = None,
        max_iterations: int = DEFAULT_AGENT_LOOP_MAX_ITERATIONS,
        plan_conversation_excerpts: list[str] | None = None,
        intent: Any | None = None,  # IG-226: Intent classification from unified classifier
    ) -> AsyncGenerator[tuple[str, Any], None]:
        """Run loop with progress events (RFC-0020 compliant).

        Yields progress events during execution for display.

        Args:
            goal: Goal description to execute
            thread_id: Thread context for execution
            workspace: Thread-specific workspace path (RFC-103)
            git_status: Optional git snapshot for RFC-104-aligned Reason prompts.
            max_iterations: Maximum loop iterations (default: 8)
            plan_conversation_excerpts: Prior thread lines (User/Assistant) for Plan phase (IG-128).
            intent: IntentClassification from unified classifier (IG-226). Determines goal handling:
                - thread_continuation: Adjust iteration behavior, reuse working memory
                - new_goal: Normal goal execution flow
                - chitchat: Should not reach here (handled in runner)

        Yields:
            Tuples of (event_type, event_data) for progress updates
        """
        # Initialize AgentLoop state manager (RFC-205)
        state_manager = AgentLoopStateManager(thread_id, Path(workspace) if workspace else None)

        # IG-226: Handle thread continuation intent
        thread_continuation_mode = False
        if intent and hasattr(intent, "intent_type"):
            if intent.intent_type == "thread_continuation":
                thread_continuation_mode = True
                logger.info(
                    "[AgentLoop] Thread continuation mode: reuse_current_goal=%s",
                    intent.reuse_current_goal if hasattr(intent, "reuse_current_goal") else False,
                )
                # Thread continuation may benefit from fewer iterations (follow-up actions)
                # but keep max_iterations unchanged for now - let Plan phase determine completion

        # RFC-609: Create GoalContextManager for goal-level context injection
        from soothe.config.models import GoalContextConfig

        goal_context_config = getattr(self.config.agentic, "goal_context", GoalContextConfig())
        goal_context_manager = GoalContextManager(state_manager, goal_context_config)

        # Try to recover from checkpoint (RFC-608: loop-scoped)
        checkpoint = state_manager.load()
        if checkpoint and checkpoint.status == "running":
            # Get current goal iteration (RFC-608: per-goal tracking)
            current_goal_index = checkpoint.current_goal_index
            if current_goal_index >= 0 and current_goal_index < len(checkpoint.goal_history):
                goal_record = checkpoint.goal_history[current_goal_index]
                iteration = goal_record.iteration
                logger.info(
                    "Recovering from checkpoint at iteration %d (goal: %s)",
                    iteration,
                    goal_record.goal_id,
                )
            else:
                # No active goal in recovered checkpoint - shouldn't happen if status==running
                logger.error("Checkpoint status is 'running' but no active goal found")
                iteration = 0
                goal_record = None

            # Derive prior conversation from step outputs (RFC-205)
            prior_outputs = state_manager.derive_plan_conversation(limit=10)
            # RFC-609: Add goal-level context to plan excerpts
            plan_goal_excerpts = goal_context_manager.get_plan_context()
            runner_prior = list(plan_conversation_excerpts or [])
            plan_excerpts = plan_goal_excerpts + runner_prior + list(prior_outputs)
        else:
            # Initialize new checkpoint (RFC-608: pass thread_id, not goal)
            checkpoint = state_manager.initialize(thread_id, max_iterations)
            iteration = 0  # New goal starts at iteration 0
            # RFC-609: Inject previous goal context for Plan phase
            plan_goal_excerpts = goal_context_manager.get_plan_context()
            # Prior Human/Assistant turns from LangGraph checkpointer (IG-128, IG-198)
            runner_prior = list(plan_conversation_excerpts or [])
            plan_excerpts = plan_goal_excerpts + runner_prior
            # Create new goal_record for this goal execution
            goal_record = state_manager.start_new_goal(goal, max_iterations)
            checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
            checkpoint.goal_history.append(goal_record)
            checkpoint.status = "running"
            state_manager.save(checkpoint)

        state = LoopState(
            goal=goal,
            thread_id=thread_id,
            workspace=workspace,
            git_status=git_status,
            iteration=iteration,  # Use recovered or initial iteration
            max_iterations=max_iterations,
            plan_conversation_excerpts=plan_excerpts,
        )

        # IG-226: Set thread continuation flag for working memory context
        if thread_continuation_mode:
            state.thread_continuation = True  # Add flag to LoopState if it exists
            logger.debug("[AgentLoop] Thread continuation flag set for working memory enhancement")

        wm_cfg = self.config.agentic.working_memory
        if wm_cfg.enabled:
            state.working_memory = LoopWorkingMemory(
                thread_id=thread_id,
                max_inline_chars=wm_cfg.max_inline_chars,
                max_entry_chars_before_spill=wm_cfg.max_entry_chars_before_spill,
            )

            # IG-226: Thread continuation working memory enhancement
            # Reuse current thread's working memory content more aggressively
            if thread_continuation_mode:
                logger.info("[AgentLoop] Thread continuation: working memory context reuse enabled")
                # Working memory will automatically load from thread persistence
                # No special handling needed - it already loads existing entries

        logger.info(
            "[Goal] %s (max_iterations=%d, iteration=%d, thread_continuation=%s)",
            log_preview(goal, 80),
            max_iterations,
            state.iteration,
            thread_continuation_mode,
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

            plan_result = await self.plan_phase.plan(
                goal=goal,
                state=state,
                context=self._build_plan_context(state),
            )

            yield (
                "plan",
                {
                    "iteration": state.iteration,
                    "status": plan_result.status,
                    "progress": plan_result.goal_progress,
                    "confidence": plan_result.confidence,
                    "next_action": plan_result.next_action,  # Full action (no truncation)
                    "reasoning": plan_result.reasoning,  # Combined chain (backward compatible)
                    "assessment_reasoning": plan_result.assessment_reasoning,
                    "plan_reasoning": plan_result.plan_reasoning,
                    "plan_action": plan_result.plan_action,
                },
            )

            if plan_result.is_done():
                state.previous_plan = plan_result
                state.iteration += 1
                state.total_duration_ms += int((time.perf_counter() - iteration_start) * 1000)

                # RFC-211 / IG-199: Final report — adaptive second CoreAgent turn vs last Execute text
                final_output = plan_result.full_output or plan_result.evidence_summary
                mode = self.config.agentic.final_response
                run_synth = needs_final_thread_synthesis(state, plan_result, mode)

                if not run_synth:
                    reuse = (state.last_execute_assistant_text or "").strip()
                    final_output = (
                        reuse
                        or (plan_result.full_output or "").strip()
                        or (plan_result.evidence_summary or "").strip()
                    )
                    logger.info(
                        "Final response: branch=reuse_execute assistant_chars=%d full_output_chars=%d",
                        len(reuse),
                        len(plan_result.full_output or ""),
                    )
                else:
                    logger.info(
                        "Starting final report generation (full_output=%d chars, evidence=%d chars, mode=%s)",
                        len(plan_result.full_output or ""),
                        len(plan_result.evidence_summary or ""),
                        mode,
                    )

                    try:
                        from langchain_core.messages import HumanMessage

                        # Agentic loop sends message to core agent requesting final report
                        report_request = f"""Based on the complete execution history in this thread, generate a comprehensive final report for the goal: {goal}

The report should:
1. Summarize what was accomplished
2. Highlight key findings or outputs
3. Provide actionable results or deliverables
4. Be well-structured with clear sections

Use all tool results and AI responses available in the conversation history to create a comprehensive, coherent final report."""

                        logger.debug(
                            "[Human Message] Final report request: %s",
                            log_preview(report_request, chars=150),
                        )
                        accum = FinalReportAccumState()
                        chunk_count = 0
                        async for chunk in self.core_agent.astream(
                            {"messages": [HumanMessage(content=report_request)]},
                            config={"configurable": {"thread_id": state.thread_id}},
                            stream_mode=["messages"],
                            subgraphs=False,
                        ):
                            chunk_count += 1
                            for msg in iter_messages_for_act_aggregation(chunk):
                                update_final_report_from_message(accum, msg)

                        last_ai_text = resolve_final_report_text(accum)

                        logger.info(
                            "Stream completed: %d chunks, %d AI messages, accumulated_chunks=%d chars, final_ai_message=%d chars, selected=%d chars",
                            chunk_count,
                            accum.ai_msg_count,
                            len(accum.accumulated_chunks),
                            len(accum.final_ai_message_text),
                            len(last_ai_text),
                        )
                        if last_ai_text:
                            final_output = last_ai_text
                            logger.info(
                                "Final report generated via CoreAgent (%d chars)", len(final_output)
                            )
                        else:
                            logger.warning("No AI text response from CoreAgent, using evidence")

                    except Exception as e:
                        # Fallback to evidence on failure
                        logger.warning("Final report generation failed: %s, using evidence", e)

                # Update plan_result with final output
                if final_output != plan_result.full_output:
                    plan_result = plan_result.model_copy(update={"full_output": final_output})

                # Finalize goal (RFC-608: mark completed, update metrics)
                state_manager.finalize_goal(goal_record, final_output)
                logger.info(
                    "[✓] Goal achieved in %d iterations (%dms)",
                    state.iteration,
                    state.total_duration_ms,
                )
                yield (
                    "completed",
                    {
                        "result": plan_result,
                        "step_results_count": len(state.step_results),
                    },
                )
                return

            decision = self._resolve_decision(plan_result, state)
            if decision is None:
                logger.error("[Reason] No executable decision after reason phase; aborting loop")
                yield (
                    "fatal_error",
                    {"error": "Reason phase returned no executable plan", "step_id": ""},
                )
                return

            if plan_result.plan_action == "new":
                state.completed_step_ids.clear()
                state.current_decision = decision

            yield (
                "plan_decision",
                {
                    "iteration": state.iteration,
                    "steps": [
                        {"id": s.id, "description": preview_first(s.description, 80)}
                        for s in decision.steps
                    ],
                    "execution_mode": decision.execution_mode,
                },
            )

            ready_steps = decision.get_ready_steps(state.completed_step_ids)
            for step in ready_steps:
                yield (
                    "step_started",
                    {"step_id": step.id, "description": step.description},
                )

            step_results = []
            # RFC-609: Create Executor with GoalContextManager for this run
            run_executor = Executor(
                self.core_agent,
                max_parallel_steps=self.config.execution.concurrency.max_parallel_steps,
                config=self.config,
                goal_context_manager=goal_context_manager,
            )
            async for item in run_executor.execute(
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
                # Mark goal as failed (RFC-608: update goal_record status)
                goal_record.status = "failed"
                goal_record.completed_at = datetime.now(UTC)
                checkpoint.status = "ready_for_next_goal"
                checkpoint.thread_health_metrics.consecutive_goal_failures += 1
                checkpoint.thread_health_metrics.last_goal_status = "failed"
                state_manager.save(checkpoint)
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
                        "output_preview": preview_first(
                            result.to_evidence_string(), 100
                        ),  # RFC-211: Use outcome
                        "error": result.error or None,
                        "duration_ms": result.duration_ms,
                        "tool_call_count": result.tool_call_count,
                    },
                )

            state.last_wave_tool_call_count = sum(r.tool_call_count for r in step_results)
            state.last_wave_subagent_task_count = sum(
                r.subagent_task_completions for r in step_results
            )
            state.last_wave_hit_subagent_cap = any(r.hit_subagent_cap for r in step_results)

            state.previous_plan = plan_result

            # Capture iteration BEFORE increment for event/checkpoint consistency
            iteration_completed = state.iteration
            state.iteration += 1
            state.total_duration_ms += int((time.perf_counter() - iteration_start) * 1000)

            # Record iteration to checkpoint (RFC-205) with pre-increment value
            state_manager.record_iteration(
                goal_record=goal_record,
                iteration=iteration_completed,  # Use pre-increment value
                plan_result=plan_result,
                decision=decision,
                step_results=step_results,
                state=state,
                working_memory=state.working_memory,
            )

            yield (
                "iteration_completed",
                {
                    "iteration": iteration_completed,  # Use pre-increment value
                    "status": plan_result.status,
                    "progress": plan_result.goal_progress,
                    "next_action": plan_result.next_action,  # Full action (no truncation)
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
            state.previous_plan.goal_progress * 100 if state.previous_plan else 0,
        )

        # Mark goal as failed due to max iterations (RFC-608)
        goal_record.status = "failed"
        goal_record.completed_at = datetime.now(UTC)
        checkpoint.status = "ready_for_next_goal"
        checkpoint.thread_health_metrics.consecutive_goal_failures += 1
        checkpoint.thread_health_metrics.last_goal_status = "failed"
        state_manager.save(checkpoint)

        result = state.previous_plan or PlanResult(
            status="replan",
            plan_action="new",
            decision=_default_agent_decision(state.goal),
            evidence_summary=state.evidence_summary,
            goal_progress=0.0,
            confidence=0.0,
            reasoning="Max iterations reached without completion",
            next_action="I've hit the iteration limit; I'll pause here.",
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
        plan_result: PlanResult,
        state: LoopState,
    ) -> AgentDecision | None:
        """Pick the AgentDecision to execute for this Execute phase."""
        if plan_result.plan_action == "keep":
            if state.current_decision is None:
                logger.warning(
                    "[Plan] plan_action=keep but no current_decision; falling back to new decision"
                )
                return plan_result.decision
            return state.current_decision
        return plan_result.decision

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
            recent_messages=list(state.plan_conversation_excerpts),
            completed_steps=completed_steps,
            workspace=state.workspace,
            git_status=state.git_status,
            working_memory_excerpt=wm_excerpt,
        )

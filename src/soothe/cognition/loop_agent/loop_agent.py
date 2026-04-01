"""Main LoopAgent orchestration for Layer 2 (RFC-0008)."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from soothe.cognition.loop_agent.executor import Executor
from soothe.cognition.loop_agent.judge import JudgePhase
from soothe.cognition.loop_agent.planner import PlannerPhase
from soothe.cognition.loop_agent.schemas import JudgeResult, LoopState
from soothe.protocols.planner import PlanContext, StepResult

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.config import SootheConfig
    from soothe.core.agent import CoreAgent
    from soothe.protocols.judge import JudgeProtocol
    from soothe.protocols.planner import PlannerProtocol

logger = logging.getLogger(__name__)

# Stream chunk format: (namespace: tuple, mode: str, data: Any)
_STREAM_CHUNK_LEN = 3


class LoopAgent:
    """Layer 2: Agentic Goal Execution Loop.

    Executes single goals through PLAN → ACT → JUDGE iterations.
    Implements the core Layer 2 architecture from RFC-0008.

    Attributes:
        core_agent: Layer 1 CoreAgent for step execution
        planner: Planner protocol for decision making
        judge: Judge protocol for evaluation
        config: Soothe configuration
    """

    def __init__(
        self,
        core_agent: CoreAgent,
        planner: PlannerProtocol,
        judge: JudgeProtocol,
        config: SootheConfig,
    ) -> None:
        """Initialize LoopAgent.

        Args:
            core_agent: Layer 1 CoreAgent runtime
            planner: Planner for PLAN phase
            judge: Judge for JUDGE phase
            config: Soothe configuration
        """
        self.core_agent = core_agent
        self.planner = planner
        self.judge = judge
        self.config = config

        # Phase components
        self.planner_phase = PlannerPhase(planner)
        self.executor = Executor(core_agent)
        self.judge_phase = JudgePhase(judge)

    async def run(
        self,
        goal: str,
        thread_id: str,
        max_iterations: int = 8,
    ) -> JudgeResult:
        """Run PLAN → ACT → JUDGE loop for goal execution.

        Args:
            goal: Goal description to execute
            thread_id: Thread context for execution
            max_iterations: Maximum loop iterations (default: 8)

        Returns:
            JudgeResult with final status and evidence
        """
        # Collect all events and return final result
        final_result = None
        async for event_type, event_data in self.run_with_progress(goal, thread_id, max_iterations):
            if event_type == "completed":
                final_result = event_data
        return final_result or JudgeResult(
            status="replan",
            evidence_summary="",
            goal_progress=0.0,
            confidence=0.0,
            reasoning="No result produced",
        )

    async def run_with_progress(
        self,
        goal: str,
        thread_id: str,
        workspace: str | None = None,
        max_iterations: int = 8,
    ) -> AsyncGenerator[tuple[str, Any], None]:
        """Run loop with progress events (RFC-0020 compliant).

        Yields progress events during execution for display.

        Args:
            goal: Goal description to execute
            thread_id: Thread context for execution
            workspace: Thread-specific workspace path (RFC-103)
            max_iterations: Maximum loop iterations (default: 8)

        Yields:
            Tuples of (event_type, event_data) for progress updates
        """
        state = LoopState(
            goal=goal,
            thread_id=thread_id,
            workspace=workspace,
            max_iterations=max_iterations,
        )

        logger.info(
            "[Goal] %s (max_iterations=%d, workspace=%s)",
            goal[:80],
            max_iterations,
            workspace or "default",
        )

        while state.iteration < state.max_iterations:
            iteration_start = time.perf_counter()

            # Yield iteration started event
            yield (
                "iteration_started",
                {
                    "iteration": state.iteration,
                    "max_iterations": max_iterations,
                },
            )

            # PLAN Phase
            decision = await self.planner_phase.plan(
                goal=goal,
                state=state,
                context=self._build_plan_context(state),
            )

            # Yield plan decision
            yield (
                "plan_decision",
                {
                    "iteration": state.iteration,
                    "steps": [{"id": s.id, "description": s.description[:80]} for s in decision.steps],
                    "execution_mode": decision.execution_mode,
                },
            )

            # ACT Phase - yield step_started before execution
            ready_steps = decision.get_ready_steps(state.completed_step_ids)

            # Yield step_started for each ready step (Level 2)
            for step in ready_steps:
                yield (
                    "step_started",
                    {"description": step.description},
                )

            # Execute steps - executor now yields events during execution
            step_results = []
            async for item in self.executor.execute(
                decision=decision,
                state=state,
            ):
                # Check if it's a stream event (tuple with 3 elements) or StepResult
                if isinstance(item, tuple) and len(item) == _STREAM_CHUNK_LEN:
                    # It's a stream event - yield it upstream
                    yield ("stream_event", item)
                else:
                    # It's a StepResult
                    step_results.append(item)

            # Check for fatal errors and abort immediately
            fatal_errors = [r for r in step_results if r.error_type == "fatal"]
            if fatal_errors:
                logger.error(
                    "Fatal error detected, aborting loop: %s",
                    fatal_errors[0].error,
                )
                yield (
                    "fatal_error",
                    {
                        "error": fatal_errors[0].error,
                        "step_id": fatal_errors[0].step_id,
                    },
                )
                # Return early with failure status
                return

            # Update state with results
            for result in step_results:
                state.add_step_result(result)
                # Yield step result event (Level 3)
                yield (
                    "step_completed",
                    {
                        "step_id": result.step_id,
                        "success": result.success,
                        "output_preview": result.output[:100] if result.output else None,
                        "error": result.error or None,
                        "duration_ms": result.duration_ms,
                        "tool_call_count": result.tool_call_count,
                    },
                )

            # JUDGE Phase
            judgment = await self.judge_phase.judge(
                goal=goal,
                state=state,
            )

            state.previous_judgment = judgment
            state.iteration += 1
            state.total_duration_ms += int((time.perf_counter() - iteration_start) * 1000)

            # Yield judgment event (visible to user)
            yield (
                "judgment",
                {
                    "status": judgment.status,
                    "progress": judgment.goal_progress,
                    "confidence": judgment.confidence,
                    "reasoning": judgment.reasoning[:200] if judgment.reasoning else "",
                    "iteration": state.iteration,
                },
            )

            # Yield iteration completed event
            yield (
                "iteration_completed",
                {
                    "iteration": state.iteration,
                    "status": judgment.status,
                    "progress": judgment.goal_progress,
                    "reasoning": judgment.reasoning[:200] if judgment.reasoning else "",
                },
            )

            # Decision logic
            if judgment.is_done():
                logger.info(
                    "[✓] Goal achieved in %d iterations (%dms)",
                    state.iteration,
                    state.total_duration_ms,
                )
                yield ("completed", judgment)
                return

            if judgment.should_replan():
                logger.info(
                    "[↻] Replan needed at iteration %d (progress=%.0f%%)",
                    state.iteration,
                    judgment.goal_progress * 100,
                )
                # Next iteration will create new decision
                state.current_decision = None
                state.completed_step_ids.clear()
                continue

            # Check if there are actually ready steps to execute
            ready_steps = decision.get_ready_steps(state.completed_step_ids)
            if not ready_steps:
                # All steps completed but goal not achieved - force replan
                logger.info(
                    "[↻] No ready steps remaining (%d completed) - forcing replan",
                    len(state.completed_step_ids),
                )
                state.current_decision = None
                state.completed_step_ids.clear()
                continue

            logger.info(
                "[→] Continue with remaining %d steps at iteration %d",
                len(ready_steps),
                state.iteration,
            )
            # Reuse current decision, execute remaining steps
            state.current_decision = decision
            continue

        # Max iterations reached
        logger.warning(
            "[⚠] Max iterations (%d) reached (progress=%.0f%%)",
            state.max_iterations,
            state.previous_judgment.goal_progress * 100 if state.previous_judgment else 0,
        )

        result = state.previous_judgment or JudgeResult(
            status="replan",
            evidence_summary=state.evidence_summary,
            goal_progress=0.0,
            confidence=0.0,
            reasoning="Max iterations reached without completion",
        )
        yield ("completed", result)

    def _build_plan_context(self, state: LoopState) -> PlanContext:
        """Build planning context with available capabilities and completed steps.

        Args:
            state: Current loop state with step results

        Returns:
            PlanContext with tools, subagents, and completed steps for planner
        """
        # Get available tools from CoreAgent
        available_tools = []
        if hasattr(self.core_agent, "tools") and isinstance(self.core_agent.tools, dict):
            available_tools = list(self.core_agent.tools.keys())

        # Get enabled subagents from config
        available_subagents = [name for name, cfg in self.config.subagents.items() if cfg.enabled]

        # Convert LoopState.step_results to planner's StepResult format
        # This ensures planner knows what was already executed (fixes repetitive loop)
        completed_steps = [
            StepResult(
                step_id=r.step_id,
                output=r.output or r.error or "",
                success=r.success,
                duration_ms=r.duration_ms,
            )
            for r in state.step_results
        ]

        return PlanContext(
            available_capabilities=available_tools + available_subagents,
            recent_messages=[],  # Placeholder for conversation context
            completed_steps=completed_steps,  # Pass executed steps to avoid repetition
        )

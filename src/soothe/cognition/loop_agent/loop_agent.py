"""Main LoopAgent orchestration for Layer 2 (RFC-0008)."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from soothe.cognition.loop_agent.executor import Executor
from soothe.cognition.loop_agent.judge import JudgePhase
from soothe.cognition.loop_agent.planner import PlannerPhase
from soothe.cognition.loop_agent.schemas import JudgeResult, LoopState
from soothe.protocols.planner import PlanContext

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
        max_iterations: int = 8,
    ) -> AsyncGenerator[tuple[str, Any], None]:
        """Run loop with progress events (RFC-0020 compliant).

        Yields progress events during execution for display.

        Args:
            goal: Goal description to execute
            thread_id: Thread context for execution
            max_iterations: Maximum loop iterations (default: 8)

        Yields:
            Tuples of (event_type, event_data) for progress updates
        """
        state = LoopState(
            goal=goal,
            thread_id=thread_id,
            max_iterations=max_iterations,
        )

        logger.info(
            "Starting agentic loop for goal: %s (max_iterations: %d)",
            goal[:100],
            max_iterations,
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

            logger.info("=== Iteration %d ===", state.iteration)

            # PLAN Phase
            decision = await self.planner_phase.plan(
                goal=goal,
                state=state,
                context=self._build_plan_context(),
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
                    "Goal achieved after %d iterations (%dms total)",
                    state.iteration,
                    state.total_duration_ms,
                )
                yield ("completed", judgment)
                return

            if judgment.should_replan():
                logger.info(
                    "Replan needed after iteration %d (progress: %.0f%%)",
                    state.iteration,
                    judgment.goal_progress * 100,
                )
                # Next iteration will create new decision
                state.current_decision = None
                state.completed_step_ids.clear()
                continue

            logger.info(
                "Continue strategy after iteration %d (%d remaining steps)",
                state.iteration,
                len(decision.get_ready_steps(state.completed_step_ids)),
            )
            # Reuse current decision, execute remaining steps
            state.current_decision = decision
            continue

        # Max iterations reached
        logger.warning(
            "Max iterations (%d) reached without goal completion (progress: %.0f%%)",
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

    def _build_plan_context(self) -> PlanContext:
        """Build planning context with available capabilities.

        Returns:
            PlanContext with tools and subagents
        """
        # Get available tools from CoreAgent
        available_tools = []
        if hasattr(self.core_agent, "tools") and isinstance(self.core_agent.tools, dict):
            available_tools = list(self.core_agent.tools.keys())

        # Get enabled subagents from config
        available_subagents = [name for name, cfg in self.config.subagents.items() if cfg.enabled]

        return PlanContext(
            available_capabilities=available_tools + available_subagents,
            recent_messages=[],  # Placeholder for conversation context
        )

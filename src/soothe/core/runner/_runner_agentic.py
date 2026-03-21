"""Agentic loop mixin for SootheRunner (RFC-0008).

Implements observe → act → verify iterative refinement loop.
Replaces single-pass mode as default execution for non-chitchat queries.
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal

from ._runner_shared import StreamChunk, _custom

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)


class AgenticMixin:
    """Agentic loop implementation (observe → act → verify).

    Mixed into SootheRunner -- all self.* attributes are defined
    on the concrete class.
    """

    async def _run_agentic_loop(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
        max_iterations: int = 3,
        observation_strategy: str = "adaptive",
        verification_strictness: str = "moderate",
    ) -> AsyncGenerator[StreamChunk]:
        """Run agentic loop: observe → act → verify.

        This replaces the old single-pass mode for non-chitchat queries.

        Args:
            user_input: User's query text
            thread_id: Thread ID for persistence
            max_iterations: Maximum loop iterations (default: 3)
            observation_strategy: "minimal" | "comprehensive" | "adaptive"
            verification_strictness: "lenient" | "moderate" | "strict"
        """
        from soothe.cognition import UnifiedClassification
        from soothe.core.event_catalog import (
            AgenticIterationCompletedEvent,
            AgenticLoopCompletedEvent,
            AgenticLoopStartedEvent,
            AgenticPlanningStrategyDeterminedEvent,
        )

        from ._types import AgenticIterationRecord, RunnerState

        state = RunnerState()
        state.thread_id = thread_id or self._current_thread_id or ""
        self._current_thread_id = state.thread_id or None

        # Two-tier classification for proper routing
        if self._unified_classifier:
            routing = await self._unified_classifier.classify_routing(user_input)
            complexity = routing.task_complexity
            logger.info(
                "Agentic mode: tier-1 routing task_complexity=%s - %s",
                complexity,
                user_input[:50],
            )

            # Fast path for chitchat - skip agentic loop
            if complexity == "chitchat":
                async for chunk in self._run_chitchat(user_input, classification=routing):
                    yield chunk
                return

            enrichment = await self._unified_classifier.classify_enrichment(user_input, complexity)
            state.unified_classification = UnifiedClassification.from_tiers(routing, enrichment)
            # Cache routing for reuse in observe phase
            state.cached_routing = routing
        else:
            state.unified_classification = None
            state.cached_routing = None
            complexity = "medium"

        # Emit loop started event
        yield _custom(
            AgenticLoopStartedEvent(
                thread_id=state.thread_id,
                query=user_input[:100],
                max_iterations=max_iterations,
                observation_strategy=observation_strategy,
                verification_strictness=verification_strictness,
            ).to_dict()
        )

        # Run pre-stream independent work (thread, policy, memory, context)
        async for chunk in self._pre_stream_independent(user_input, state, complexity=complexity):
            yield chunk

        iteration = 0
        should_continue = True
        cumulative_context = []
        iteration_records: list[AgenticIterationRecord] = []

        # Determine initial planning strategy based on complexity
        planning_strategy = self._determine_planning_strategy(complexity, user_input, state)
        logger.info("Planning strategy: %s for complexity=%s", planning_strategy, complexity)

        yield _custom(
            AgenticPlanningStrategyDeterminedEvent(
                iteration=iteration,
                complexity=complexity,
                strategy=planning_strategy,
                reason="initial_classification",
            ).to_dict()
        )

        while iteration < max_iterations and should_continue:
            iteration_start = perf_counter()

            # Observe phase (skip I/O on first iteration as pre-stream already did it)
            async for chunk in self._agentic_observe(
                user_input, state, cumulative_context, observation_strategy, iteration, skip_io=(iteration == 0)
            ):
                yield chunk

            # Act phase (with adaptive planning)
            async for chunk in self._agentic_act(user_input, state, cumulative_context, iteration, planning_strategy):
                yield chunk

            # Verify phase
            verification_result = None
            async for chunk in self._agentic_verify(user_input, state, verification_strictness, iteration):
                if isinstance(chunk, dict) and chunk.get("verification_result"):
                    verification_result = chunk["verification_result"]
                yield chunk

            should_continue = verification_result.get("should_continue", False) if verification_result else False

            iteration_duration = int((perf_counter() - iteration_start) * 1000)
            response_text = "".join(state.full_response)

            # Create iteration record
            record = AgenticIterationRecord(
                iteration=iteration,
                planning_strategy=planning_strategy,
                observation_summary=str(cumulative_context[-1])[:200] if cumulative_context else "",
                actions_taken=response_text[:200],
                verification_result=str(verification_result)[:200] if verification_result else "",
                should_continue=should_continue,
                duration_ms=iteration_duration,
            )
            iteration_records.append(record)
            state.iteration_records = iteration_records

            iteration += 1

            # Emit iteration completed
            yield _custom(
                AgenticIterationCompletedEvent(
                    iteration=iteration,
                    planning_strategy=planning_strategy,
                    outcome="continue" if should_continue else "complete",
                    duration_ms=iteration_duration,
                ).to_dict()
            )

            # Adapt planning strategy based on iteration results
            if should_continue and iteration < max_iterations:
                new_strategy = self._adapt_planning_strategy(planning_strategy, state, verification_result)
                if new_strategy != planning_strategy:
                    planning_strategy = new_strategy
                    yield _custom(
                        AgenticPlanningStrategyDeterminedEvent(
                            iteration=iteration,
                            complexity=complexity,
                            strategy=planning_strategy,
                            reason="adaptive_escalation",
                        ).to_dict()
                    )

        # Post-stream work
        async for chunk in self._post_stream(user_input, state):
            yield chunk

        # Emit loop completed
        yield _custom(
            AgenticLoopCompletedEvent(
                thread_id=state.thread_id,
                total_iterations=iteration,
                outcome="completed",
            ).to_dict()
        )

    def _determine_planning_strategy(
        self,
        complexity: str,
        user_input: str,
        state: Any,
    ) -> Literal["none", "lightweight", "comprehensive"]:
        """Determine planning strategy based on complexity and user intent.

        Args:
            complexity: Task complexity from classification
            user_input: User's query
            state: Runner state

        Returns:
            Planning strategy: "none", "lightweight", or "comprehensive"
        """
        # Check for explicit planning hints
        force_keywords = self._config.agentic.planning.force_keywords

        user_lower = user_input.lower()

        if any(kw in user_lower for kw in force_keywords):
            return "comprehensive"

        # Adaptive based on complexity
        if complexity == "simple":
            return "none"
        if complexity == "medium":
            return "lightweight"
        # complex
        return "comprehensive"

    def _adapt_planning_strategy(
        self,
        current_strategy: str,
        state: Any,
        verification_result: dict,
    ) -> str:
        """Adapt planning strategy based on iteration results.

        If verification shows the problem is more complex than initially thought,
        escalate planning strategy.
        """
        if not self._config.agentic.planning.adaptive_escalation:
            return current_strategy

        feedback = verification_result.get("feedback", "")

        # Escalate planning if multiple issues found
        if "multiple issues" in feedback.lower() or "complex" in feedback.lower():
            if current_strategy == "none":
                return "lightweight"
            if current_strategy == "lightweight":
                return "comprehensive"

        return current_strategy

    async def _agentic_observe(
        self,
        user_input: str,
        state: Any,
        cumulative_context: list,
        observation_strategy: str,
        iteration: int,
        skip_io: bool = False,
    ) -> AsyncGenerator[StreamChunk]:
        """Observe phase: gather context and classify.

        Reuses existing protocol infrastructure:
        - Context projection
        - Memory recall
        - Policy check
        - Classification

        Strategy behavior:
        - minimal: Skip context/memory, < 100ms
        - comprehensive: Full operations, 2-3s
        - adaptive: Minimal for iteration 0, comprehensive later

        Args:
            user_input: User query
            state: Runner state
            cumulative_context: List of observation dicts
            observation_strategy: "minimal" | "comprehensive" | "adaptive"
            iteration: Current iteration number
            skip_io: Skip I/O operations (already done in pre-stream)
        """
        from soothe.core.event_catalog import (
            AgenticObservationCompletedEvent,
            AgenticObservationStartedEvent,
        )

        yield _custom(
            AgenticObservationStartedEvent(
                iteration=iteration,
                strategy=observation_strategy,
            ).to_dict()
        )

        observations = {}

        # Determine operations based on strategy
        if observation_strategy == "minimal":
            should_gather = False
        elif observation_strategy == "comprehensive":
            should_gather = True
        else:  # adaptive
            should_gather = iteration > 0

        # Context (conditional, skip if already done in pre-stream)
        if not skip_io and should_gather and self._context:
            try:
                projection = await self._context.project(user_input, token_budget=4000)
                observations["context"] = projection
                state.context_projection = projection
            except Exception:
                logger.debug("Context projection failed", exc_info=True)

        # Memory (conditional, skip if already done in pre-stream)
        if not skip_io and should_gather and self._memory:
            try:
                memories = await self._memory.recall(user_input, limit=5)
                observations["memories"] = memories
                state.recalled_memories = memories
            except Exception:
                logger.debug("Memory recall failed", exc_info=True)

        # Classification: use cached result if available
        if hasattr(state, "cached_routing") and state.cached_routing:
            observations["classification"] = state.cached_routing
        elif self._unified_classifier:
            try:
                routing = await self._unified_classifier.classify_routing(user_input)
                observations["classification"] = routing
            except Exception:
                logger.debug("Classification failed", exc_info=True)

        cumulative_context.append(observations)

        # Determine planning strategy for this iteration
        complexity = (
            observations.get("classification", {}).task_complexity if observations.get("classification") else "medium"
        )

        yield _custom(
            AgenticObservationCompletedEvent(
                iteration=iteration,
                context_entries=len(observations.get("context", [])),
                memories_recalled=len(observations.get("memories", [])),
                planning_strategy=self._determine_planning_strategy(complexity, user_input, state),
            ).to_dict()
        )

    async def _agentic_act(
        self,
        user_input: str,
        state: Any,
        cumulative_context: list,
        iteration: int,
        planning_strategy: str,
    ) -> AsyncGenerator[StreamChunk]:
        """Act phase: execute actions with adaptive planning.

        Planning is determined by:
        1. Problem complexity (from classification)
        2. User intent (explicit hints)
        3. Observation results (context suggests needs)

        Args:
            user_input: User's query
            state: Runner state
            cumulative_context: Context from previous observations
            iteration: Current iteration number
            planning_strategy: "none", "lightweight", or "comprehensive"
        """
        # Create plan if strategy requires it
        if planning_strategy != "none" and self._planner:
            try:
                from soothe.core.event_catalog import PlanCreatedEvent
                from soothe.protocols.planner import PlanContext

                capabilities = [name for name, cfg in self._config.subagents.items() if cfg.enabled]

                context = PlanContext(
                    recent_messages=[user_input],
                    available_capabilities=capabilities,
                    completed_steps=[{"iteration": i, "context": ctx} for i, ctx in enumerate(cumulative_context)],
                    unified_classification=state.unified_classification,
                )

                # Configure planning depth based on strategy
                if planning_strategy == "lightweight":
                    # Limit steps for lightweight planning
                    max_steps = self._config.agentic.planning.medium_max_steps
                else:  # comprehensive
                    max_steps = None  # No limit

                plan = await self._planner.create_plan(
                    user_input,
                    context,
                    max_steps=max_steps,
                )

                state.plan = plan
                self._current_plan = plan

                # Emit plan created event
                yield _custom(
                    PlanCreatedEvent(
                        goal=plan.goal,
                        steps=[{"id": s.id, "description": s.description} for s in plan.steps],
                    ).to_dict()
                )

                logger.info(
                    "Created %s plan with %d steps for iteration %d",
                    planning_strategy,
                    len(plan.steps),
                    iteration,
                )
            except Exception:
                logger.debug("Plan creation failed", exc_info=True)

        # Execute plan or direct action
        if state.plan and len(state.plan.steps) > 1:
            # Multi-step: use step loop
            async for chunk in self._run_step_loop(user_input, state, state.plan, goal_id=state.thread_id):
                yield chunk
        else:
            # Single-step or no plan: use stream phase
            async with self._concurrency.acquire_llm_call():
                async for chunk in self._stream_phase(user_input, state):
                    yield chunk

    async def _agentic_verify(
        self,
        user_input: str,
        state: Any,
        verification_strictness: str,
        iteration: int,
    ) -> AsyncGenerator[StreamChunk]:
        """Verify phase: evaluate results and decide continuation.

        Uses planner protocol for reflection and decision-making.
        """
        from soothe.core.event_catalog import (
            AgenticVerificationCompletedEvent,
            AgenticVerificationStartedEvent,
            PlanReflectedEvent,
        )

        yield _custom(
            AgenticVerificationStartedEvent(
                iteration=iteration,
                strictness=verification_strictness,
            ).to_dict()
        )

        verification_result = None

        if self._planner and state.plan:
            try:
                from soothe.protocols.planner import StepResult

                step_results = [
                    StepResult(
                        step_id=s.id,
                        output=s.result or "",
                        success=s.status == "completed",
                    )
                    for s in state.plan.steps
                    if s.status in ("completed", "failed")
                ]

                if step_results:
                    reflection = await self._planner.reflect(state.plan, step_results)

                    # Emit reflection event
                    yield _custom(
                        PlanReflectedEvent(
                            should_revise=reflection.should_revise,
                            assessment=reflection.assessment[:200],
                        ).to_dict()
                    )

                    # Determine if should continue based on verification
                    response_text = "".join(state.full_response)
                    should_continue = self._evaluate_continuation(
                        reflection,
                        response_text,
                        verification_strictness,
                    )

                    verification_result = {
                        "should_continue": should_continue,
                        "assessment": reflection.assessment,
                        "feedback": reflection.feedback,
                    }

                    # Revise plan if continuing
                    if should_continue and reflection.should_revise:
                        revised = await self._planner.revise_plan(state.plan, reflection.feedback)
                        self._current_plan = revised
                        state.plan = revised
            except Exception:
                logger.debug("Verification failed", exc_info=True)

        yield _custom(
            AgenticVerificationCompletedEvent(
                iteration=iteration,
                should_continue=verification_result.get("should_continue", False) if verification_result else False,
                assessment=verification_result.get("assessment", "")[:100] if verification_result else "",
            ).to_dict()
        )

        # Yield verification result for caller
        if verification_result:
            yield {"verification_result": verification_result}

    def _evaluate_continuation(
        self,
        reflection: Any,
        response_text: str,
        verification_strictness: str,
    ) -> bool:
        """Evaluate whether to continue the agentic loop.

        Args:
            reflection: Planner reflection result
            response_text: Accumulated response text
            verification_strictness: "lenient" | "moderate" | "strict"

        Returns:
            True if should continue, False otherwise
        """
        response_lower = response_text.lower()

        # Check for task completion signals (all levels)
        completion_signals = self._config.agentic.early_termination.completion_signals
        if any(signal in response_lower for signal in completion_signals):
            return False

        # Continuation indicators
        continuation_indicators = [
            "need to verify",
            "should test",
            "missing",
            "incomplete",
            "not yet",
            "still need",
            "todo:",
            "remaining",
        ]

        if verification_strictness == "lenient":
            # Continue with ANY indication of incomplete work
            return reflection.should_revise or any(sig in response_lower for sig in continuation_indicators)

        if verification_strictness == "moderate":
            # Continue with clear need + quality check
            return reflection.should_revise and (
                any(sig in response_lower for sig in continuation_indicators) or len(response_text) < 500
            )

        # strict: Continue only with strong evidence of incompleteness
        strong_evidence = ["need to verify", "must test", "critically missing", "incomplete -", "failed to", "error:"]
        return reflection.should_revise and any(sig in response_lower for sig in strong_evidence)

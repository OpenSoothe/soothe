# Implementation Guide: Agentic Loop Execution Architecture

**Guide**: IG-045
**Title**: Agentic Loop Implementation Guide
**Created**: 2026-03-22
**Related RFCs**: RFC-201, RFC-200, RFC-202, RFC-102, RFC-401

## Overview

This implementation guide covers the replacement of single-pass execution with the Agentic Loop architecture defined in RFC-201. The Agentic Loop implements the **Observe → Act → Verify** pattern as the default execution mode for non-chitchat queries, with adaptive planning strategies and iterative refinement.

## Prerequisites

- [x] RFC-201 accepted (Agentic Loop Execution Architecture)
- [x] RFC-102 implemented (Unified Classification)
- [x] RFC-202 implemented (DAG-Based Execution)
- [x] RFC-401 implemented (Progress Event Protocol)
- [x] Development environment setup
- [x] Dependencies installed

## Implementation Plan

### Phase 1: Core Agentic Loop Implementation

**Goal**: Implement the three-phase agentic loop (observe, act, verify) to replace single-pass execution.

**Tasks**:
- [ ] Create `/src/soothe/core/_runner_agentic.py` with AgenticMixin
- [ ] Implement `_run_agentic_loop()` main orchestration method
- [ ] Implement `_agentic_observe()` phase
- [ ] Implement `_agentic_act()` phase with adaptive planning
- [ ] Implement `_agentic_verify()` phase
- [ ] Implement planning strategy determination logic
- [ ] Implement iteration control and early termination

### Phase 2: Event System Integration

**Goal**: Add agentic loop events to the event catalog and TUI handlers.

**Tasks**:
- [ ] Add 10 new event models to `/src/soothe/core/event_catalog.py`
- [ ] Register events in event registry with RFC-401 naming
- [ ] Add TUI event handlers in `/src/soothe/cli/tui/event_processors.py`
- [ ] Test event emission and display

### Phase 3: Configuration Schema

**Goal**: Add agentic loop configuration options.

**Tasks**:
- [ ] Add `AgenticLoopConfig` to `/src/soothe/config/models.py`
- [ ] Add `PlanningConfig` and `EarlyTerminationConfig`
- [ ] Update configuration validation
- [ ] Document configuration options

### Phase 4: Runner Integration

**Goal**: Replace single-pass with agentic loop as default execution.

**Tasks**:
- [ ] Import AgenticMixin in `/src/soothe/core/runner.py`
- [ ] Remove `_run_single_pass()` method
- [ ] Update `astream()` to route to agentic loop by default
- [ ] Preserve autonomous mode routing (RFC-200)
- [ ] Update runner documentation

### Phase 5: Testing & Verification

**Goal**: Ensure agentic loop works correctly across all complexity levels.

**Tasks**:
- [ ] Create unit tests for agentic loop phases
- [ ] Create integration tests with real LLM calls
- [ ] Test chitchat fast path
- [ ] Test adaptive planning strategies
- [ ] Test iteration control and early termination
- [ ] Verify performance targets met
- [ ] Update existing tests that relied on single-pass

## File Structure

```
src/soothe/
├── core/
│   ├── _runner_agentic.py          # NEW: Agentic loop implementation
│   ├── runner.py                   # MODIFIED: Remove single-pass, add agentic routing
│   └── event_catalog.py            # MODIFIED: Add agentic events
├── config/
│   └── models.py                   # MODIFIED: Add AgenticLoopConfig
└── cli/tui/
    └── event_processors.py         # MODIFIED: Add agentic event handlers

tests/
├── unit/
│   └── test_agentic_loop.py        # NEW: Unit tests
└── integration_tests/
    └── test_agentic_integration.py # NEW: Integration tests

docs/specs/
└── RFC-201-agentic-goal-execution.md   # UPDATED: Already updated
```

## Implementation Details

### Module 1: Agentic Loop Core

**File**: `src/soothe/core/_runner_agentic.py`

```python
"""Agentic loop mixin for SootheRunner.

Implements observe → act → verify iterative refinement loop.
Replaces single-pass mode as default execution for non-chitchat queries.
"""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING, Any, Literal
from soothe.core._runner_shared import StreamChunk, _custom
from soothe.core.event_catalog import (
    AgenticIterationCompletedEvent,
    AgenticIterationStartedEvent,
    AgenticLoopCompletedEvent,
    AgenticLoopStartedEvent,
    AgenticObservationCompletedEvent,
    AgenticObservationStartedEvent,
    AgenticVerificationCompletedEvent,
    AgenticVerificationStartedEvent,
    AgenticPlanningStrategyDeterminedEvent,
)

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
        from soothe.core.runner import RunnerState
        from soothe.cognition import UnifiedClassification

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
                async for chunk in self._run_chitchat(
                    user_input, classification=routing
                ):
                    yield chunk
                return

            enrichment = await self._unified_classifier.classify_enrichment(
                user_input, complexity
            )
            state.unified_classification = UnifiedClassification.from_tiers(
                routing, enrichment
            )
        else:
            state.unified_classification = None
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
        async for chunk in self._pre_stream_independent(
            user_input, state, complexity=complexity
        ):
            yield chunk

        iteration = 0
        should_continue = True
        cumulative_context = []

        # Determine initial planning strategy based on complexity
        planning_strategy = self._determine_planning_strategy(
            complexity, user_input, state
        )
        logger.info(
            "Planning strategy: %s for complexity=%s", planning_strategy, complexity
        )

        yield _custom(
            AgenticPlanningStrategyDeterminedEvent(
                iteration=iteration,
                complexity=complexity,
                strategy=planning_strategy,
                reason="initial_classification",
            ).to_dict()
        )

        while iteration < max_iterations and should_continue:
            # Observe phase
            async for chunk in self._agentic_observe(
                user_input, state, cumulative_context, observation_strategy, iteration
            ):
                yield chunk

            # Act phase (with adaptive planning)
            async for chunk in self._agentic_act(
                user_input, state, cumulative_context, iteration, planning_strategy
            ):
                yield chunk

            # Verify phase
            verification_result = None
            async for chunk in self._agentic_verify(
                user_input, state, verification_strictness, iteration
            ):
                if isinstance(chunk, dict) and chunk.get("verification_result"):
                    verification_result = chunk["verification_result"]
                yield chunk

            should_continue = (
                verification_result.get("should_continue", False)
                if verification_result
                else False
            )

            iteration += 1

            # Emit iteration completed
            yield _custom(
                AgenticIterationCompletedEvent(
                    iteration=iteration,
                    planning_strategy=planning_strategy,
                    outcome="continue" if should_continue else "complete",
                    duration_ms=0,  # TODO: track actual duration
                ).to_dict()
            )

            # Adapt planning strategy based on iteration results
            if should_continue and iteration < max_iterations:
                new_strategy = self._adapt_planning_strategy(
                    planning_strategy, state, verification_result
                )
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
        elif complexity == "medium":
            return "lightweight"
        else:  # complex
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
            elif current_strategy == "lightweight":
                return "comprehensive"

        return current_strategy

    async def _agentic_observe(
        self,
        user_input: str,
        state: Any,
        cumulative_context: list,
        observation_strategy: str,
        iteration: int,
    ) -> AsyncGenerator[StreamChunk]:
        """Observe phase: gather context and classify.

        Reuses existing protocol infrastructure:
        - Context projection
        - Memory recall
        - Policy check
        - Classification
        """
        yield _custom(
            AgenticObservationStartedEvent(
                iteration=iteration,
                strategy=observation_strategy,
            ).to_dict()
        )

        observations = {}

        # Gather context (parallel)
        if self._context:
            try:
                projection = await self._context.project(user_input, token_budget=4000)
                observations["context"] = projection
                state.context_projection = projection
            except Exception:
                logger.debug("Context projection failed", exc_info=True)

        # Recall memories
        if self._memory:
            try:
                memories = await self._memory.recall(user_input, limit=5)
                observations["memories"] = memories
                state.recalled_memories = memories
            except Exception:
                logger.debug("Memory recall failed", exc_info=True)

        # Classify if available
        if self._unified_classifier:
            try:
                routing = await self._unified_classifier.classify_routing(user_input)
                observations["classification"] = routing
            except Exception:
                logger.debug("Classification failed", exc_info=True)

        cumulative_context.append(observations)

        # Determine planning strategy for this iteration
        complexity = (
            observations.get("classification", {}).task_complexity
            if observations.get("classification")
            else "medium"
        )

        yield _custom(
            AgenticObservationCompletedEvent(
                iteration=iteration,
                context_entries=len(observations.get("context", [])),
                memories_recalled=len(observations.get("memories", [])),
                planning_strategy=self._determine_planning_strategy(
                    complexity, user_input, state
                ),
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
                from soothe.protocols.planner import PlanContext

                capabilities = [
                    name for name, cfg in self._config.subagents.items() if cfg.enabled
                ]

                context = PlanContext(
                    recent_messages=[user_input],
                    available_capabilities=capabilities,
                    completed_steps=[
                        {"iteration": i, "context": ctx}
                        for i, ctx in enumerate(cumulative_context)
                    ],
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
                from soothe.core.event_catalog import PlanCreatedEvent

                yield _custom(
                    PlanCreatedEvent(
                        goal=plan.goal,
                        steps=[
                            {"id": s.id, "description": s.description}
                            for s in plan.steps
                        ],
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
            async for chunk in self._run_step_loop(
                user_input, state, state.plan, goal_id=state.thread_id
            ):
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
                    from soothe.core.event_catalog import PlanReflectedEvent

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
                        revised = await self._planner.revise_plan(
                            state.plan, reflection.feedback
                        )
                        self._current_plan = revised
                        state.plan = revised
            except Exception:
                logger.debug("Verification failed", exc_info=True)

        yield _custom(
            AgenticVerificationCompletedEvent(
                iteration=iteration,
                should_continue=verification_result.get("should_continue", False)
                if verification_result
                else False,
                assessment=verification_result.get("assessment", "")[:100]
                if verification_result
                else "",
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
        # If planner explicitly says revise, continue
        if reflection.should_revise:
            return True

        # Check for task completion signals
        completion_signals = self._config.agentic.early_termination.completion_signals

        response_lower = response_text.lower()
        if any(signal in response_lower for signal in completion_signals):
            return False

        # Strictness-based decision
        if verification_strictness == "lenient":
            # Continue if any indication of incomplete work
            return reflection.should_revise
        elif verification_strictness == "moderate":
            # Balance between continuing and stopping
            return reflection.should_revise and len(response_text) < 500
        else:  # strict
            # Only continue if strong indication
            return False
```

### Module 2: Event Catalog

**File**: `src/soothe/core/event_catalog.py`

Add these event models after existing events:

```python
# ---------------------------------------------------------------------------
# Agentic Loop Events (RFC-201)
# ---------------------------------------------------------------------------


class AgenticLoopStartedEvent(BaseModel):
    """Emitted when agentic loop starts."""

    thread_id: str
    query: str
    max_iterations: int
    observation_strategy: str
    verification_strictness: str


class AgenticLoopCompletedEvent(BaseModel):
    """Emitted when agentic loop completes."""

    thread_id: str
    total_iterations: int
    outcome: str  # "completed" | "failed" | "escalated"


class AgenticIterationStartedEvent(BaseModel):
    """Emitted at the start of each agentic iteration."""

    iteration: int
    planning_strategy: str


class AgenticIterationCompletedEvent(BaseModel):
    """Emitted at the end of each agentic iteration."""

    iteration: int
    planning_strategy: str
    outcome: str
    duration_ms: int


class AgenticObservationStartedEvent(BaseModel):
    """Emitted when observation phase starts."""

    iteration: int
    strategy: str


class AgenticObservationCompletedEvent(BaseModel):
    """Emitted when observation phase completes."""

    iteration: int
    context_entries: int
    memories_recalled: int
    planning_strategy: str


class AgenticVerificationStartedEvent(BaseModel):
    """Emitted when verification phase starts."""

    iteration: int
    strictness: str


class AgenticVerificationCompletedEvent(BaseModel):
    """Emitted when verification phase completes."""

    iteration: int
    should_continue: bool
    assessment: str


class AgenticPlanningStrategyDeterminedEvent(BaseModel):
    """Emitted when planning strategy is determined."""

    iteration: int
    complexity: str
    strategy: str
    reason: str
```

And register them in the event registry:

```python
# Register agentic events
REGISTRY.register(
    "soothe.agentic.loop_started",
    EventMeta(verbosity="info", domain="agentic", description="Agentic loop started"),
)
REGISTRY.register(
    "soothe.agentic.loop_completed",
    EventMeta(verbosity="info", domain="agentic", description="Agentic loop completed"),
)
REGISTRY.register(
    "soothe.agentic.iteration_started",
    EventMeta(verbosity="info", domain="agentic", description="Iteration started"),
)
REGISTRY.register(
    "soothe.agentic.iteration_completed",
    EventMeta(verbosity="info", domain="agentic", description="Iteration completed"),
)
REGISTRY.register(
    "soothe.agentic.observation_started",
    EventMeta(verbosity="debug", domain="agentic", description="Observation started"),
)
REGISTRY.register(
    "soothe.agentic.observation_completed",
    EventMeta(verbosity="debug", domain="agentic", description="Observation completed"),
)
REGISTRY.register(
    "soothe.agentic.verification_started",
    EventMeta(verbosity="debug", domain="agentic", description="Verification started"),
)
REGISTRY.register(
    "soothe.agentic.verification_completed",
    EventMeta(verbosity="debug", domain="agentic", description="Verification completed"),
)
REGISTRY.register(
    "soothe.agentic.planning_strategy_determined",
    EventMeta(verbosity="info", domain="agentic", description="Planning strategy determined"),
)
```

### Module 3: Configuration

**File**: `src/soothe/config/models.py`

Add after existing config classes:

```python
class PlanningConfig(BaseModel):
    """Adaptive planning configuration."""

    simple_max_tokens: int = Field(
        default=50,
        description="Skip planning for queries < N tokens",
    )
    medium_max_steps: int = Field(
        default=3,
        description="Lightweight planning step limit",
    )
    complexity_threshold: int = Field(
        default=160,
        description="Tokens threshold for complex planning",
    )

    force_keywords: list[str] = Field(
        default=["plan for", "create a plan", "steps to"],
        description="Keywords that force comprehensive planning",
    )

    adaptive_escalation: bool = Field(
        default=True,
        description="Escalate planning if iteration shows complexity",
    )


class EarlyTerminationConfig(BaseModel):
    """Early termination configuration."""

    enabled: bool = Field(
        default=True,
        description="Enable early termination based on completion signals",
    )
    completion_signals: list[str] = Field(
        default=["task complete", "done", "finished successfully"],
        description="Signals that indicate task completion",
    )
    error_threshold: int = Field(
        default=3,
        description="Max errors before stopping iteration",
    )


class AgenticLoopConfig(BaseModel):
    """Configuration for agentic loop execution mode."""

    enabled: bool = Field(
        default=True,
        description="Enable agentic loop mode",
    )

    max_iterations: int = Field(
        default=3,
        description="Maximum agentic loop iterations",
        ge=1,
        le=10,
    )

    observation_strategy: Literal["minimal", "comprehensive", "adaptive"] = Field(
        default="adaptive",
        description="Strategy for observation phase",
    )

    verification_strictness: Literal["lenient", "moderate", "strict"] = Field(
        default="moderate",
        description="Strictness level for verification phase",
    )

    planning: PlanningConfig = Field(
        default_factory=PlanningConfig,
        description="Planning configuration",
    )

    early_termination: EarlyTerminationConfig = Field(
        default_factory=EarlyTerminationConfig,
        description="Early termination configuration",
    )


class SootheConfig(BaseModel):
    # ... existing fields ...

    agentic: AgenticLoopConfig = Field(
        default_factory=AgenticLoopConfig,
        description="Agentic loop configuration",
    )
```

### Module 4: Runner Integration

**File**: `src/soothe/core/runner.py`

```python
from soothe.core._runner_agentic import AgenticMixin

class SootheRunner(
    CheckpointMixin,
    StepLoopMixin,
    AutonomousMixin,  # RFC-200
    AgenticMixin,      # RFC-201
    PhasesMixin,
):
    """Protocol-orchestrated agent runner."""

    async def astream(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
        autonomous: bool = False,
        max_iterations: int | None = None,
        subagent: str | None = None,
    ) -> AsyncGenerator[StreamChunk]:
        """Stream agent execution with protocol orchestration.

        Args:
            user_input: The user's query text.
            thread_id: Thread ID for persistence. Generated if not provided.
            autonomous: Enable autonomous iteration loop (RFC-200).
            max_iterations: Override max iterations.
            subagent: Optional subagent name to route the query to directly.
        """
        # Priority: autonomous > default (agentic)
        if autonomous and self._goal_engine:
            async for chunk in self._run_autonomous(
                user_input,
                thread_id=thread_id,
                max_iterations=max_iterations or self._config.autonomous.max_iterations,
            ):
                yield chunk
            return

        # Default: agentic loop
        async for chunk in self._run_agentic_loop(
            user_input,
            thread_id=thread_id,
            max_iterations=max_iterations or self._config.agentic.max_iterations,
            observation_strategy=self._config.agentic.observation_strategy,
            verification_strictness=self._config.agentic.verification_strictness,
        ):
            yield chunk
```

**Remove**:
- Delete the `_run_single_pass()` method entirely
- Remove any direct calls to `_run_single_pass()`

### Module 5: TUI Event Handlers

**File**: `src/soothe/cli/tui/event_processors.py`

Add this handler function:

```python
def _handle_agentic_event(data: dict, state: TuiState, event_type: str) -> None:
    """Handle agentic loop events."""
    if event_type == "soothe.agentic.loop_started":
        state.activity_lines.append(
            Text.from_markup(
                "[bold cyan]🔄 Agentic loop started[/] "
                f"(max {data.get('max_iterations', 3)} iterations)"
            )
        )
    elif event_type == "soothe.agentic.iteration_started":
        iteration = data.get('iteration', 0)
        strategy = data.get('planning_strategy', 'unknown')
        state.activity_lines.append(
            Text.from_markup(
                f"[dim]  Iteration {iteration + 1} ({strategy} planning)[/]"
            )
        )
    elif event_type == "soothe.agentic.observation_completed":
        context = data.get('context_entries', 0)
        memories = data.get('memories_recalled', 0)
        strategy = data.get('planning_strategy', 'unknown')
        state.activity_lines.append(
            Text.from_markup(
                f"[dim]    ↳ Observed: {context} context, {memories} memories → {strategy}[/]"
            )
        )
    elif event_type == "soothe.agentic.verification_completed":
        should_continue = data.get('should_continue', False)
        outcome = "→ continuing" if should_continue else "✓ complete"
        state.activity_lines.append(
            Text.from_markup(
                f"[dim]    ↳ Verified: {outcome}[/]"
            )
        )
    elif event_type == "soothe.agentic.loop_completed":
        iterations = data.get('total_iterations', 0)
        outcome = data.get('outcome', 'unknown')
        state.activity_lines.append(
            Text.from_markup(
                f"[bold green]✓ Agentic loop completed[/] "
                f"({iterations} iterations, {outcome})"
            )
        )
```

Update `process_daemon_event()` to route agentic events:

```python
def process_daemon_event(msg, state, verbosity):
    # ... existing code ...

    event_type = data.get("type", "")

    # Route agentic events
    if event_type.startswith("soothe.agentic."):
        _handle_agentic_event(data, state, event_type)
    # ... rest of handlers ...
```

## Testing Strategy

### Unit Tests

**File**: `tests/unit/test_agentic_loop.py`

```python
import pytest
from soothe.core.runner import SootheRunner
from soothe.config import SootheConfig


@pytest.mark.asyncio
async def test_agentic_loop_basic():
    """Test basic agentic loop execution."""
    config = SootheConfig()
    runner = SootheRunner(config)

    chunks = []
    async for chunk in runner.astream(
        "Debug the failing tests",
        max_iterations=2,
    ):
        chunks.append(chunk)

    # Verify loop events were emitted
    event_types = [c[2].get("type") for c in chunks if len(c) == 3]
    assert "soothe.agentic.loop_started" in event_types
    assert "soothe.agentic.iteration_started" in event_types
    assert "soothe.agentic.observation_completed" in event_types
    assert "soothe.agentic.verification_completed" in event_types
    assert "soothe.agentic.loop_completed" in event_types


@pytest.mark.asyncio
async def test_agentic_chitchat_fast_path():
    """Test chitchat bypasses agentic loop."""
    config = SootheConfig()
    runner = SootheRunner(config)

    chunks = []
    async for chunk in runner.astream("Hello, how are you?"):
        chunks.append(chunk)

    # Verify no agentic loop events
    event_types = [c[2].get("type") for c in chunks if len(c) == 3]
    assert "soothe.agentic.loop_started" not in event_types
    assert "soothe.chitchat.response" in event_types


@pytest.mark.asyncio
async def test_planning_strategy_none():
    """Test planning strategy 'none' for simple queries."""
    runner = SootheRunner()

    strategy = runner._determine_planning_strategy(
        "simple",
        "just read the file",
        None,
    )

    assert strategy == "none"


@pytest.mark.asyncio
async def test_planning_strategy_lightweight():
    """Test planning strategy 'lightweight' for medium queries."""
    runner = SootheRunner()

    strategy = runner._determine_planning_strategy(
        "medium",
        "debug the error",
        None,
    )

    assert strategy == "lightweight"


@pytest.mark.asyncio
async def test_planning_strategy_comprehensive():
    """Test planning strategy 'comprehensive' for complex queries."""
    runner = SootheRunner()

    strategy = runner._determine_planning_strategy(
        "complex",
        "refactor the auth system",
        None,
    )

    assert strategy == "comprehensive"


@pytest.mark.asyncio
async def test_early_termination():
    """Test early termination when task complete signal detected."""
    runner = SootheRunner()

    from soothe.protocols.planner import ReflectionResult

    reflection = ReflectionResult(
        should_revise=False,
        assessment="Task completed successfully",
        feedback="",
    )

    should_continue = runner._evaluate_continuation(
        reflection,
        "The task is now complete and finished successfully",
        "moderate",
    )

    assert should_continue is False


@pytest.mark.asyncio
async def test_iteration_limit():
    """Test iteration limit is respected."""
    config = SootheConfig()
    config.agentic.max_iterations = 2
    runner = SootheRunner(config)

    chunks = []
    async for chunk in runner.astream("Complex task"):
        chunks.append(chunk)

    # Count iterations
    iteration_events = [
        c for c in chunks
        if len(c) == 3 and c[2].get("type") == "soothe.agentic.iteration_completed"
    ]

    assert len(iteration_events) <= 2
```

### Integration Tests

**File**: `tests/integration_tests/test_agentic_integration.py`

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_agentic_loop_with_real_llm():
    """Test agentic loop with real LLM calls."""
    runner = SootheRunner()

    chunks = []
    async for chunk in runner.astream(
        "Debug why the tests are failing and fix them",
        max_iterations=3,
    ):
        chunks.append(chunk)

    # Verify actual problem-solving occurred
    # Check that multiple iterations happened
    iteration_events = [
        c for c in chunks
        if len(c) == 3 and c[2].get("type") == "soothe.agentic.iteration_completed"
    ]

    assert len(iteration_events) >= 1

    # Verify final response is meaningful
    response_text = "".join([c[2].get("content", "") for c in chunks if len(c) == 3])
    assert len(response_text) > 50


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agentic_vs_autonomous():
    """Compare agentic mode vs autonomous mode."""
    runner = SootheRunner()

    # Run same query in both modes
    agentic_result = []
    async for chunk in runner.astream(
        "Improve the code quality",
        max_iterations=2,
    ):
        agentic_result.append(chunk)

    autonomous_result = []
    async for chunk in runner.astream(
        "Improve the code quality",
        autonomous=True,
        max_iterations=2,
    ):
        autonomous_result.append(chunk)

    # Compare iteration counts
    agentic_iterations = len([
        c for c in agentic_result
        if len(c) == 3 and c[2].get("type") == "soothe.agentic.iteration_completed"
    ])

    autonomous_iterations = len([
        c for c in autonomous_result
        if len(c) == 3 and "iteration" in c[2].get("type", "")
    ])

    # Agentic should be lighter-weight
    assert agentic_iterations <= autonomous_iterations
```

## Migration Notes

### For Developers

1. **Remove single-pass assumptions**: Any code that assumed one-shot execution needs to handle multiple iterations
2. **Update tests**: Tests that relied on `_run_single_pass()` need to use `astream()` instead
3. **Event handlers**: Add handlers for new agentic events if needed

### For Users

No API changes - agentic loop is transparent:

```python
# Before (single-pass):
async for chunk in runner.astream("debug tests"):
    process(chunk)

# After (agentic loop, same API):
async for chunk in runner.astream("debug tests"):
    process(chunk)
# Now automatically iterates if needed
```

## Verification Checklist

- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Chitchat fast path works (< 500ms for simple queries)
- [ ] Planning strategies work correctly (none/lightweight/comprehensive)
- [ ] Iteration limit respected
- [ ] Early termination works
- [ ] Events emitted correctly
- [ ] TUI displays agentic loop progress
- [ ] Autonomous mode still works (RFC-200)
- [ ] No performance regression
- [ ] Documentation updated

## Performance Targets

| Metric | Target | Verification |
|--------|--------|--------------|
| Chitchat latency (P90) | < 500ms | Benchmark tests |
| Simple query latency | < 1.5s | Integration tests |
| Medium query latency | < 3s | Integration tests |
| Complex query latency | < 5s | Integration tests |
| Memory overhead | +5% max | Profiling |
| Iteration efficiency | 90%+ complete in ≤ 3 iterations | Metrics |

## Related Documents

- [RFC-201](../specs/RFC-201-agentic-goal-execution.md) - Agentic Loop Architecture
- [RFC-200](../specs/RFC-200-autonomous-goal-management.md) - Autonomous Iteration Loop
- [RFC-102](../specs/RFC-102-security-filesystem-policy.md) - Unified Classification
- [RFC-401](../specs/RFC-401-event-processing.md) - Progress Event Protocol

---

*Implementation guide for RFC-201: Agentic Loop Execution Architecture*
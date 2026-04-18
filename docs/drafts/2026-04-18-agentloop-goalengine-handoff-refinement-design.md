# Design: AgentLoop ↔ GoalEngine Handoff Architecture Refinement

**Date**: 2026-04-18
**Author**: Platonic Brainstorming Session
**Status**: Draft
**Purpose**: Refine Layer 2 ↔ Layer 3 handoff contracts with inverted control flow model

---

## Executive Summary

This design refines the AgentLoop (Layer 2) ↔ GoalEngine (Layer 3) handoff architecture by establishing an **inverted control flow model**: AgentLoop actively queries GoalEngine for goal assignment (pull-based), GoalEngine never invokes AgentLoop (service provider role). This design addresses three comprehensive aspects:

1. **Goal Pull Architecture**: AgentLoop actively pulls goal context, GoalEngine provides goal state service
2. **Failure Evidence Handoff Contract**: Layer 2 → Layer 3 evidence translation with RFC-200 EvidenceBundle
3. **Dual Trigger Synchronization Ordering**: Reactive + Pull trigger ordering for consistency

**Key Architectural Change**: Remove RFC-200 PERFORM delegation (GoalEngine → AgentLoop active call), replace with AgentLoop → GoalEngine pull model.

---

## Problem Statement

### Current RFC Architecture Issues

**RFC-200 §50-64**: Defines PERFORM stage as GoalEngine actively invoking AgentLoop.astream():
```python
# Current model (TO BE REMOVED)
async def perform_goal(goal: Goal) -> PlanResult:
    plan_result = await agentic_loop.astream(...)  # GoalEngine calls AgentLoop
    return plan_result
```

**RFC-201 §93-101**: States dual trigger synchronization (reactive + pull) but lacks:
- Explicit ordering specification
- Trigger timing details
- Race condition handling

**IG-189 §363-395**: Defines Layer2FailureHandoff contract but lacks:
- Evidence translation implementation pattern
- BackoffReasoner integration flow
- AgentLoop evidence construction responsibility

**Implementation Gap**: RFC-200 shows ⚠️ "Missing: Explicit Layer 2 delegation" (PERFORM stage not implemented)

### Architectural Principle Violation

Current model violates **Layer 2 execution ownership**: AgentLoop should drive execution timing, not be passively invoked by Layer 3.

**Protocol-first principle**: GoalEngine should provide goal state service (stable API), not orchestrate execution.

---

## Solution: Inverted Control Flow Architecture

### Core Principle

**AgentLoop drives execution, GoalEngine provides goal service.**

**Inversion**: ❌ Remove "GoalEngine PERFORM → AgentLoop delegation"
**Replacement**: ✅ "AgentLoop pull → GoalEngine query"

**Architectural Rationale**:
1. **Execution ownership**: Layer 2 controls execution timing and iteration loops
2. **Service provider pattern**: Layer 3 provides goal state (DAG, priorities, status)
3. **Pull-based integration**: AgentLoop queries when needed (need-based trigger)
4. **Event optional**: Events for observability, not control flow

---

## Component 1: Goal Pull Architecture

### Design Pattern

**AgentLoop Initialization** (run_with_progress):

```python
async def run_with_progress(...):
    # PULL: AgentLoop queries GoalEngine for current goal
    goal_engine = resolve_goal_engine(config)
    current_goal = goal_engine.get_next_ready_goal()  # Pull-based assignment
    
    if not current_goal:
        logger.info("No goals ready for execution")
        return None
    
    # AgentLoop owns execution loop
    thread_id = f"{base_tid}__goal_{current_goal.id}"
    state = LoopState(
        current_goal_id=current_goal.id,
        goal_text=current_goal.description,
        thread_id=thread_id,
        ...
    )
    
    # Execute Layer 2 Plan → Execute loop (AgentLoop drives)
    while iteration < max_iterations:
        plan_result = await self.plan_phase.plan(...)
        
        if plan_result.status == "done":
            # REPORT: AgentLoop reports completion to GoalEngine
            goal_engine.complete_goal(
                goal_id=current_goal.id,
                plan_result=plan_result,
            )
            return plan_result
        
        # Continue execution...
```

### GoalEngine API Refinement

**New Service Provider Interface**:

```python
class GoalEngine:
    """Layer 3 Goal Lifecycle Manager (Service Provider).
    
    Provides goal state service, never invokes AgentLoop.
    AgentLoop queries GoalEngine via pull-based API.
    """
    
    def get_next_ready_goal(self) -> Goal | None:
        """Get next goal ready for execution (DAG-satisfied, highest priority).
        
        Called by: AgentLoop before starting Layer 2 loop.
        
        Returns:
            Goal with dependencies satisfied, or None if no goals ready.
        
        DAG scheduling logic:
        - Filter: goals with all dependencies completed
        - Sort: by (-priority, created_at)
        - Activate: status "pending" → "active"
        """
        ready_goals = self.ready_goals(limit=1)
        if not ready_goals:
            return None
        
        goal = ready_goals[0]
        goal.status = "active"  # Activate on assignment
        return goal
    
    def complete_goal(
        self,
        goal_id: str,
        plan_result: PlanResult,
    ) -> None:
        """Mark goal completed with Layer 2 execution evidence.
        
        Called by: AgentLoop after successful Plan → Execute loop.
        
        Args:
            goal_id: Completed goal identifier.
            plan_result: Layer 2 final result with evidence_summary.
        
        Side effects:
        - Update goal status: "active" → "completed"
        - Store GoalReport with summary
        - Emit GoalCompletedEvent (optional observability)
        """
        goal = self._goals[goal_id]
        goal.status = "completed"
        goal.updated_at = datetime.now()
        
        goal.report = GoalReport(
            goal_id=goal_id,
            summary=plan_result.evidence_summary,
            iteration_count=state.iteration if state else 1,
            step_count=len(plan_result.decision.steps) if plan_result.decision else 0,
            final_plan_result=plan_result,
        )
        
        # Emit event for observability (optional)
        emit_event(
            GoalCompletedEvent(
                goal_id=goal_id,
                summary=plan_result.evidence_summary[:200],
                duration_ms=int((goal.updated_at - goal.created_at).total_seconds() * 1000),
            )
        )
    
    async def fail_goal(
        self,
        goal_id: str,
        evidence: EvidenceBundle,
        allow_retry: bool = True,
    ) -> BackoffDecision | None:
        """Mark goal failed with evidence, apply backoff reasoning.
        
        Called by: AgentLoop when Layer 2 execution fails.
        
        Args:
            goal_id: Failed goal identifier.
            evidence: Layer 2 execution evidence (RFC-200 EvidenceBundle contract).
            allow_retry: Whether retry is allowed.
        
        Returns:
            BackoffDecision if backoff reasoning applied, None if no retry.
        
        Backoff reasoning (GoalEngine internal):
        - Call GoalBackoffReasoner with goal context + evidence
        - Apply BackoffDecision (DAG restructuring)
        - Reset backoff target goal to "pending"
        
        Encapsulation: AgentLoop never calls BackoffReasoner directly.
        """
        goal = self._goals[goal_id]
        goal.status = "failed"
        goal.error = evidence.narrative
        goal.retry_count += 1
        
        if allow_retry and goal.retry_count < goal.max_retries:
            # GoalEngine owns backoff reasoning (encapsulated)
            goal_context = self._build_goal_context(goal_id)
            decision = await self._backoff_reasoner.reason_backoff(
                goal_id=goal_id,
                goal_context=goal_context,
                failed_evidence=evidence,
            )
            
            # Apply backoff decision (GoalEngine internal)
            self._apply_backoff_decision(decision)
            return decision
        
        return None
    
    def _apply_backoff_decision(self, decision: BackoffDecision) -> None:
        """Apply backoff decision to Goal DAG (GoalEngine internal logic).
        
        Not called by AgentLoop (encapsulated).
        
        Args:
            decision: LLM reasoning result with:
            - backoff_to_goal_id: WHERE to backoff in DAG
            - reason: Natural language reasoning
            - new_directives: GoalDirective[] for restructuring
        """
        backoff_goal = self._goals[decision.backoff_to_goal_id]
        backoff_goal.status = "pending"  # Reset for re-execution
        backoff_goal.retry_count = 0
        backoff_goal.updated_at = datetime.now()
        
        # Apply new directives
        for directive in decision.new_directives:
            self.apply_directive(directive)
        
        logger.info(
            "Goal backoff applied: goal %s → backoff to %s (reason: %s)",
            self._current_context.get("goal_id"),
            decision.backoff_to_goal_id,
            decision.reason,
        )
        
        # Persist DAG mutation
        self._persist_goal_state()
```

### Architectural Boundary Summary

| Responsibility | Owner | Integration Point |
|----------------|-------|-------------------|
| Execution control | AgentLoop | Loop timing, iteration management |
| Thread management | AgentLoop.Executor | CoreAgent thread coordination |
| Evidence construction | AgentLoop | EvidenceBundleBuilder from PlanResult |
| Goal state management | GoalEngine | Goal lifecycle, DAG structure |
| Backoff reasoning | GoalEngine (internal) | GoalBackoffReasoner (not exposed) |
| DAG restructuring | GoalEngine (internal) | BackoffDecision application |
| Completion tracking | GoalEngine | GoalReport persistence |

---

## Component 2: Failure Evidence Handoff Contract

### Evidence Flow Architecture

**Sequence**: AgentLoop detects failure → builds EvidenceBundle → calls GoalEngine.fail_goal() → GoalEngine applies BackoffReasoner

**EvidenceBundle Contract** (RFC-200 §14-22 canonical structure):

```python
class EvidenceBundle(BaseModel):
    """Canonical evidence payload for Layer 2 → Layer 3 handoff."""
    
    structured: dict[str, Any]
    """Machine-readable execution metrics for deterministic processing.
    
    Examples:
    - iteration: int
    - wave_tool_calls: int
    - wave_errors: int
    - goal_progress: float
    """
    
    narrative: str
    """Natural language synthesis for LLM reasoning and operator visibility.
    
    Synthesized from:
    - PlanResult.reasoning
    - PlanResult.evidence_summary
    - PlanResult.user_summary
    """
    
    source: Literal["layer2_execute", "layer2_plan", "layer3_reflect"]
    """Evidence producer stage."""
    
    timestamp: datetime
    """Evidence emission time."""
```

### EvidenceBundleBuilder Implementation Pattern

**AgentLoop Responsibility**: Construct EvidenceBundle from Layer 2 execution context.

```python
class EvidenceBundleBuilder:
    """Construct Layer 2 → Layer 3 evidence handoff payload."""
    
    def build_from_plan_result(
        self,
        plan_result: PlanResult,
        wave_metrics: dict[str, Any],  # Wave execution metrics from LoopState
        iteration: int,
    ) -> EvidenceBundle:
        """Build evidence bundle from Layer 2 PlanResult.
        
        Implements RFC-200 EvidenceBundle contract:
        - structured: Wave execution metrics (machine-readable)
        - narrative: PlanResult reasoning + evidence_summary (LLM-readable)
        - source: "layer2_execute" or "layer2_plan"
        
        Args:
            plan_result: Layer 2 PlanResult with evidence_summary, reasoning.
            wave_metrics: LoopState wave tracking fields (RFC-201 §236-245).
            iteration: Current iteration number.
        """
        
        # Structured: Wave metrics for deterministic processing (RFC-201 §236-245)
        structured = {
            "iteration": iteration,
            "wave_tool_calls": wave_metrics.get("last_wave_tool_call_count", 0),
            "wave_subagent_tasks": wave_metrics.get("last_wave_subagent_task_count", 0),
            "wave_errors": wave_metrics.get("last_wave_error_count", 0),
            "wave_output_length": wave_metrics.get("last_wave_output_length", 0),
            "wave_hit_subagent_cap": wave_metrics.get("last_wave_hit_subagent_cap", False),
            "goal_progress": plan_result.goal_progress,
            "confidence": plan_result.confidence,
            "plan_status": plan_result.status,
            "plan_action": plan_result.plan_action,
        }
        
        # Narrative: Natural language synthesis for GoalBackoffReasoner
        narrative = self._synthesize_failure_narrative(
            plan_reasoning=plan_result.reasoning,
            evidence_summary=plan_result.evidence_summary,
            user_summary=plan_result.user_summary,
            wave_metrics=wave_metrics,
        )
        
        return EvidenceBundle(
            structured=structured,
            narrative=narrative,
            source="layer2_execute",
            timestamp=datetime.now(),
        )
    
    def _synthesize_failure_narrative(
        self,
        plan_reasoning: str,
        evidence_summary: str,
        user_summary: str,
        wave_metrics: dict[str, Any],
    ) -> str:
        """Synthesize natural language failure narrative for backoff reasoning.
        
        Goal: Provide GoalBackoffReasoner complete failure context
        for deciding WHERE to backoff in goal DAG.
        
        Structure:
        1. Plan reasoning (why Layer 2 thought this approach)
        2. Evidence summary (what actually happened)
        3. Wave metrics pattern (execution anomalies)
        4. Gap analysis (expected vs actual)
        
        Args:
            plan_reasoning: LLM reasoning from PlanResult.reasoning.
            evidence_summary: Execution evidence from PlanResult.evidence_summary.
            user_summary: User-facing summary from PlanResult.user_summary.
            wave_metrics: LoopState wave tracking fields (RFC-201 §236-245).
        """
        iteration = wave_metrics.get("iteration", 0)
        tool_calls = wave_metrics.get("last_wave_tool_call_count", 0)
        subagent_tasks = wave_metrics.get("last_wave_subagent_task_count", 0)
        errors = wave_metrics.get("last_wave_error_count", 0)
        output_length = wave_metrics.get("last_wave_output_length", 0)
        hit_cap = wave_metrics.get("last_wave_hit_subagent_cap", False)
        
        sections = [
            f"## Layer 2 Execution Failure Evidence\n\n",
            f"**Iteration**: {iteration}\n\n",
            f"**Plan Reasoning**:\n{plan_reasoning}\n\n",
            f"**Evidence Summary**:\n{evidence_summary}\n\n",
            f"**User Summary**:\n{user_summary}\n\n",
            f"**Wave Metrics Pattern**:\n",
            f"- Tool calls: {tool_calls}\n",
            f"- Subagent tasks: {subagent_tasks}\n",
            f"- Errors: {errors}\n",
            f"- Output length: {output_length}\n",
            f"- Hit subagent cap: {hit_cap}\n\n",
        ]
        
        if errors > 0:
            sections.append(
                f"**Failure Mode**: Execution errors detected during wave.\n\n"
            )
        
        if hit_cap:
            sections.append(
                f"**Resource Constraint**: Subagent task cap reached (default max: 2).\n\n"
            )
        
        return "".join(sections)
    
    def build_from_exception(
        self,
        exception: Exception,
        state: LoopState,
    ) -> EvidenceBundle:
        """Build evidence bundle from execution exception.
        
        Used when CoreAgent execution throws exception (not PlanResult failure).
        """
        structured = {
            "iteration": state.iteration,
            "exception_type": type(exception).__name__,
            "exception_message": str(exception)[:500],
            "goal_progress": state.last_plan_result.goal_progress if state.last_plan_result else 0.0,
        }
        
        narrative = f"## Execution Exception\n\n**Exception**: {type(exception).__name__}\n\n**Message**: {str(exception)}\n\n**Context**: Goal '{state.goal_text}' at iteration {state.iteration}\n\n"
        
        return EvidenceBundle(
            structured=structured,
            narrative=narrative,
            source="layer2_execute",
            timestamp=datetime.now(),
        )
```

### Handoff Integration in AgentLoop.Executor

**Failure Detection Pattern**:

```python
# AgentLoop.Executor
async def execute(self, decision: AgentDecision, state: LoopState):
    """Execute AgentDecision steps with failure handoff."""
    
    goal_engine = resolve_goal_engine(self.config)
    evidence_builder = EvidenceBundleBuilder()
    
    try:
        # Execute steps
        results = await self._execute_steps(decision, state)
        
        # Check execution status
        if self._execution_failed(results):
            # BUILD: Construct failure evidence
            evidence = evidence_builder.build_from_plan_result(
                plan_result=state.last_plan_result,
                wave_metrics=state.last_wave_metrics,
                iteration=state.iteration,
            )
            
            # HANDOFF: AgentLoop → GoalEngine with evidence
            backoff_decision = await goal_engine.fail_goal(
                goal_id=state.current_goal_id,
                evidence=evidence,
                allow_retry=True,
            )
            
            # REACT: Log backoff decision (GoalEngine already applied internally)
            if backoff_decision:
                logger.info(
                    "Goal %s backoff: backoff_to=%s, reason=%s",
                    state.current_goal_id,
                    backoff_decision.backoff_to_goal_id,
                    backoff_decision.reason,
                )
            
            return ExecuteResult(
                status="failed",
                backoff_decision=backoff_decision,
            )
        
        # Success path
        return ExecuteResult(status="success", results=results)
    
    except Exception as e:
        # Exception handoff
        evidence = evidence_builder.build_from_exception(exception=e, state=state)
        await goal_engine.fail_goal(
            goal_id=state.current_goal_id,
            evidence=evidence,
            allow_retry=False,  # Exception usually non-retryable
        )
        
        raise
```

### GoalBackoffReasoner Integration (GoalEngine Internal)

**Encapsulation**: AgentLoop never calls BackoffReasoner directly. GoalEngine owns backoff reasoning.

```python
# GoalEngine internal (not exposed to AgentLoop)
async def fail_goal(self, goal_id: str, evidence: EvidenceBundle, ...):
    """AgentLoop calls this, GoalEngine internally applies backoff."""
    
    goal.status = "failed"
    goal.error = evidence.narrative
    
    if allow_retry and goal.retry_count < goal.max_retries:
        # GoalEngine internal: build goal context for BackoffReasoner
        goal_context = GoalContext(
            current_goal_id=goal_id,
            all_goals=self._snapshot_all_goals(),
            completed_goals=self._get_completed_goal_ids(),
            failed_goals=self._get_failed_goal_ids(),
            ready_goals=self._get_ready_goal_ids(),
            max_parallel_goals=self._config.max_parallel_goals,
        )
        
        # GoalEngine internal: call BackoffReasoner
        decision = await self._backoff_reasoner.reason_backoff(
            goal_id=goal_id,
            goal_context=goal_context,
            failed_evidence=evidence,
        )
        
        # GoalEngine internal: apply decision (DAG restructuring)
        self._apply_backoff_decision(decision)
        
        return decision
    
    return None
```

---

## Component 3: Dual Trigger Synchronization Ordering

### Trigger Type Definition

```python
class SyncTriggerType(Enum):
    """AgentLoop synchronization trigger types with GoalEngine."""
    
    REACTIVE = "reactive"
    """Event-bound trigger: fired on execution boundaries.
    
    Purpose: Update GoalEngine state with execution evidence immediately.
    Timing: After execution boundaries (completion, failure, step completion).
    Direction: AgentLoop → GoalEngine (push evidence).
    Examples: complete_goal(), fail_goal(), event emission.
    """
    
    PULL = "pull"
    """Need-based trigger: fired before decisions requiring goal context.
    
    Purpose: Query GoalEngine for authoritative goal state before planning.
    Timing: Before Plan phase, after backoff, before iteration boundary.
    Direction: AgentLoop → GoalEngine (query goal data).
    Examples: get_goal(), get_next_ready_goal(), ready_goals().
    """
```

### Ordering Specification (Per Iteration)

**Sync Sequence**: PULL → Plan → Execute → REACTIVE → PULL (cycle)

```python
class AgentLoopSyncOrchestrator:
    """Manages AgentLoop synchronization triggers with GoalEngine.
    
    Ordering principle: PULL before decision, REACTIVE after execution.
    """
    
    async def run_iteration(self, state: LoopState) -> PlanResult:
        """Single AgentLoop iteration with ordered synchronization.
        
        Sync ordering:
        1. PULL #1 (before Plan): Get authoritative goal state
        2. PLAN: LLM reasoning with goal context
        3. EXECUTE: Run steps, collect evidence
        4. REACTIVE #1 (on completion): complete_goal()
        5. REACTIVE #2 (on failure): fail_goal()
        6. PULL #2 (after backoff): Check updated goal status
        7. REACTIVE #3 (step completion): Emit event (optional)
        8. PULL #3 (before next iteration): Check DAG consistency
        """
        
        goal_engine = resolve_goal_engine(self.config)
        
        # === STEP 1: PULL TRIGGER #1 - Before Plan decision ===
        current_goal_state = goal_engine.get_goal(state.current_goal_id)
        
        # Decision point: Check if goal still active
        if current_goal_state.status != "active":
            logger.info(
                "Goal %s no longer active (status: %s) - aborting iteration",
                state.current_goal_id,
                current_goal_state.status,
            )
            return PlanResult(
                status="abort",
                reasoning=f"Goal state changed: {current_goal_state.status}",
            )
        
        # Inject goal context for Plan phase
        state.goal_priority = current_goal_state.priority
        state.goal_dependencies = current_goal_state.depends_on
        state.goal_retry_count = current_goal_state.retry_count
        
        # === STEP 2: PLAN PHASE ===
        plan_result = await self.plan_phase.plan(
            goal=state.goal_text,
            state=state,
            context=self._build_plan_context(state, current_goal_state),
        )
        
        # === STEP 3: DECISION CHECK ===
        if plan_result.status == "done":
            # Goal completed successfully
            
            # === STEP 4: REACTIVE TRIGGER #1 - Goal completion ===
            goal_engine.complete_goal(
                goal_id=state.current_goal_id,
                plan_result=plan_result,
            )
            
            logger.info(
                "Goal %s completed successfully",
                state.current_goal_id,
            )
            
            return plan_result
        
        # === STEP 4: EXECUTE PHASE ===
        decision = plan_result.decision
        execute_results = await self.executor.execute(decision, state)
        
        # Collect execution evidence
        evidence_bundle = self._build_execution_evidence(
            plan_result=plan_result,
            execute_results=execute_results,
            iteration=state.iteration,
        )
        
        # === STEP 5: REACTIVE TRIGGER #2 - Failure handoff ===
        if execute_results.status == "failed":
            backoff_decision = await goal_engine.fail_goal(
                goal_id=state.current_goal_id,
                evidence=evidence_bundle,
                allow_retry=True,
            )
            
            # GoalEngine applied backoff internally
            
            # === STEP 6: PULL TRIGGER #2 - After backoff ===
            updated_goal_state = goal_engine.get_goal(state.current_goal_id)
            
            if updated_goal_state.status == "pending":
                # Goal reset to pending (backoff applied to prerequisite)
                logger.info(
                    "Goal %s reset to pending after backoff to %s - ending iteration",
                    state.current_goal_id,
                    backoff_decision.backoff_to_goal_id,
                )
                
                return PlanResult(
                    status="backoff",
                    reasoning=f"Backoff applied: {backoff_decision.reason}",
                    backoff_decision=backoff_decision,
                )
            
            # Continue with failure result
            return plan_result
        
        # === STEP 7: REACTIVE TRIGGER #3 - Step completion (optional) ===
        emit_event(
            StepCompletedEvent(
                goal_id=state.current_goal_id,
                iteration=state.iteration,
                evidence_summary=evidence_bundle.narrative[:200],
            )
        )
        
        # === STEP 8: PULL TRIGGER #3 - Before next iteration ===
        # Check DAG consistency: current goal dependencies still satisfied?
        ready_goals = goal_engine.ready_goals(limit=10)
        current_goal_ready = any(g.id == state.current_goal_id for g in ready_goals)
        
        if not current_goal_ready:
            # Goal no longer ready (reflection added dependencies)
            logger.info(
                "Goal %s no longer ready (dependencies changed) - deferring",
                state.current_goal_id,
            )
            
            return PlanResult(
                status="deferred",
                reasoning="Goal dependencies changed, no longer ready for execution",
            )
        
        # Continue iteration loop
        return plan_result
```

### Trigger Timing Matrix

| Trigger | When | Purpose | AgentLoop Call | GoalEngine Response |
|---------|------|---------|----------------|---------------------|
| **PULL #1** | Before Plan | Get goal state for planning | `get_goal(goal_id)` | Return goal: status, priority, dependencies |
| **REACTIVE #1** | Goal completion | Mark goal completed | `complete_goal(goal_id, plan_result)` | Update status "completed", store GoalReport |
| **REACTIVE #2** | Execution failure | Handoff failure evidence | `fail_goal(goal_id, evidence)` | Apply BackoffReasoner, mutate DAG |
| **PULL #2** | After backoff | Check updated goal state | `get_goal(goal_id)` | Return post-backoff goal status |
| **REACTIVE #3** | Step completion | Emit evidence (optional) | `emit_event(StepCompleted)` | Observability only (no state change) |
| **PULL #3** | Before next iteration | Check DAG consistency | `ready_goals(limit)` | Return ready goals list |

### Critical Ordering Constraints

**Constraint #1: PULL before Plan (mandatory)**
- **Reason**: Plan decisions require authoritative goal state (priority, dependencies, status)
- **Violation consequence**: Planning with stale goal context, wrong priority order, missing dependency awareness
- **Enforcement**: Abort iteration if goal status ≠ "active"

**Constraint #2: REACTIVE after execution (immediate)**
- **Reason**: GoalEngine needs execution evidence for DAG decisions (completion tracking, backoff reasoning)
- **Violation consequence**: GoalEngine state stale during reflection, backoff decisions based on outdated evidence
- **Enforcement**: Call complete_goal() / fail_goal() immediately after execution boundary

**Constraint #3: PULL after backoff (before continuing)**
- **Reason**: Backoff may reset goal status to "pending" or add new dependencies
- **Violation consequence**: AgentLoop continues executing goal that's no longer active
- **Enforcement**: Check goal status after fail_goal(), abort if "pending"

**Constraint #4: PULL before iteration boundary (DAG consistency)**
- **Reason**: Reflection may have added dependencies to current goal (dynamic restructuring)
- **Violation consequence**: AgentLoop executes goal with unsatisfied dependencies
- **Enforcement**: Call ready_goals(), defer if goal not in ready list

### Race Condition Handling

**Scenario #1: External GoalEngine DAG mutation**
- **Problem**: Goal manually edited via file watcher (RFC-200 §709-726)
- **Solution**: PULL #1 before Plan detects status change → abort iteration
- **Result**: AgentLoop pulls new goal on next iteration

**Scenario #2: Parallel AgentLoop threads for multiple goals**
- **Problem**: Multiple threads executing ready_goals concurrently
- **Solution**: Each thread pulls independently, GoalEngine atomic state updates
- **Result**: Threads synchronized via GoalEngine state atomicity

**Scenario #3: Backoff applied while AgentLoop still executing**
- **Problem**: GoalEngine.fail_goal() called, but AgentLoop iteration continues
- **Solution**: PULL #2 after backoff checks goal status → abort if "pending"
- **Result**: AgentLoop ends iteration, pulls new goal state on next cycle

**Scenario #4: Reflection adds dependency to active goal**
- **Problem**: Layer 3 reflection adds new prerequisite to goal currently executing
- **Solution**: PULL #3 before next iteration checks ready_goals() → goal not ready → defer
- **Result**: AgentLoop defers current goal, scheduler picks up prerequisite

### Configuration Schema

```yaml
agentic:
  sync_strategy:
    # Pull triggers (mandatory for consistency)
    pull_before_plan: true        # PULL #1: Get goal state before Plan
    pull_after_backoff: true      # PULL #2: Check updated goal after backoff
    pull_before_iteration: true   # PULL #3: DAG consistency check
    
    # Reactive triggers (immediate evidence push)
    reactive_on_completion: true  # REACTIVE #1: Report goal completion
    reactive_on_failure: true     # REACTIVE #2: Handoff failure evidence
    reactive_on_step: optional    # REACTIVE #3: Emit step events (observability)
```

---

## Architectural Impact Analysis

### RFC Changes Required

**RFC-200 (Layer 3 Goal Management) - Major Refactoring**:

| Section | Action | Reason |
|---------|--------|--------|
| §50-64 | ❌ **REMOVE** | PERFORM → Layer 2 delegation contradicts inverted control |
| §NEW | ✅ **ADD** | "AgentLoop Goal Pull Architecture" section |
| §NEW | ✅ **ADD** | "EvidenceBundle Handoff Contract" details |
| §2.1 | ✅ **KEEP** | GoalBackoffReasoner unchanged (internal to GoalEngine) |
| §14-22 | ✅ **KEEP** | EvidenceBundle contract unchanged (canonical) |
| §95-101 | ✅ **KEEP** | Dual trigger synchronization unchanged |

**RFC-201 (Layer 2 AgentLoop) - Major Refactoring**:

| Section | Action | Reason |
|---------|--------|--------|
| §39-47 | ❌ **REMOVE** | Layer 3 → Layer 2 integration (replace with pull model) |
| §93-101 | ✅ **CLARIFY** | Dual trigger ordering specification (add detailed ordering) |
| §NEW | ✅ **ADD** | "Goal Pull Integration" section (AgentLoop queries GoalEngine) |
| §NEW | ✅ **ADD** | "Failure Evidence Handoff" section (EvidenceBundleBuilder pattern) |
| §352-395 | ✅ **KEEP** | Layer 2 failure handoff concept unchanged |

**RFC-001 (Core Modules) - No Changes**:
- ContextProtocol integration unchanged
- MemoryProtocol integration unchanged

### Implementation Files Impact

**New Files Required**:
- `cognition/agent_loop/evidence_builder.py`: EvidenceBundleBuilder implementation
- `cognition/agent_loop/sync_orchestrator.py`: Dual trigger ordering orchestrator
- `cognition/goal_engine/backoff_reasoner.py`: GoalBackoffReasoner (RFC-200 §2.1)

**Modified Files Required**:
- `cognition/agent_loop/agent_loop.py`: Add goal pull logic, remove PERFORM assumption
- `cognition/agent_loop/executor.py`: Add failure evidence handoff pattern
- `cognition/goal_engine.py`: Add `get_next_ready_goal()`, refine `complete_goal()`/`fail_goal()`

**No Implementation in this Design Phase**:
- Design only, code implementation deferred to Platonic Coding Phase 2

---

## Testing Strategy

### Integration Test Scenarios

**Test #1: Goal Pull Architecture**:
- AgentLoop calls `get_next_ready_goal()` → receives goal
- AgentLoop calls `complete_goal()` after success → GoalEngine marks completed
- AgentLoop calls `fail_goal()` with evidence → GoalEngine applies backoff

**Test #2: Failure Evidence Handoff**:
- EvidenceBundleBuilder constructs from PlanResult + wave metrics
- EvidenceBundle structured field contains wave metrics
- EvidenceBundle narrative field contains synthesized reasoning
- GoalEngine.fail_goal() receives EvidenceBundle, applies BackoffReasoner

**Test #3: Dual Trigger Ordering**:
- PULL #1 before Plan: aborts iteration if goal status ≠ "active"
- REACTIVE #1 after completion: calls complete_goal() immediately
- REACTIVE #2 after failure: calls fail_goal() with evidence
- PULL #2 after backoff: detects goal status "pending", aborts iteration
- PULL #3 before iteration: defers if goal not in ready_goals()

**Test #4: Race Condition Handling**:
- External DAG mutation → PULL #1 detects → abort iteration
- Backoff applied → PULL #2 detects goal "pending" → end iteration
- Reflection adds dependency → PULL #3 detects goal not ready → defer

### Success Criteria

1. **Control flow correctness**: AgentLoop drives execution, GoalEngine never calls AgentLoop
2. **Evidence contract stability**: EvidenceBundle matches RFC-200 schema, GoalEngine accepts evidence
3. **Synchronization consistency**: PULL before Plan, REACTIVE after execution ordering enforced
4. **Backoff encapsulation**: AgentLoop never calls BackoffReasoner, GoalEngine applies internally
5. **DAG consistency**: PULL triggers detect goal status changes, abort/defer iterations correctly

---

## Performance Considerations

### Overhead Analysis

**Goal Pull Overhead**:
- `get_goal()`: <1ms (in-memory GoalEngine state lookup)
- `get_next_ready_goal()`: <2ms (DAG traversal + priority sort)
- `complete_goal()`: <5ms (status update + event emission)

**Evidence Construction Overhead**:
- EvidenceBundleBuilder: <10ms (wave metrics extraction + narrative synthesis)
- Narrative synthesis: Regex extraction + string concatenation (bounded by limit)

**Synchronization Overhead**:
- PULL triggers: 3 calls per iteration × <2ms = <6ms per iteration
- REACTIVE triggers: 1-2 calls per iteration × <5ms = <10ms per iteration
- Total sync overhead: <16ms per iteration (negligible compared to LLM latency)

### Optimization Opportunities

**Caching**: GoalEngine state cached in AgentLoop state between PULL calls (avoid redundant queries)

**Lazy narrative**: EvidenceBundle narrative synthesized only when failure detected (skip on success)

**Batch events**: Multiple step completion events batched into single emission (optional REACTIVE #3)

---

## Migration Path

### Backward Compatibility

**Existing AgentLoop executions**: Continue without GoalEngine integration (if autonomous mode disabled)

**Existing GoalEngine state**: Unchanged (GoalEngine API additions are non-breaking)

**RFC compatibility**: Design aligns with existing RFC principles (no architectural breaking changes)

### Implementation Sequence

**Phase 1**: GoalEngine API refinement (`get_next_ready_goal()`, `fail_goal()` evidence integration)
**Phase 2**: AgentLoop goal pull integration (remove PERFORM assumption)
**Phase 3**: EvidenceBundleBuilder implementation (failure handoff contract)
**Phase 4**: Sync orchestrator implementation (dual trigger ordering)
**Phase 5**: GoalBackoffReasoner implementation (RFC-200 §2.1)

---

## References

- RFC-200: Autonomous Goal Management Loop (Layer 3)
- RFC-201: AgentLoop Plan-Execute Loop Architecture (Layer 2)
- RFC-001: Core Modules Architecture (ContextProtocol, MemoryProtocol)
- RFC-609: Goal Context Management for AgentLoop
- IG-189: Architecture Refinement from Brainstorming Session
- RFC-600: Event Processing & Filtering (optional event emission)

---

## Appendix: Design Decision Rationale

### Why Inverted Control Flow?

**Rationale**: Layer 2 should own execution timing (matches RFC-201 executor role), Layer 3 should provide goal state service (matches protocol-first principle). Active PERFORM delegation violates execution ownership boundary.

**Alternative rejected**: Pure event-driven (contradicts RFC-201 direct integration model, adds latency, creates event storms in multi-goal execution).

### Why Dual Trigger Synchronization?

**Rationale**: Single trigger model insufficient:
- Pure reactive: AgentLoop state stale during planning (no goal context pull before Plan)
- Pure pull: GoalEngine state stale during execution (no evidence push after failure)

**Hybrid solution**: PULL before decisions (need-based) + REACTIVE after execution (event-bound) → complete synchronization coverage.

### Why EvidenceBundleBuilder in AgentLoop?

**Rationale**: AgentLoop owns execution context (PlanResult, wave metrics). GoalEngine lacks access to Layer 2 execution details. Evidence construction responsibility naturally falls to evidence producer (AgentLoop).

**Alternative rejected**: GoalEngine queries AgentLoop for evidence → violates inverted control (GoalEngine should not query AgentLoop).

### Why GoalBackoffReasoner Encapsulated?

**Rationale**: GoalEngine owns goal lifecycle (RFC-200 §144-179). Backoff reasoning is goal-level decision, requires goal context (all goals, DAG structure). AgentLoop lacks goal DAG visibility. Encapsulation preserves architectural separation.

**Alternative rejected**: AgentLoop calls BackoffReasoner → violates goal ownership boundary, AgentLoop needs GoalEngine context anyway (circular dependency).

---

*Design complete. Ready for user review before RFC refactoring phase.*
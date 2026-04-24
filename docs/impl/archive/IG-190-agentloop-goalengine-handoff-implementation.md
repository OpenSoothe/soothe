---
title: IG-190 AgentLoop ↔ GoalEngine Handoff Implementation
status: draft
created: 2026-04-18
last_updated: 2026-04-18
author: Xiaming Chen
related_rfc: [RFC-200, RFC-201, RFC-609]
tags: [implementation, agentloop, goalengine, handoff, context-construction]
---

# IG-190: AgentLoop ↔ GoalEngine Handoff Implementation

## Overview

This implementation guide documents code patterns for AgentLoop (Layer 2) ↔ GoalEngine (Layer 3) handoff architecture refinements. Companion to design draft `2026-04-18-agentloop-goalengine-handoff-refinement-design.md`.

**Key Refinements**:
1. Inverted control flow (AgentLoop pulls goals)
2. Dual trigger synchronization ordering
3. Failure evidence handoff (EvidenceBundleBuilder)
4. GoalContext construction (dependency-driven retrieval)

**Implementation Scope**: Code patterns, data structures, integration points. Architecture design remains in RFCs.

---

## Component 1: GoalEngine Service Provider API

**File**: `cognition/goal_engine.py`

### GoalEngine Goal Pull API

```python
class GoalEngine:
    """Layer 3 Goal Lifecycle Manager (Service Provider).
    
    Provides goal state service for AgentLoop queries.
    Never invokes AgentLoop (inverted control flow).
    """
    
    def get_next_ready_goal(self) -> Goal | None:
        """Get next goal ready for execution (DAG-satisfied, highest priority).
        
        Called by: AgentLoop before starting Layer 2 loop.
        
        Returns:
            Goal with dependencies satisfied, or None if no goals ready.
        
        Implementation:
        - Filter goals with all dependencies completed
        - Sort by (-priority, created_at)
        - Activate: status "pending" → "active"
        - Return top goal
        """
        ready_goals = self.ready_goals(limit=1)
        if not ready_goals:
            return None
        
        goal = ready_goals[0]
        goal.status = "active"
        goal.updated_at = datetime.now()
        self._persist_goal_state()
        
        logger.info(
            "Goal assignment: goal %s (priority %d) activated",
            goal.id,
            goal.priority,
        )
        
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
        
        Implementation:
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
            iteration_count=self._extract_iteration_count(plan_result),
            step_count=self._extract_step_count(plan_result),
            final_plan_result=plan_result,
        )
        
        self._persist_goal_state()
        
        # Emit event for observability
        emit_event(
            GoalCompletedEvent(
                goal_id=goal_id,
                summary=plan_result.evidence_summary[:200],
                duration_ms=int((goal.updated_at - goal.created_at).total_seconds() * 1000),
            )
        )
        
        logger.info(
            "Goal completion: goal %s completed after %d iterations",
            goal_id,
            goal.report.iteration_count,
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
        
        Implementation:
        - Update goal status: "active" → "failed"
        - If retry allowed and retry_count < max_retries:
          - Build GoalContext snapshot
          - Call BackoffReasoner.reason_backoff()
          - Apply BackoffDecision (DAG restructuring)
          - Return decision
        - Else: return None
        """
        goal = self._goals[goal_id]
        goal.status = "failed"
        goal.error = evidence.narrative
        goal.retry_count += 1
        goal.updated_at = datetime.now()
        
        logger.warning(
            "Goal failure: goal %s failed (retry %d/%d)",
            goal_id,
            goal.retry_count,
            goal.max_retries,
        )
        
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
            
            logger.info(
                "Goal backoff: goal %s → backoff to %s (reason: %s)",
                goal_id,
                decision.backoff_to_goal_id,
                decision.reason,
            )
            
            return decision
        
        self._persist_goal_state()
        return None
    
    def _apply_backoff_decision(self, decision: BackoffDecision) -> None:
        """Apply backoff decision to Goal DAG (GoalEngine internal).
        
        Args:
            decision: LLM reasoning result with:
            - backoff_to_goal_id: WHERE to backoff in DAG
            - reason: Natural language reasoning
            - new_directives: GoalDirective[] for restructuring
        
        Implementation:
        - Reset backoff target goal to "pending"
        - Apply new directives
        - Persist DAG mutation
        """
        backoff_goal = self._goals[decision.backoff_to_goal_id]
        backoff_goal.status = "pending"
        backoff_goal.retry_count = 0
        backoff_goal.updated_at = datetime.now()
        
        # Apply new directives
        for directive in decision.new_directives:
            self.apply_directive(directive)
        
        self._persist_goal_state()
        
        logger.info(
            "Backoff applied: goal %s reset to pending",
            decision.backoff_to_goal_id,
        )
```

---

## Component 2: Dual Trigger Synchronization Orchestrator

**File**: `cognition/agent_loop/sync_orchestrator.py`

### AgentLoop Sync Ordering Implementation

```python
class AgentLoopSyncOrchestrator:
    """Manages AgentLoop synchronization triggers with GoalEngine.
    
    Ordering principle: PULL before decision, REACTIVE after execution.
    """
    
    async def run_iteration(self, state: LoopState) -> PlanResult:
        """Single AgentLoop iteration with ordered synchronization.
        
        Sync sequence (8 steps):
        1. PULL #1: Get goal state before Plan
        2. PLAN: LLM reasoning with goal context
        3. EXECUTE: Run steps
        4. REACTIVE #1: complete_goal() on success
        5. REACTIVE #2: fail_goal() on failure
        6. PULL #2: Check goal status after backoff
        7. REACTIVE #3: Emit step event (optional)
        8. PULL #3: Check DAG consistency before next iteration
        """
        goal_engine = self.config.resolve_goal_engine()
        
        # === STEP 1: PULL TRIGGER #1 - Before Plan ===
        current_goal = goal_engine.get_goal(state.current_goal_id)
        
        if current_goal.status != "active":
            logger.info(
                "Goal %s no longer active (status: %s) - aborting",
                state.current_goal_id,
                current_goal.status,
            )
            return PlanResult(
                status="abort",
                reasoning=f"Goal state changed: {current_goal.status}",
            )
        
        # Inject goal context
        state.goal_priority = current_goal.priority
        state.goal_dependencies = current_goal.depends_on
        
        # === STEP 2: PLAN ===
        plan_result = await self.plan_phase.plan(
            goal=state.goal_text,
            state=state,
            context=self._build_plan_context(state, current_goal),
        )
        
        # === STEP 3: DECISION CHECK ===
        if plan_result.status == "done":
            # Goal completed
            
            # === STEP 4: REACTIVE TRIGGER #1 ===
            goal_engine.complete_goal(state.current_goal_id, plan_result)
            
            logger.info("Goal %s completed", state.current_goal_id)
            return plan_result
        
        # === STEP 4: EXECUTE ===
        decision = plan_result.decision
        execute_results = await self.executor.execute(decision, state)
        
        # === STEP 5: REACTIVE TRIGGER #2 - Failure ===
        if execute_results.status == "failed":
            evidence = self._build_failure_evidence(plan_result, state)
            
            backoff = await goal_engine.fail_goal(
                goal_id=state.current_goal_id,
                evidence=evidence,
                allow_retry=True,
            )
            
            # === STEP 6: PULL TRIGGER #2 - After backoff ===
            updated_goal = goal_engine.get_goal(state.current_goal_id)
            
            if updated_goal.status == "pending":
                logger.info(
                    "Goal %s reset to pending after backoff - ending iteration",
                    state.current_goal_id,
                )
                
                return PlanResult(
                    status="backoff",
                    reasoning=f"Backoff applied: {backoff.reason}",
                    backoff_decision=backoff,
                )
            
            return plan_result
        
        # === STEP 7: REACTIVE TRIGGER #3 - Optional ===
        emit_event(
            StepCompletedEvent(
                goal_id=state.current_goal_id,
                iteration=state.iteration,
                evidence_summary=...,
            )
        )
        
        # === STEP 8: PULL TRIGGER #3 - Before next iteration ===
        ready_goals = goal_engine.ready_goals(limit=10)
        
        if state.current_goal_id not in [g.id for g in ready_goals]:
            logger.info(
                "Goal %s no longer ready (dependencies changed) - deferring",
                state.current_goal_id,
            )
            
            return PlanResult(
                status="deferred",
                reasoning="Dependencies changed",
            )
        
        return plan_result
```

---

## Component 3: EvidenceBundleBuilder

**File**: `cognition/agent_loop/evidence_builder.py`

### Failure Evidence Construction

```python
class EvidenceBundleBuilder:
    """Construct Layer 2 → Layer 3 evidence handoff payload."""
    
    def build_from_plan_result(
        self,
        plan_result: PlanResult,
        wave_metrics: dict[str, Any],
        iteration: int,
    ) -> EvidenceBundle:
        """Build evidence bundle from Layer 2 PlanResult.
        
        Args:
            plan_result: Layer 2 result with reasoning, evidence_summary.
            wave_metrics: LoopState wave tracking fields §236-245.
            iteration: Current iteration number.
        
        Returns:
            EvidenceBundle with structured metrics + narrative synthesis.
        """
        
        # Structured: Wave metrics for deterministic processing
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
        }
        
        # Narrative: Natural language synthesis
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
        """Synthesize natural language failure narrative.
        
        Structure:
        - Plan reasoning
        - Evidence summary
        - Wave metrics pattern
        - Failure mode analysis
        """
        iteration = wave_metrics.get("iteration", 0)
        tool_calls = wave_metrics.get("last_wave_tool_call_count", 0)
        subagent_tasks = wave_metrics.get("last_wave_subagent_task_count", 0)
        errors = wave_metrics.get("last_wave_error_count", 0)
        hit_cap = wave_metrics.get("last_wave_hit_subagent_cap", False)
        
        sections = [
            f"## Layer 2 Execution Failure Evidence\n\n",
            f"**Iteration**: {iteration}\n\n",
            f"**Plan Reasoning**:\n{plan_reasoning}\n\n",
            f"**Evidence Summary**:\n{evidence_summary}\n\n",
            f"**User Summary**:\n{user_summary}\n\n",
            f"**Wave Metrics**:\n",
            f"- Tool calls: {tool_calls}\n",
            f"- Subagent tasks: {subagent_tasks}\n",
            f"- Errors: {errors}\n",
            f"- Hit cap: {hit_cap}\n\n",
        ]
        
        if errors > 0:
            sections.append("**Failure Mode**: Execution errors.\n\n")
        
        if hit_cap:
            sections.append("**Resource Constraint**: Subagent cap reached.\n\n")
        
        return "".join(sections)
```

---

## Component 4: GoalContextConstructor

**File**: `cognition/agent_loop/goal_context_constructor.py`

### Dependency-Driven Context Construction

```python
class GoalContextConstructor:
    """Construct dependency-driven GoalContext for Plan phase.
    
    Synthesis strategy:
    1. GoalEngine.get_goal() → current goal metadata
    2. For each dependency goal: retrieve execution history
    3. Combine dependency + current + previous goal context
    """
    
    def __init__(
        self,
        goal_engine: GoalEngine,
        context_protocol: ContextProtocol,
        goal_context_manager: GoalContextManager,
        config: GoalContextConfig,
    ) -> None:
        self._goal_engine = goal_engine
        self._context = context_protocol
        self._goal_context_manager = goal_context_manager
        self._config = config
    
    def construct_plan_context(
        self,
        goal_id: str,
    ) -> PlanContext:
        """Construct dependency-aware Plan context.
        
        Entry limits (fixed):
        - Dependency context: 5 entries per dependency goal
        - Current goal context: 10 entries
        - Previous goals: 5 summaries
        
        Returns:
            PlanContext with dependency-aware entries.
        """
        
        # Step 1: Get GoalEngine metadata
        current_goal = self._goal_engine.get_goal(goal_id)
        
        if not current_goal:
            logger.warning("Goal %s not found", goal_id)
            return PlanContext(entries=[], metadata={})
        
        # Step 2: Dependency-driven retrieval
        dependency_entries = []
        
        if current_goal.depends_on:
            retrieval_module = self._context.get_retrieval_module()
            
            for dep_goal_id in current_goal.depends_on:
                dep_goal = self._goal_engine.get_goal(dep_goal_id)
                
                dep_entries = retrieval_module.retrieve_by_goal_relevance(
                    goal_id=dep_goal_id,
                    execution_context={"retrieval_type": "dependency"},
                    limit=5,
                )
                
                dependency_entries.extend([
                    ContextEntry(
                        source=entry.source,
                        content=entry.content,
                        metadata={
                            "goal_id": dep_goal_id,
                            "goal_text": dep_goal.description if dep_goal else "",
                            "goal_priority": dep_goal.priority if dep_goal else 0,
                            "dependency_relation": "prerequisite",
                        },
                    )
                    for entry in dep_entries
                ])
        
        logger.info(
            "Dependency retrieval: goal %s has %d dependencies → %d entries",
            goal_id,
            len(current_goal.depends_on),
            len(dependency_entries),
        )
        
        # Step 3: Current goal retrieval
        retrieval_module = self._context.get_retrieval_module()
        
        current_entries = retrieval_module.retrieve_by_goal_relevance(
            goal_id=goal_id,
            execution_context={"retrieval_type": "current_goal"},
            limit=10,
        )
        
        current_entries_formatted = [
            ContextEntry(
                source=entry.source,
                content=entry.content,
                metadata={
                    "goal_id": goal_id,
                    "goal_text": current_goal.description,
                    "goal_priority": current_goal.priority,
                    "dependency_relation": "current",
                },
            )
            for entry in current_entries
        ]
        
        # Step 4: Previous goal summaries
        previous_summaries = self._goal_context_manager.get_plan_context(limit=5)
        
        previous_entries = [
            ContextEntry(
                source="goal_history",
                content=summary,
                metadata={"dependency_relation": "previous_goal"},
            )
            for summary in previous_summaries
        ]
        
        # Step 5: Combine all entries
        all_entries = dependency_entries + current_entries_formatted + previous_entries
        
        logger.info(
            "Plan context synthesis: goal %s → %d entries (%d dep + %d current + %d prev)",
            goal_id,
            len(all_entries),
            len(dependency_entries),
            len(current_entries_formatted),
            len(previous_entries),
        )
        
        return PlanContext(
            entries=all_entries,
            metadata={
                "goal_id": goal_id,
                "goal_priority": current_goal.priority,
                "goal_dependencies": current_goal.depends_on,
                "dependency_entries": len(dependency_entries),
                "current_entries": len(current_entries_formatted),
                "previous_entries": len(previous_entries),
            },
        )
```

---

## Integration Points

### AgentLoop.run_with_progress() Goal Pull

```python
# AgentLoop initialization
async def run_with_progress(...):
    # PULL: AgentLoop queries GoalEngine
    goal_engine = config.resolve_goal_engine()
    current_goal = goal_engine.get_next_ready_goal()
    
    if not current_goal:
        logger.info("No goals ready")
        return None
    
    # AgentLoop owns execution
    state = LoopState(
        current_goal_id=current_goal.id,
        goal_text=current_goal.description,
        thread_id=...,
    )
    
    # Execute Layer 2 loop
    plan_result = await self.run_iteration(state)
    
    # REPORT: AgentLoop reports to GoalEngine
    if plan_result.status == "done":
        goal_engine.complete_goal(current_goal.id, plan_result)
    
    return plan_result
```

### Plan Phase GoalContext Integration

```python
# AgentLoop run_iteration() - GoalContext construction
async def run_iteration(state: LoopState) -> PlanResult:
    # PULL #1: Get goal state
    goal_engine = self.config.resolve_goal_engine()
    current_goal = goal_engine.get_goal(state.current_goal_id)
    
    # CONSTRUCT: Dependency-aware PlanContext
    context_constructor = GoalContextConstructor(
        goal_engine=goal_engine,
        context_protocol=self.config.resolve_context_protocol(),
        goal_context_manager=GoalContextManager(...),
        config=self._config.goal_context,
    )
    
    plan_context = context_constructor.construct_plan_context(
        goal_id=state.current_goal_id,
    )
    
    # PLAN: LLM reasoning with dependency-aware context
    plan_result = await self.plan_phase.plan(
        goal=state.goal_text,
        state=state,
        context=plan_context,
    )
```

---

## Testing Requirements

### Integration Tests

1. **Goal Pull Architecture**:
   - `get_next_ready_goal()` returns DAG-satisfied goal
   - `complete_goal()` marks goal completed
   - `fail_goal()` applies backoff reasoning

2. **Dual Trigger Ordering**:
   - PULL #1 aborts iteration if goal status ≠ "active"
   - REACTIVE #1 calls complete_goal() after success
   - REACTIVE #2 calls fail_goal() after failure
   - PULL #2 detects goal "pending" after backoff

3. **EvidenceBundleBuilder**:
   - Wave metrics extracted from LoopState §236-245
   - Narrative synthesized from PlanResult fields
   - EvidenceBundle matches RFC-200 contract

4. **GoalContextConstructor**:
   - Dependency goals retrieved (5 entries per dependency)
   - Current goal retrieved (10 entries)
   - Previous goals included (5 summaries)
   - Entry metadata includes goal_priority, dependency_relation

---

## References

- Design Draft: `docs/drafts/2026-04-18-agentloop-goalengine-handoff-refinement-design.md`
- RFC-200: Autonomous Goal Management
- RFC-201: AgentLoop Plan-Execute Loop
- RFC-609: Goal Context Management

---

*Implementation guide for AgentLoop ↔ GoalEngine handoff architecture refinements.*
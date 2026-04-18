---
title: IG-189 Architecture Refinement from Brainstorming Session
status: draft
created: 2026-04-18
last_updated: 2026-04-18
author: Xiaming Chen
related_rfc: [RFC-000, RFC-001, RFC-200, RFC-201, RFC-202, RFC-203, RFC-609]
tags: [architecture, brainstorming, refinement, goal-engine, context-management]
---

# IG-189: Architecture Refinement from Brainstorming Session

## Overview

This implementation guide documents architecture refinements derived from the brainstorming session conducted on 2026-04-17. The session explored unified architecture for long-running autonomous agents through First Principles Thinking, Morphological Analysis, Cross-Pollination, and Emergent Thinking techniques.

**Key Discovery**: The existing RFC architecture already implements most brainstorming concepts through different naming and composition. These refinements enhance existing RFCs rather than replacing the architecture.

## Background

### Brainstorming Session Summary

**Session Topic**: Designing unified architecture for Soothe long-running autonomous agents with GoalEngine-driven execution and AgentLoop orchestration

**Goals**:
- Novel middleware patterns
- Goal decomposition strategies
- Evidence flow architectures
- Unified context management model
- Architectural isolation between AgentLoop and CoreAgent

**Techniques Used**:
1. First Principles Thinking (completed)
2. Morphological Analysis (partial)
3. Cross-Pollination (partial)
4. Emergent Thinking (completed)

**Key Output**: 35 architectural insight categories identifying fundamental truths about long-running autonomous agent execution.

### Critical Realization

After reading RFC-000, RFC-001, RFC-200, RFC-201, RFC-202, RFC-203, RFC-609, the existing architecture already implements most brainstorming goals:

1. **AgentLoop** = Layer 2 Plan → Execute Loop (not consciousness + coordinator)
   - RFC-201: AgentLoop runs Plan → Execute iterations for single goals
   - AgentLoop.executor coordinates CoreAgent threads via Layer 1 integration

2. **GoalEngine** = Layer 3 Goal Lifecycle Manager
   - RFC-200: GoalEngine owns Goal DAG and status
   - GoalDirective enables dynamic goal restructuring (backoff equivalent)

3. **ContextProtocol** = "Consciousness" Equivalent
   - RFC-001: ContextProtocol is unbounded, append-only knowledge ledger
   - Persists across threads via DurabilityProtocol
   - Projects bounded views for LLM (matches brainstorming "consciousness" concept)

4. **GoalContextManager** = Goal Context Integration (RFC-609 NEW)
   - get_plan_context(): Previous goal summaries for Plan phase
   - get_execute_briefing(): Goal briefing on thread switch

## Architecture Refinement Proposals

### Proposal #1: GoalBackoffReasoner - LLM-Driven Backoff Reasoning

**Brainstorming Source**: Category #8, #16, #88

**Current State**: RFC-200 GoalEngine has GoalDirective for restructuring, but lacks explicit LLM-driven "backoff" reasoning. Current retry logic is hardcoded.

**Problem**: Goal DAG failure should trigger LLM reasoning-based backoff, not algorithmic backtracking. GoalEngine needs to consider entire execution history to decide optimal backoff point.

**Proposed Enhancement**:

```python
class GoalBackoffReasoner:
    """LLM-driven backoff reasoning for GoalEngine.

    When goal execution fails, this module analyzes full goal context
    (all goals + dependencies + evidence) and decides WHERE to backoff
    in goal DAG using LLM reasoning, not hardcoded retry rules.

    This implements brainstorming Category #8: GoalEngine LLM-Driven
    Backoff Reasoning.
    """

    async def reason_backoff(
        self,
        goal_id: str,
        goal_context: GoalContext,
        execution_history: list[ExecutionEvidence],
    ) -> BackoffDecision:
        """Analyze goal context and execution history to determine backoff point.

        Args:
            goal_id: Failed goal identifier.
            goal_context: Full goal context including dependencies and evidence.
            execution_history: Complete execution history for reasoning.

        Returns:
            BackoffDecision specifying:
            - backoff_to: Goal node ID to backoff to
            - reason: Natural language reasoning for decision
            - new_directives: GoalDirective list for restructuring

        Raises:
            ValueError: If goal_id not found in goal_context.
        """
        pass
```

**Evidence Structure** (Category #14):

GoalEngine backoff evidence has dual structure:
- **Structured**: Goal subDAG execution status (hierarchical DAG with node-level annotations)
- **Unstructured**: Natural language fail reason + gap analysis

```python
class GoalSubDAGStatus:
    """Hierarchical status structure for goal subDAG execution."""

    dag_structure: DAG[GoalNode]
    execution_states: dict[GoalNodeID, ExecutionState]
    backoff_points: set[GoalNodeID]
    evidence_annotations: dict[GoalNodeID, EvidenceBundle]


class ExecutionState:
    """Execution state annotation for each goal node."""

    status: str  # pending|running|success|failed|backoff_pending
    thread_ids: list[str]
    timestamps: dict[str, datetime]


class EvidenceBundle:
    """Dual evidence structure per brainstorming Category #14."""

    structured: SubDAGExecutionMetrics
    unstructured: dict[str, str]  # {fail_reason, gap_analysis}
```

**Integration Point**: GoalEngine calls `BackoffReasoner.reason_backoff()` when goal execution fails (replaces hardcoded retry logic).

**Impact on RFCs**:
- RFC-200: Add GoalBackoffReasoner module to GoalEngine architecture
- RFC-201: Executor sends backoff evidence to GoalEngine on failure

### Proposal #2: ContextRetrievalModule - Self-Contained Retrieval

**Brainstorming Source**: Category #13, #15, #16

**Current State**: RFC-001 ContextProtocol has ingest/project, but lacks brainstorming's "self-contained retrieval module with stable API".

**Problem**: AgentLoop requires goal-centric retrieval (not query-centric) to determine relevant history based on goal relationship. Retrieval should be a first-class architectural module, not just a utility function.

**Proposed Enhancement**:

```python
class ContextRetrievalModule:
    """Self-contained retrieval module for ContextProtocol.

    Provides stable API for goal-centric retrieval, enabling algorithm
    evolution without breaking integration contracts. This implements
    brainstorming Category #13: Self-Contained Retrieval Module Architecture.

    Stable API contract (Category #16): retrieve_by_goal_relevance()
    with goal-centric retrieval dimension.
    """

    def retrieve_by_goal_relevance(
        self,
        goal_id: str,
        execution_context: dict,
        limit: int = 10,
    ) -> list[ContextEntry]:
        """Retrieve context entries relevant to specific goal.

        Goal-centric retrieval (not query-centric). Relevance determined
        by goal relationship to history, not keyword similarity.

        Args:
            goal_id: Goal identifier for relevance matching.
            execution_context: Current execution context for filtering.
            limit: Maximum entries to return.

        Returns:
            List of ContextEntry objects ordered by goal relevance.
        """
        pass

    def retrieve_by_thread_similarity(
        self,
        thread_id: str,
        goal_similarity_threshold: float = 0.7,
    ) -> list[ContextEntry]:
        """Retrieve entries from threads with similar goals.

        Implements brainstorming Category #20: Goal Similarity Threading
        Algorithm. Thread relationship determined by goal similarity
        metrics: exact match, semantic similarity, dependency relationship.

        Args:
            thread_id: Source thread for similarity matching.
            goal_similarity_threshold: Minimum similarity score (0.0-1.0).

        Returns:
            List of ContextEntry from similar goal threads.
        """
        pass
```

**Integration Point**: ContextProtocol delegates retrieval to RetrievalModule, preserving ingest/project interface.

**Impact on RFCs**:
- RFC-001: Add ContextRetrievalModule to ContextProtocol architecture
- RFC-609: GoalContextManager uses RetrievalModule for context queries

### Proposal #3: ThreadRelationshipModule - Thread Similarity Analysis

**Brainstorming Source**: Category #20, #23

**Current State**: RFC-609 GoalContextManager exists, but lacks explicit thread relationship module.

**Problem**: Thread relationship fundamentally based on goal similarity hierarchy (exact > semantic > dependency). Goal context includes thread ecosystem, not just current goal execution memory.

**Proposed Enhancement**:

```python
class ThreadRelationshipModule:
    """Thread relationship analysis for goal context.

    Implements brainstorming Category #20: Goal Similarity Threading
    Algorithm. Thread clustering by goal relationship strength.

    Goal similarity hierarchy:
    1. Exact match: Same goal_id, multiple execution threads
    2. Semantic similarity: Goals with similar intent/pattern (embedding)
    3. Dependency relationship: Goals in same DAG path
    """

    def compute_similarity(self, goal_a: Goal, goal_b: Goal) -> float:
        """Compute goal similarity score.

        Implements brainstorming Category #23: Embedding-Based Goal
        Similarity. Embedding distance determines goal similarity.

        Args:
            goal_a: First goal for comparison.
            goal_b: Second goal for comparison.

        Returns:
            Similarity score (0.0-1.0):
            - 1.0: Exact match (same goal_id)
            - 0.7-0.9: Semantic similarity (embedding distance)
            - 0.3-0.6: Dependency relationship (same DAG path)
            - 0.0-0.2: No relationship
        """
        pass

    def construct_goal_context(
        self,
        goal_id: str,
        options: ContextConstructionOptions,
    ) -> GoalContext:
        """Construct comprehensive goal context including thread ecosystem.

        Implements brainstorming Category #17, #19: Goal Context Construction
        Module Architecture. Context is assembled based on policy, not just
        retrieved based on query.

        Args:
            goal_id: Target goal identifier.
            options: Context construction options:
                - include_same_goal_threads: bool
                - include_similar_goals: bool
                - thread_selection_strategy: Strategy (latest, all, best-performing)

        Returns:
            GoalContext containing:
            - Goal execution memory
            - Thread ecosystem (related threads)
            - Goal superset concept (Category #15)
        """
        pass


class ContextConstructionOptions:
    """Configurable context construction strategy (Category #22)."""

    include_same_goal_threads: bool = True
    include_similar_goals: bool = True
    thread_selection_strategy: str = "latest"  # latest, all, best-performing
    similarity_threshold: float = 0.7
```

**Integration Point**: GoalContextManager uses ThreadRelationshipModule for context construction.

**Impact on RFCs**:
- RFC-609: Add ThreadRelationshipModule to GoalContextManager architecture
- RFC-001: ContextProtocol provides goal/thread metadata for similarity computation

### Proposal #4: Dual Persistence Architecture Confirmed

**Brainstorming Source**: Category #25, #26

**Current State**: RFC-001 + RFC-202 already implement brainstorming's dual persistence architecture.

**Architecture Mapping**:
- **AgentLoop persistence**: DurabilityProtocol + ContextProtocol persistence
- **CoreAgent persistence**: langchain checkpointer (RFC-100)

**Key Insight**: This brainstorming discovery confirms existing architecture is correct. Durability is a first-class architectural requirement for consciousness persistence across system lifecycle.

**Impact on RFCs**: **NO CHANGE NEEDED** - Architecture already matches brainstorming discovery.

### Proposal #5: Direct Task Provisioning Alternative (Analysis Only)

**Brainstorming Source**: Category #9, #12

**Current State**: RFC-201 Executor uses config injection for CoreAgent (middleware pattern).

**Alternative Identified**: Brainstorming proposed "direct task packaging" as alternative to middleware injection:

```python
# Current approach (config injection - RFC-201)
config = {
    "configurable": {
        "thread_id": tid,
        "soothe_step_tools": step.tools,  # Middleware injection pattern
        "soothe_step_subagent": step.subagent,
        "soothe_step_expected_output": step.expected_output,
    }
}

# Brainstorming alternative: Direct task packaging
task_package = TaskPackage(
    goal_context=goal_context_manager.get_execute_briefing(),
    execution_history=retrieval_module.retrieve_by_goal_relevance(goal_id),
    backoff_evidence=goal_engine.get_backoff_evidence(goal_id),
    step=step,
)
# Direct send to CoreAgent without middleware
```

**Decision**: Keep current config injection approach (it's working, matches RFC-201). However, enhance it with RFC-609 GoalContextManager integration, which already implements brainstorming's goal context injection concept.

**Impact on RFCs**:
- RFC-201: No architectural change, but integrate GoalContextManager for context injection
- RFC-609: Provides get_execute_briefing() for context package

### Proposal #6: AgentLoop Architecture Clarification

**Brainstorming Source**: Category #24, #28, #72

**Brainstorming Proposal**: Split AgentLoop into Consciousness + Coordination submodules.

**RFC Reality**: Existing architecture has different separation:
- **AgentLoop**: Layer 2 loop runner (Plan → Execute)
- **ContextProtocol**: "Consciousness" (knowledge ledger) - separate protocol
- **Executor**: Coordination (thread management) - component of AgentLoop

**Refinement Principle**: Keep protocols separate (ContextProtocol as protocol), AgentLoop as Layer 2 runner, don't merge consciousness into AgentLoop. AgentLoop mediates all component interactions (Category #24: Control Flow Hierarchy), but consciousness is ContextProtocol, not AgentLoop submodule.

**Impact on RFCs**: **NO CHANGE NEEDED** - Existing architecture separation is correct. This clarification prevents misinterpretation of brainstorming concepts.

## Architectural Principles Confirmed

The brainstorming session validated several architectural principles from RFC-000:

1. **Protocol-first, runtime-second** - Every module is a protocol; implementations are swappable
2. **Unbounded context, bounded projection** - ContextProtocol is unlimited; projections are bounded
3. **Durable by default** - Agent state is persistable and resumable (dual persistence confirmed)
4. **Plan-driven execution** - AgentLoop runs Plan → Execute iterations (Layer 2)
5. **Goal lifecycle management** - GoalEngine owns Goal DAG and status (Layer 3)
6. **Goal-centric retrieval** - Retrieval dimension is goal relationship, not query similarity

## Implementation Strategy

### Phase 1: GoalBackoffReasoner (Priority: High)

**Rationale**: GoalEngine backoff reasoning is core to autonomous goal evolution. Implementing this enables LLM-driven goal restructuring based on execution evidence.

**Steps**:
1. Create `cognition/goal_engine/backoff_reasoner.py`
2. Define `GoalBackoffReasoner` protocol
3. Implement LLM-based reasoning logic
4. Define `GoalSubDAGStatus` hierarchical structure
5. Integrate with GoalEngine failure handling
6. Add backoff evidence collection in Executor

**Dependencies**: RFC-200 (GoalEngine), RFC-201 (Executor), GoalContext RFC-609

### Phase 2: ContextRetrievalModule (Priority: High)

**Rationale**: Goal-centric retrieval is fundamental to AgentLoop context management. Self-contained module with stable API enables algorithm evolution.

**Steps**:
1. Create `backends/context/retrieval_module.py`
2. Define `ContextRetrievalModule` protocol
3. Implement goal-centric retrieval algorithm
4. Add thread similarity retrieval method
5. Integrate with ContextProtocol
6. Update GoalContextManager to use RetrievalModule

**Dependencies**: RFC-001 (ContextProtocol), RFC-609 (GoalContextManager)

### Phase 3: ThreadRelationshipModule (Priority: Medium)

**Rationale**: Thread relationship analysis enhances goal context construction with thread ecosystem awareness.

**Steps**:
1. Create `cognition/goal_engine/thread_relationship.py`
2. Define `ThreadRelationshipModule` protocol
3. Implement goal similarity computation (embedding-based)
4. Implement context construction with policy options
5. Integrate with GoalContextManager
6. Add thread clustering visualization

**Dependencies**: RFC-609 (GoalContextManager), RFC-001 (ContextProtocol), embedding model support

### Phase 4: Integration Testing (Priority: High)

**Rationale**: New modules must integrate with existing RFC architecture without breaking contracts.

**Steps**:
1. Create integration tests for GoalBackoffReasoner + GoalEngine
2. Create integration tests for ContextRetrievalModule + ContextProtocol
3. Create integration tests for ThreadRelationshipModule + GoalContextManager
4. Verify end-to-end AgentLoop execution with new modules
5. Verify durability persistence with new modules
6. Run full verification suite: `./scripts/verify_finally.sh`

**Dependencies**: All phases 1-3 completed

## Testing Strategy

### Unit Tests

Each new module requires comprehensive unit tests:

1. **GoalBackoffReasoner tests**:
   - Backoff reasoning with various goal contexts
   - Evidence bundle handling (structured + unstructured)
   - BackoffDecision generation correctness
   - LLM reasoning mock testing

2. **ContextRetrievalModule tests**:
   - Goal-centric retrieval accuracy
   - Thread similarity retrieval correctness
   - Retrieval algorithm edge cases
   - API contract stability tests

3. **ThreadRelationshipModule tests**:
   - Goal similarity computation (exact, semantic, dependency)
   - Context construction with various options
   - Thread clustering correctness
   - Embedding-based similarity accuracy

### Integration Tests

Test module integration with existing RFC architecture:

1. GoalBackoffReasoner + GoalEngine failure handling
2. ContextRetrievalModule + ContextProtocol ingest/project
3. ThreadRelationshipModule + GoalContextManager context flow
4. AgentLoop execution with all new modules
5. Durability persistence with new module state

### End-to-End Tests

Verify complete autonomous agent execution:

1. Goal decomposition with backoff reasoning
2. Context management with goal-centric retrieval
3. Thread coordination with similarity awareness
4. Durability persistence across restarts
5. Long-running autonomous execution (24/7 test)

## Documentation Requirements

### RFC Updates

Update existing RFCs with refinement proposals:

1. **RFC-200**: Add GoalBackoffReasoner architecture section
2. **RFC-001**: Add ContextRetrievalModule architecture section
3. **RFC-609**: Add ThreadRelationshipModule architecture section
4. **RFC-201**: Document GoalContextManager integration

### Architecture Diagrams

Create architecture diagrams showing:

1. GoalBackoffReasoner flow (goal failure → reasoning → restructuring)
2. ContextRetrievalModule API contract (goal-centric retrieval)
3. ThreadRelationshipModule similarity hierarchy
4. Dual persistence architecture (confirmed)
5. AgentLoop control flow hierarchy (mediator role)

### Implementation Guide Updates

Update existing implementation guides:

1. IG-188: Add ThreadRelationshipModule reference (already documented)
2. IG-189: This guide (architecture refinement from brainstorming)
3. Future IGs: Document implementation phases 1-3

## Success Criteria

### Functional Criteria

1. GoalEngine backoff decisions use LLM reasoning (not hardcoded rules)
2. Context retrieval is goal-centric (not query-centric)
3. Thread relationship computed via goal similarity (exact > semantic > dependency)
4. All existing tests continue to pass (backward compatibility)
5. New modules integrate without breaking RFC contracts

### Performance Criteria

1. GoalBackoffReasoner: <5 seconds for reasoning decision
2. ContextRetrievalModule: <1 second for goal-centric retrieval
3. ThreadRelationshipModule: <2 seconds for similarity computation
4. No degradation in AgentLoop iteration latency

### Architectural Criteria

1. Modules are self-contained with stable APIs
2. Protocols remain separate (no merging)
3. Durability architecture unchanged (dual persistence)
4. AgentLoop remains Layer 2 runner (not merged with consciousness)
5. GoalEngine ownership principle maintained (owns goal status)

## Risks and Mitigation

### Risk #1: LLM Reasoning Latency

**Risk**: GoalBackoffReasoner LLM calls may introduce latency in goal failure handling.

**Mitigation**:
- Use fast LLM model (Claude Haiku) for backoff reasoning
- Cache reasoning results for similar failure patterns
- Timeout with fallback to simple backoff rules

### Risk #2: Embedding Model Accuracy

**Risk**: Goal similarity computation depends on embedding model accuracy.

**Mitigation**:
- Use high-quality embedding model (OpenAI text-embedding-3-small)
- Combine embedding similarity with metadata filtering
- Provide manual override for similarity threshold

### Risk #3: Module Integration Complexity

**Risk**: Three new modules may introduce integration complexity.

**Mitigation**:
- Phase implementation (one module at a time)
- Comprehensive integration tests per phase
- Maintain backward compatibility with existing APIs
- Use stable API contracts with versioning

### Risk #4: Context Retrieval Algorithm Evolution

**Risk**: Retrieval algorithm may need frequent updates, risking API breakage.

**Mitigation**:
- Self-contained module with stable API contract
- Algorithm changes happen inside module, API remains stable
- Version API if breaking changes unavoidable
- Deprecation policy for old API versions

## Timeline

### Week 1-2: Phase 1 (GoalBackoffReasoner)

- Design protocol and implementation
- Create evidence bundle structure
- Integrate with GoalEngine
- Unit tests and integration tests

### Week 3-4: Phase 2 (ContextRetrievalModule)

- Design protocol and implementation
- Implement goal-centric retrieval
- Integrate with ContextProtocol
- Unit tests and integration tests

### Week 5-6: Phase 3 (ThreadRelationshipModule)

- Design protocol and implementation
- Implement similarity computation
- Integrate with GoalContextManager
- Unit tests and integration tests

### Week 7: Phase 4 (Integration Testing)

- End-to-end integration tests
- Verification suite run
- Documentation updates
- RFC updates

### Week 8: Review and Refinement

- Architecture review
- Performance testing
- Edge case handling
- Final documentation

## Conclusion

This implementation guide documents architecture refinements derived from brainstorming session insights. The key discovery is that existing RFC architecture already implements most brainstorming concepts through different naming and composition.

The refinement proposals enhance existing RFCs rather than replacing architecture:

1. **GoalBackoffReasoner**: LLM-driven backoff reasoning (enhancement to RFC-200)
2. **ContextRetrievalModule**: Self-contained retrieval (enhancement to RFC-001)
3. **ThreadRelationshipModule**: Thread similarity analysis (enhancement to RFC-609)
4. **Dual Persistence**: Confirmed existing architecture (no change)
5. **Direct Provisioning**: Alternative analysis only (keep current approach)
6. **AgentLoop Clarification**: Existing separation is correct (no change)

These refinements enable more sophisticated autonomous agent behavior while maintaining architectural alignment with RFC principles and langchain ecosystem compatibility.

## References

- Brainstorming Session: `_bmad-output/brainstorming/brainstorming-session-2026-04-17-144552.md`
- RFC-000: System Conceptual Design
- RFC-001: Core Modules Architecture
- RFC-200: Agentic Goal Execution
- RFC-201: Layer 2 AgentLoop Implementation
- RFC-202: Durability Protocol
- RFC-609: Goal Context Management

## Appendix: Brainstorming Categories Reference

Key brainstorming categories informing refinements:

- **Category #8**: GoalEngine LLM-Driven Backoff Reasoning
- **Category #13**: Self-Contained Retrieval Module Architecture
- **Category #14**: GoalEngine Backoff Evidence Dual Structure
- **Category #15**: Goal Context as Superset Concept
- **Category #16**: Retrieval Module API Contract
- **Category #17**: Goal Context Construction Module Architecture
- **Category #19**: Context Construction Module API Contract
- **Category #20**: Goal Similarity Threading Algorithm
- **Category #22**: Configurable Context Construction Strategy
- **Category #23**: Embedding-Based Goal Similarity
- **Category #24**: AgentLoop Control Flow Hierarchy
- **Category #25**: Durability Architecture Requirement
- **Category #26**: Dual Persistence Architecture
- **Category #28**: Consciousness-Based Coordination Submodule Architecture

Full brainstorming output available in session file.
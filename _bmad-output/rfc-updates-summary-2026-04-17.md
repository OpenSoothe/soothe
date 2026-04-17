# RFC Updates Summary - Architecture Refinement (2026-04-17)

## Overview

Updated 3 RFCs based on IG-184 architecture refinement proposals derived from brainstorming session (2026-04-17-144552). Updates enhance existing architecture without replacing fundamental design.

---

## RFC-200: Layer 3 - Autonomous Goal Management

**File**: `docs/specs/RFC-200-autonomous-goal-management.md`
**Status**: Revised → Updated (2026-04-17)

### Changes Added

**New Section 2: GoalBackoffReasoner**

Added complete specification for LLM-driven backoff reasoning:

1. **BackoffDecision Model**:
   - `backoff_to_goal_id`: Target goal for backoff
   - `reason`: Natural language reasoning
   - `new_directives`: Additional directives after backoff
   - `evidence_summary`: Why current goal path failed

2. **GoalBackoffReasoner Interface**:
   - `__init__(config)`: Initialize with reasoning model
   - `reason_backoff(goal_id, goal_context, failed_evidence)`: LLM analysis
   - Returns BackoffDecision with optimal backoff point

3. **Integration with GoalEngine**:
   - GoalEngine.__init__() initializes backoff_reasoner
   - GoalEngine.fail_goal() calls backoff_reasoner instead of hardcoded retry
   - _apply_backoff_decision() applies reasoning results

4. **Configuration**:
   ```yaml
   autonomous:
     goal_backoff:
       enabled: true
       llm_role: reason
       max_backoff_depth: 3
   ```

### Section Renumbering

- Section 2: GoalBackoffReasoner (NEW)
- Section 3: Dynamic Goal Management (previously Section 2)
- Section 4: Safety Mechanisms (previously Section 3)
- Section 5: DAG Consistency Handling (previously Section 4)
- Section 6: IterationRecord (previously Section 5)
- Section 7: Goal Management Tools (previously Section 6)

---

## RFC-001: Core Modules Architecture

**File**: `docs/specs/RFC-001-core-modules-architecture.md`
**Status**: Implemented → Updated (2026-04-17)

### Changes Added

**New Subsection: ContextRetrievalModule**

Added self-contained retrieval module specification after Module 1 Design Principles:

1. **Module Interface**:
   - `__init__(embedding_model)`: Initialize with embeddings
   - `retrieve_by_goal_relevance(goal_id, execution_context, limit)`: Goal-centric retrieval
   - Stable API enables algorithm evolution

2. **Algorithm Versions**:
   - `v1_keyword`: Goal tag matching (current)
   - `v2_embedding`: Semantic similarity (future)
   - `hybrid`: Combined approach (future)

3. **Integration with ContextProtocol**:
   - KeywordContext.__init__() initializes retrieval_module
   - `get_retrieval_module()`: Expose module for goal-centric operations
   - AgentLoop uses module for goal-relevant history

4. **Usage Pattern**:
   ```python
   context = self._context.get_retrieval_module()
   relevant_history = context.retrieve_by_goal_relevance(
       goal_id=state.current_goal_id,
       execution_context={"iteration": state.iteration},
       limit=10,
   )
   ```

5. **Design Principle**: Separate retrieval from ContextProtocol interface, stable API enables evolution.

---

## RFC-609: Goal Context Management for AgentLoop

**File**: `docs/specs/RFC-609-goal-context-management.md`
**Status**: Draft → Updated (2026-04-17)

### Changes Added

**New Module: ThreadRelationshipModule**

Added thread relationship analysis module specification:

1. **Module Structure Update**:
   - Added `thread_relationship.py` to module list

2. **ContextConstructionOptions Model**:
   - `include_same_goal_threads`: Multiple threads for same goal_id
   - `include_similar_goals`: Semantically similar goals
   - `thread_selection_strategy`: latest/all/best_performing
   - `similarity_threshold`: Embedding threshold

3. **ThreadRelationshipModule Interface**:
   - `compute_similarity(goal_a, goal_b)`: Goal similarity scoring
   - `construct_goal_context(goal_id, goal_history, options)`: Context construction

4. **Similarity Hierarchy**:
   - Exact match: 1.0 (same goal_id)
   - Semantic: embedding distance
   - Dependency: same DAG chain

5. **Context Construction Strategies**:
   - `latest`: Most recent thread
   - `all`: All matching threads
   - `best_performing`: Best metrics

6. **Integration with GoalContextManager**:
   - GoalContextManager.__init__() accepts embedding_model parameter
   - Initializes ThreadRelationshipModule
   - get_execute_briefing() uses module for context construction

7. **Configuration Extension**:
   ```yaml
   agentic:
     goal_context:
       include_similar_goals: true
       thread_selection_strategy: latest
       similarity_threshold: 0.7
       embedding_role: embedding
   ```

---

## Architectural Principles Preserved

All updates preserve core architectural principles:

1. **Protocol-runner separation**: ContextProtocol stays as protocol, AgentLoop stays as Layer 2 runner
2. **Layer 3-2-1 hierarchy**: GoalEngine (Layer 3) → AgentLoop (Layer 2) → CoreAgent (Layer 1) preserved
3. **Dual persistence**: DurabilityProtocol + langchain checkpointer unchanged
4. **Config injection**: RFC-201 executor mechanism preserved (GoalContextManager integrates via config)

---

## Implementation Status

| Proposal | RFC Updated | Implementation Status |
|----------|-------------|----------------------|
| #1 GoalBackoffReasoner | RFC-200 ✅ | Specification complete, awaiting implementation |
| #2 ContextRetrievalModule | RFC-001 ✅ | Specification complete, awaiting implementation |
| #3 ThreadRelationshipModule | RFC-609 ✅ | Specification complete, awaiting implementation |
| #4 Dual Persistence | RFC-001, RFC-202 ✅ | No changes needed (architecture verified) |
| #5 Direct Provisioning | RFC-201 ✅ | No changes needed (keep config injection) |
| #6 Submodule Architecture | RFC-000, RFC-001 ✅ | No changes needed (protocol-runner separation confirmed) |

---

## Next Actions

1. **Begin Phase 1 Implementation**: GoalBackoffReasoner (IG-184, Proposal #1)
   - Duration: 2-3 days
   - Priority: High
   - File: `cognition/goal_engine/backoff_reasoner.py`

2. **Begin Phase 2 Implementation**: ContextRetrievalModule (IG-184, Proposal #2)
   - Duration: 2-3 days
   - Priority: Medium
   - File: `protocols/context/retrieval.py`

3. **Begin Phase 3 Implementation**: ThreadRelationshipModule (IG-184, Proposal #3)
   - Duration: 3-4 days
   - Priority: Medium
   - File: `cognition/goal_context/thread_relationship.py`

---

## References

- **Brainstorming Session**: `_bmad-output/brainstorming/brainstorming-session-2026-04-17-144552.md`
- **Implementation Guide**: `docs/impl/IG-184-architecture-refinement-proposals.md`
- **RFC-200**: `docs/specs/RFC-200-autonomous-goal-management.md` (updated)
- **RFC-001**: `docs/specs/RFC-001-core-modules-architecture.md` (updated)
- **RFC-609**: `docs/specs/RFC-609-goal-context-management.md` (updated)

---

## Verification

All RFC updates validated against:
- Original brainstorming insights (35 categories)
- IG-184 implementation guide specifications
- Existing architectural principles (RFC-000)
- Layer hierarchy integrity (RFC-200, RFC-201, RFC-100)

**Architecture refinement complete**: 3 RFCs updated, 3 proposals documented, 6 architectural decisions finalized.
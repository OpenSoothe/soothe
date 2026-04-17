# IG-184: Architecture Refinement Proposals from Brainstorming Session

**IG Number**: IG-184
**Title**: Architecture Refinement Propals for Unified Long-Running Agent Architecture
**Status**: Draft
**Created**: 2026-04-17
**Dependencies**: RFC-000, RFC-001, RFC-200, RFC-200, RFC-200, RFC-609
**Related**: Brainstorming Session 2026-04-17-144552

---

## Overview

This implementation guide documents 6 architectural refinement proposals derived from a brainstorming session (2026-04-17) that generated 35 architectural insights across First Principles Thinking, Morphological Analysis, Cross-Pollination, and Emergent Thinking techniques.

The proposals enhance existing RFC architecture rather than replacing it, based on the discovery that Soothe's current architecture already implements most brainstorming concepts through different naming/composition.

---

## Key Discovery: Existing Architecture Alignment

After comprehensive RFC review, the brainstorming session revealed:

| Brainstorming Concept | RFC Implementation | Match Status |
|----------------------|-------------------|--------------|
| AgentLoop consciousness | ContextProtocol (RFC-001) | ✅ Existing |
| GoalEngine goal evolution | GoalEngine + GoalDirective (RFC-200) | ✅ Existing |
| LLM-driven backoff reasoning | Missing | ⚠️ Needs enhancement |
| Self-contained retrieval module | Missing | ⚠️ Needs enhancement |
| Thread relationship module | Missing | ⚠️ Needs enhancement |
| Dual persistence architecture | DurabilityProtocol + langchain checkpointer (RFC-001, RFC-200) | ✅ Existing |
| Goal context integration | GoalContextManager (RFC-609) | ✅ Existing |

**Architectural Principle**: Enhance existing protocols rather than creating new architectural layers. Keep ContextProtocol as "consciousness", GoalEngine as goal manager, AgentLoop as Layer 2 runner.

---

## Proposal #1: GoalEngine Backoff Reasoner Enhancement

### Problem

RFC-200 GoalEngine has GoalDirective for dynamic restructuring, but lacks explicit LLM-driven backoff reasoning when goal DAG paths fail. Current implementation uses hardcoded retry logic without reasoning-based decision about WHERE to backoff.

### Brainstorming Foundation

From brainstorming Categories #8, #16, #31:
- **Category #8**: GoalEngine backoff determined by LLM dynamically based on full picture of current knowledge
- **Category #16**: Evidence structure is dual (structured subDAG status + unstructured natural language)
- **Category #31**: AgentLoop-GoalEngine synchronization triggered by thread completion + need-based

### Design

Add `GoalBackoffReasoner` module:

```python
# cognition/goal_engine/backoff_reasoner.py

class BackoffDecision(BaseModel):
    """LLM-driven backoff decision for goal DAG restructuring."""
    
    backoff_to_goal_id: str
    """Target goal to backoff to (where to resume in DAG)."""
    
    reason: str
    """Natural language reasoning for backoff decision."""
    
    new_directives: list[GoalDirective] = []
    """Additional directives to apply after backoff."""
    
    evidence_summary: str
    """Summary of why current goal path failed."""

class GoalBackoffReasoner:
    """LLM-driven backoff reasoning for GoalEngine."""
    
    def __init__(self, config: SootheConfig) -> None:
        self._model = config.create_chat_model("reason")
        self._prompt_template = BACKOFF_REASONING_PROMPT
    
    async def reason_backoff(
        self,
        goal_id: str,
        goal_context: GoalContext,
        failed_evidence: str,
    ) -> BackoffDecision:
        """
        LLM analyzes full goal context and decides WHERE to backoff.
        
        Args:
            goal_id: Failed goal identifier
            goal_context: Snapshot of all goals (RFC-200 GoalContext)
            failed_evidence: Evidence from Layer 2 execution
        
        Returns:
            BackoffDecision with backoff point + reasoning + directives
        """
        # Build context with GoalContext + failed evidence
        prompt = self._build_backoff_prompt(goal_id, goal_context, failed_evidence)
        
        # LLM reasoning call
        response = await self._model.ainvoke(prompt)
        
        # Parse structured BackoffDecision
        decision = BackoffDecision.model_validate_json(response.content)
        
        logger.info(
            "Backoff reasoning: goal %s → backoff to %s (%s)",
            goal_id, decision.backoff_to_goal_id, decision.reason,
        )
        
        return decision
    
    def _build_backoff_prompt(self, goal_id, goal_context, evidence) -> str:
        """Build LLM prompt with goal DAG context + evidence."""
        return self._prompt_template.format(
            goal_id=goal_id,
            goal_snapshot=self._format_goal_snapshot(goal_context),
            failed_evidence=evidence,
        )
```

### Integration

Modify GoalEngine.fail_goal() to call BackoffReasoner:

```python
# cognition/goal_engine.py (existing)

class GoalEngine:
    def __init__(self, config: SootheConfig) -> None:
        self._goals: dict[str, Goal] = {}
        self._backoff_reasoner = GoalBackoffReasoner(config)  # NEW
    
    async def fail_goal(
        self,
        goal_id: str,
        error: str,
        allow_retry: bool = True,
    ) -> None:
        """Mark goal failed with backoff reasoning."""
        goal = self._goals[goal_id]
        goal.status = "failed"
        goal.error = error
        
        if allow_retry and goal.retry_count < goal.max_retries:
            # NEW: Call backoff reasoner instead of simple retry
            goal_context = self._build_goal_context(goal_id)
            decision = await self._backoff_reasoner.reason_backoff(
                goal_id=goal_id,
                goal_context=goal_context,
                failed_evidence=error,
            )
            
            # Apply backoff decision
            self._apply_backoff_decision(decision)
            
            logger.info(
                "Goal %s failed → backoff to %s, retry %d/%d",
                goal_id, decision.backoff_to_goal_id,
                goal.retry_count, goal.max_retries,
            )
        
        goal.retry_count += 1
        goal.updated_at = datetime.now()
```

### Configuration

```yaml
# config.dev.yml

autonomous:
  goal_backoff:
    enabled: true
    llm_role: reason  # Use reasoning model for backoff decisions
    max_backoff_depth: 3  # Limit backoff chain depth
```

### Implementation Tasks

1. Create `cognition/goal_engine/backoff_reasoner.py` with GoalBackoffReasoner class
2. Add BackoffDecision model to `schemas.py`
3. Modify GoalEngine.__init__() to initialize backoff_reasoner
4. Modify GoalEngine.fail_goal() to call backoff_reasoner.reason_backoff()
5. Add _apply_backoff_decision() method to GoalEngine
6. Add configuration schema for goal_backoff settings
7. Write unit tests for backoff reasoning logic
8. Write integration tests for GoalEngine-BackoffReasoner flow

---

## Proposal #2: ContextProtocol Retrieval Module Enhancement

### Problem

RFC-001 ContextProtocol has ingest/project methods, but lacks brainstorming's "self-contained retrieval module with stable API" for goal-centric retrieval. Current project() is query-centric, not goal-centric.

### Brainstorming Foundation

From brainstorming Categories #13, #15, #16:
- **Category #13**: Self-contained retrieval module with stable APIs
- **Category #15**: Goal-centric retrieval (retrieve_by_goal_relevance)
- **Category #16**: Stable API enables algorithm evolution

### Design

Add ContextRetrievalModule as separate component:

```python
# protocols/context/retrieval.py (NEW)

class ContextRetrievalModule:
    """Self-contained retrieval module for ContextProtocol.
    
    Stable API boundary enables algorithm evolution without
    breaking ContextProtocol interface.
    """
    
    def __init__(self, embedding_model: Embeddings) -> None:
        self._embedding_model = embedding_model
        self._algorithm_version = "v1_keyword"  # Evolvable
    
    def retrieve_by_goal_relevance(
        self,
        goal_id: str,
        execution_context: dict[str, Any],
        limit: int = 10,
    ) -> list[ContextEntry]:
        """
        Goal-centric retrieval (not query-centric).
        
        Relevance determined by goal relationship to history,
        not keyword similarity.
        
        Args:
            goal_id: Target goal for relevance matching
            execution_context: Current execution state
            limit: Maximum entries to return
        
        Returns:
            ContextEntry list ranked by goal relevance
        
        Stable API: Algorithm can evolve (keyword → embedding → hybrid)
        without breaking callers.
        """
        # Current algorithm: Keyword-based goal tag matching
        if self._algorithm_version == "v1_keyword":
            return self._retrieve_by_goal_tags(goal_id, limit)
        
        # Future algorithm: Embedding-based semantic matching
        if self._algorithm_version == "v2_embedding":
            return self._retrieve_by_goal_embeddings(goal_id, limit)
        
        # Future: Hybrid approach
        return self._retrieve_hybrid(goal_id, limit)
    
    def _retrieve_by_goal_tags(self, goal_id: str, limit: int) -> list[ContextEntry]:
        """Current v1 algorithm: Goal tag matching."""
        # Implementation: Match entries with goal_id tag
        ...
    
    def _retrieve_by_goal_embeddings(self, goal_id: str, limit: int) -> list[ContextEntry]:
        """Future v2 algorithm: Semantic similarity."""
        # Implementation: Embed goal description, match entry embeddings
        ...
```

### Integration

ContextProtocol delegates retrieval to module:

```python
# protocols/context/keyword_context.py (existing)

class KeywordContext(ContextProtocol):
    def __init__(self, embedding_model: Embeddings | None = None) -> None:
        self._entries: list[ContextEntry] = []
        self._retrieval_module = ContextRetrievalModule(embedding_model)  # NEW
    
    async def project(self, query: str, token_budget: int) -> ContextProjection:
        """Existing project method (unchanged)."""
        ...
    
    # NEW: Expose retrieval module for goal-centric access
    def get_retrieval_module(self) -> ContextRetrievalModule:
        """Get retrieval module for goal-centric operations."""
        return self._retrieval_module
```

### Usage Pattern

AgentLoop uses retrieval module for goal-centric context:

```python
# cognition/agent_loop/executor.py

class Executor:
    async def execute(self, decision: AgentDecision, state: LoopState):
        # Get goal-centric context (NEW)
        context = self._context.get_retrieval_module()
        relevant_history = context.retrieve_by_goal_relevance(
            goal_id=state.current_goal_id,
            execution_context={"iteration": state.iteration},
            limit=10,
        )
        
        # Build task package with goal-centric context
        ...
```

### Configuration

```yaml
# config.dev.yml

protocols:
  context:
    retrieval:
      algorithm_version: v1_keyword  # v1_keyword | v2_embedding | hybrid
      embedding_role: embedding  # Model role for embedding-based retrieval
```

### Implementation Tasks

1. Create `protocols/context/retrieval.py` with ContextRetrievalModule class
2. Add algorithm_version configuration to SootheConfig
3. Modify KeywordContext and VectorContext to initialize retrieval_module
4. Add get_retrieval_module() method to ContextProtocol interface
5. Implement v1_keyword algorithm (goal tag matching)
6. Add placeholder for v2_embedding algorithm (future work)
7. Update executor to use retrieval_module.retrieve_by_goal_relevance()
8. Write unit tests for retrieval module algorithms
9. Write integration tests for ContextProtocol-RetrievalModule flow

---

## Proposal #3: Thread Relationship Module Enhancement

### Problem

RFC-609 GoalContextManager exists for goal context injection, but brainstorming identified need for thread relationship analysis (goal similarity, thread clustering) which is not implemented.

### Brainstorming Foundation

From brainstorming Categories #20, #23:
- **Category #20**: Thread relationship determined by goal similarity metrics (exact > semantic > dependency)
- **Category #23**: Goal similarity threading algorithm for context construction

### Design

Add ThreadRelationshipModule:

```python
# cognition/goal_context/thread_relationship.py (NEW)

class ContextConstructionOptions(BaseModel):
    """Options for goal context construction."""
    
    include_same_goal_threads: bool = True
    """Include multiple threads for same goal_id."""
    
    include_similar_goals: bool = True
    """Include threads with semantically similar goals."""
    
    thread_selection_strategy: Literal["latest", "all", "best_performing"] = "latest"
    """Strategy for selecting relevant threads."""
    
    similarity_threshold: float = 0.7
    """Embedding similarity threshold for goal matching."""

class ThreadRelationshipModule:
    """Thread relationship analysis for goal context construction."""
    
    def __init__(self, embedding_model: Embeddings) -> None:
        self._embedding_model = embedding_model
    
    def compute_similarity(self, goal_a: Goal, goal_b: Goal) -> float:
        """
        Goal similarity for thread clustering.
        
        Hierarchy (exact > semantic > dependency):
        - Exact match: 1.0 (same goal_id)
        - Semantic similarity: embedding distance
        - Dependency relationship: same DAG path
        """
        # Exact match
        if goal_a.id == goal_b.id:
            return 1.0
        
        # Semantic similarity
        emb_a = self._embedding_model.embed_query(goal_a.description)
        emb_b = self._embedding_model.embed_query(goal_b.description)
        semantic_sim = cosine_similarity(emb_a, emb_b)
        
        # Dependency relationship (same DAG path)
        # Implementation: Check if goals in same dependency chain
        
        return semantic_sim
    
    def construct_goal_context(
        self,
        goal_id: str,
        goal_history: list[GoalRecord],
        options: ContextConstructionOptions,
    ) -> GoalContext:
        """
        Context construction module.
        
        Handles:
        - Same goal multiple threads
        - Similar goal execution history
        
        Args:
            goal_id: Target goal for context
            goal_history: Previous goal records from checkpoint
            options: Construction configuration
        
        Returns:
            GoalContext with execution memory + thread ecosystem
        """
        context_goals = []
        
        # Include same goal threads
        if options.include_same_goal_threads:
            same_goal_threads = [g for g in goal_history if g.goal_id == goal_id]
            context_goals.extend(self._select_threads(same_goal_threads, options))
        
        # Include similar goals
        if options.include_similar_goals:
            current_goal = self._get_current_goal(goal_id)
            similar_goals = []
            for g in goal_history:
                if g.goal_id != goal_id:  # Exclude same goal (already included)
                    sim = self.compute_similarity(current_goal, g)
                    if sim >= options.similarity_threshold:
                        similar_goals.append((g, sim))
            
            # Sort by similarity, select top matches
            similar_goals.sort(key=lambda x: x[1], reverse=True)
            context_goals.extend([g[0] for g in similar_goals[:5]])
        
        return GoalContext(
            current_goal_id=goal_id,
            context_goals=context_goals,
        )
    
    def _select_threads(self, threads: list, options: ContextConstructionOptions) -> list:
        """Select threads based on strategy."""
        if options.thread_selection_strategy == "latest":
            return threads[-1:] if threads else []
        elif options.thread_selection_strategy == "all":
            return threads
        elif options.thread_selection_strategy == "best_performing":
            # Sort by performance metrics (duration, success rate)
            return sorted(threads, key=lambda g: g.duration_ms)[:1]
```

### Integration

GoalContextManager uses ThreadRelationshipModule:

```python
# cognition/goal_context_manager.py (RFC-609, modified)

class GoalContextManager:
    def __init__(
        self,
        state_manager: AgentLoopStateManager,
        config: GoalContextConfig,
        embedding_model: Embeddings,  # NEW parameter
    ) -> None:
        self._state_manager = state_manager
        self._config = config
        self._thread_relationship = ThreadRelationshipModule(embedding_model)  # NEW
    
    def get_plan_context(self, limit: int | None = None) -> list[str]:
        """Get previous goal summaries for Plan phase (unchanged)."""
        ...
    
    def get_execute_briefing(self, limit: int | None = None) -> str | None:
        """Get goal briefing for Execute phase (enhanced)."""
        checkpoint = self._state_manager.load()
        if not checkpoint or not checkpoint.thread_switch_pending:
            return None
        
        # NEW: Use thread relationship module for context construction
        options = ContextConstructionOptions(
            include_same_goal_threads=True,
            include_similar_goals=self._config.include_similar_goals,
            thread_selection_strategy=self._config.thread_selection_strategy,
            similarity_threshold=self._config.similarity_threshold,
        )
        
        goal_context = self._thread_relationship.construct_goal_context(
            goal_id=checkpoint.current_goal_id,
            goal_history=checkpoint.goal_history,
            options=options,
        )
        
        return self._format_execute_briefing(goal_context)
```

### Configuration

```yaml
# config.dev.yml

agentic:
  goal_context:
    include_similar_goals: true
    thread_selection_strategy: latest  # latest | all | best_performing
    similarity_threshold: 0.7
    embedding_role: embedding
```

### Implementation Tasks

1. Create `cognition/goal_context/thread_relationship.py` with ThreadRelationshipModule
2. Add ContextConstructionOptions model
3. Implement compute_similarity() with exact match + semantic similarity
4. Implement construct_goal_context() with same goal + similar goals logic
5. Modify GoalContextManager to initialize thread_relationship module
6. Modify get_execute_briefing() to use thread_relationship.construct_goal_context()
7. Add configuration schema for thread_relationship settings
8. Write unit tests for similarity computation
9. Write unit tests for context construction logic
10. Write integration tests for GoalContextManager-ThreadRelationshipModule flow

---

## Proposal #4: Dual Persistence Architecture (No Change)

### Status: Already Implemented

RFC-001 and RFC-200 already implement brainstorming's dual persistence architecture (Category #26):

| Layer | Persistence Mechanism | RFC Reference |
|-------|----------------------|---------------|
| AgentLoop | DurabilityProtocol + ContextProtocol | RFC-001 §Module 1, §Module 5 |
| CoreAgent | langchain checkpointer | RFC-100, RFC-200 §8.1 |

### Verification

Current implementation matches brainstorming discovery:

- AgentLoop execution records → ContextProtocol.persist(thread_id)
- Goal status → GoalEngine.snapshot() + RunArtifactStore.save_checkpoint()
- CoreAgent checkpoints → langgraph checkpointer (separate mechanism)

**NO ENHANCEMENT NEEDED** - Architecture already correct.

---

## Proposal #5: Direct Task Provisioning Alternative

### Problem

Brainstorming proposed "direct task provisioning" as alternative to middleware injection (Category #9, #12), but RFC-200 Executor already uses config injection (working implementation).

### Analysis

Current RFC-200 approach (config injection):
```python
config = {
    "configurable": {
        "thread_id": tid,
        "soothe_step_tools": step.tools,  # Middleware injection
        "soothe_step_subagent": step.subagent,
        "soothe_step_expected_output": step.expected_output,
    }
}
```

Brainstorming proposal (direct packaging):
```python
task_package = TaskPackage(
    goal_context=goal_context_manager.get_execute_briefing(),
    execution_history=retrieval_module.retrieve_by_goal_relevance(goal_id),
    backoff_evidence=goal_engine.get_backoff_evidence(goal_id),
    step=step,
)
```

### Decision

**Keep current config injection approach**:
- Working implementation in RFC-200
- Matches langgraph config pattern
- GoalContextManager (RFC-609) already adds goal briefing to config

**No architectural change needed** - RFC-609 enhancement provides goal context integration without replacing config injection mechanism.

---

## Proposal #6: AgentLoop Submodule Architecture Clarification

### Problem

Brainstorming proposed splitting AgentLoop into Consciousness + Coordination submodules (Category #28), but this violates RFC architectural principle: protocols are separate, AgentLoop is Layer 2 runner.

### Clarification

**Correct architectural composition**:
- **ContextProtocol** = "consciousness" (separate protocol, RFC-001)
- **AgentLoop.Executor** = coordination component (part of Layer 2 runner, RFC-200)
- **AgentLoop** = Layer 2 Plan → Execute loop runner (NOT merged with consciousness)

### Principle

Keep protocols separate from loop runners:
- ContextProtocol is protocol (knowledge ledger)
- AgentLoop is Layer 2 runner (orchestrates protocol usage)
- Executor is component (delegates to Layer 1)

**NO ARCHITECTURAL CHANGE** - Maintain protocol-runner separation.

---

## Implementation Plan

### Phase 1: Backoff Reasoner (Proposal #1)
**Priority**: High (critical for goal evolution)
**Duration**: 2-3 days
**Dependencies**: RFC-200 GoalEngine

1. Implement GoalBackoffReasoner module
2. Add BackoffDecision schema
3. Integrate with GoalEngine.fail_goal()
4. Write tests + documentation

### Phase 2: Retrieval Module (Proposal #2)
**Priority**: Medium (optimizes context projection)
**Duration**: 2-3 days
**Dependencies**: RFC-001 ContextProtocol

1. Implement ContextRetrievalModule with v1_keyword algorithm
2. Add to ContextProtocol interface
3. Update executor to use goal-centric retrieval
4. Write tests + configuration

### Phase 3: Thread Relationship (Proposal #3)
**Priority**: Medium (enhances goal context)
**Duration**: 3-4 days
**Dependencies**: RFC-609 GoalContextManager

1. Implement ThreadRelationshipModule
2. Add similarity computation
3. Enhance GoalContextManager to use thread relationship
4. Write tests + configuration

### Phase 4-6: Documentation Only
**Proposals #4, #5, #6**: Document architectural decisions, no implementation needed.

---

## Verification Requirements

### Unit Tests
- GoalBackoffReasoner.reason_backoff() LLM reasoning test
- ContextRetrievalModule.retrieve_by_goal_relevance() algorithm test
- ThreadRelationshipModule.compute_similarity() similarity metrics test
- ThreadRelationshipModule.construct_goal_context() context construction test

### Integration Tests
- GoalEngine → BackoffReasoner → GoalDirective flow
- ContextProtocol → RetrievalModule → Executor flow
- GoalContextManager → ThreadRelationshipModule → Execute briefing flow

### Architecture Verification
- Protocol-runner separation maintained (Proposal #6)
- Dual persistence unchanged (Proposal #4)
- Config injection preserved (Proposal #5)

---

## Success Criteria

1. GoalEngine has LLM-driven backoff reasoning (Proposal #1 implemented)
2. ContextProtocol has goal-centric retrieval module (Proposal #2 implemented)
3. GoalContextManager has thread relationship analysis (Proposal #3 implemented)
4. Dual persistence architecture verified unchanged (Proposal #4)
5. Config injection mechanism preserved (Proposal #5)
6. Protocol-runner separation maintained (Proposal #6)

---

## References

- Brainstorming Session: Consolidation intermediate artifact removed during cleanup (2026-04-17); key decisions are reflected in consolidated RFCs.
- RFC-000: System Conceptual Design
- RFC-001: Core Modules Architecture
- RFC-200: Layer 3 Autonomous Goal Management
- RFC-200: Layer 2 Agentic Goal Execution
- RFC-200: DAG Execution & Failure Recovery
- RFC-609: Goal Context Management for AgentLoop

---

## Conclusion

This implementation guide documents 6 architectural refinement proposals derived from comprehensive brainstorming and RFC analysis. Three proposals require implementation (#1, #2, #3), three proposals document architectural decisions without changes (#4, #5, #6).

The proposals enhance existing RFC architecture while preserving architectural principles: protocol-runner separation, Layer 2-3-1 hierarchy, and dual persistence architecture.

**Next Actions**: Begin Phase 1 implementation (GoalBackoffReasoner) after user approval.
# IG-188: Thread Relationship Module Implementation (RFC-609)

**Implementation Guide**: NNN-thread-relationship-module
**RFC**: RFC-609 (Goal Context Management)
**Status**: In Progress
**Created**: 2026-04-17
**Dependencies**: RFC-609, RFC-400 (ContextRetrievalModule), Gap Analysis

---

## Overview

Implement RFC-609 `ThreadRelationshipModule` for goal similarity computation and thread ecosystem context construction. This closes the primary gap identified in the brainstorming analysis: thread relationship awareness for goal context management.

## Gap Context

**From Brainstorming Analysis**:
- **Proposal #3**: ThreadRelationshipModule specified in RFC-609 but not implemented
- **Missing Capabilities**: Goal similarity computation, thread ecosystem context, embedding-based relevance
- **Impact**: HIGH - thread ecosystem awareness critical for multi-thread AgentLoop execution
- **Effort**: MEDIUM - 2-3 weeks implementation

## Implementation Tasks

### Task 1: Implement ThreadRelationshipModule Core

**Location**: `packages/soothe/src/soothe/cognition/agent_loop/thread_relationship.py`

**Requirements** (RFC-609 §95-156):
1. `compute_similarity()` - Goal similarity for thread clustering
2. `construct_goal_context()` - Context construction with thread ecosystem
3. Embedding integration for semantic similarity
4. Similarity hierarchy: exact > semantic > dependency

**API Contract**:
```python
class ContextConstructionOptions(BaseModel):
    """Options for goal context construction."""
    include_same_goal_threads: bool = True
    include_similar_goals: bool = True
    thread_selection_strategy: Literal["latest", "all", "best_performing"] = "latest"
    similarity_threshold: float = 0.7

class ThreadRelationshipModule:
    def __init__(self, embedding_model: Embeddings) -> None: ...
    
    def compute_similarity(self, goal_a: Goal, goal_b: Goal) -> float: ...
    
    def construct_goal_context(
        self,
        goal_id: str,
        goal_history: list[GoalExecutionRecord],
        options: ContextConstructionOptions,
    ) -> GoalContext: ...
```

---

### Task 2: Integrate with GoalContextManager

**Location**: `packages/soothe/src/soothe/cognition/agent_loop/goal_context_manager.py`

**Enhancements**:
1. Add `ThreadRelationshipModule` parameter to constructor
2. Use module in `get_execute_briefing()` for context construction
3. Replace simple goal filtering with thread-aware context construction

**Integration Point**:
```python
class GoalContextManager:
    def __init__(
        self,
        state_manager: AgentLoopStateManager,
        config: GoalContextConfig,
        embedding_model: Embeddings,  # NEW
    ) -> None:
        self._thread_relationship = ThreadRelationshipModule(embedding_model)
```

---

### Task 3: Extend Configuration

**Location**: `packages/soothe/src/soothe/config/models.py`

**Add Fields to GoalContextConfig**:
```python
class GoalContextConfig(BaseModel):
    plan_limit: int = 10
    execute_limit: int = 10
    enabled: bool = True
    
    # NEW: Thread relationship configuration
    include_similar_goals: bool = True
    thread_selection_strategy: Literal["latest", "all", "best_performing"] = "latest"
    similarity_threshold: float = 0.7
    embedding_role: str = "embedding"
```

---

### Task 4: Wire Embedding Model Integration

**Location**: `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py`

**Enhancement**: Pass embedding model to GoalContextManager:
```python
# agent_loop.py run_with_progress()
embedding_model = config.create_embedding_model()
goal_context_manager = GoalContextManager(
    state_manager, 
    config.agentic.goal_context,
    embedding_model,  # NEW
)
```

---

### Task 5: Unit Tests

**Location**: `packages/soothe/tests/unit/cognition/agent_loop/test_thread_relationship.py`

**Test Cases**:
1. `test_compute_similarity_exact_match` - Same goal_id returns 1.0
2. `test_compute_similarity_semantic` - Embedding-based similarity
3. `test_compute_similarity_dependency` - Same DAG path
4. `test_construct_goal_context_includes_same_goal_threads` - Multiple threads same goal
5. `test_construct_goal_context_includes_similar_goals` - Similar goal history
6. `test_thread_selection_strategy_latest` - Latest thread selection
7. `test_thread_selection_strategy_best_performing` - Best metrics selection

---

## Implementation Details

### Similarity Computation Algorithm

**Hierarchy** (RFC-609 §158-160):
1. **Exact Match**: `goal_a.id == goal_b.id` → score 1.0
2. **Semantic Similarity**: Embedding cosine similarity on goal descriptions
3. **Dependency Relationship**: Goals in same DAG dependency chain (requires GoalEngine integration)

**Implementation**:
```python
def compute_similarity(self, goal_a: Goal, goal_b: Goal) -> float:
    # 1. Exact match (highest priority)
    if goal_a.goal_id == goal_b.goal_id:
        return 1.0
    
    # 2. Semantic similarity (embedding-based)
    embedding_a = self._embedding_model.embed_query(goal_a.goal_text)
    embedding_b = self._embedding_model.embed_query(goal_b.goal_text)
    
    semantic_score = cosine_similarity(embedding_a, embedding_b)
    
    # 3. Dependency relationship (requires GoalEngine context, future enhancement)
    # For now, return semantic score
    
    return semantic_score
```

### Context Construction Algorithm

**Steps** (RFC-609 §136-156):
1. Filter goal_history by similarity threshold
2. Apply thread selection strategy
3. Construct GoalContext with execution memory + thread ecosystem

**Implementation**:
```python
def construct_goal_context(
    self,
    goal_id: str,
    goal_history: list[GoalExecutionRecord],
    options: ContextConstructionOptions,
) -> GoalContext:
    # 1. Find similar goals
    similar_goals = []
    for record in goal_history:
        if record.goal_id == goal_id and options.include_same_goal_threads:
            similar_goals.append(record)  # Exact match
        elif options.include_similar_goals:
            similarity = self.compute_similarity(
                Goal(goal_id=goal_id, description=...),
                Goal(goal_id=record.goal_id, description=record.goal_text),
            )
            if similarity >= options.similarity_threshold:
                similar_goals.append(record)
    
    # 2. Apply thread selection strategy
    selected_goals = self._apply_strategy(similar_goals, options.thread_selection_strategy)
    
    # 3. Construct GoalContext
    return GoalContext(
        goal_id=goal_id,
        execution_memory=selected_goals,
        thread_ecosystem=self._build_thread_ecosystem(selected_goals),
    )
```

### Thread Selection Strategies

**Latest**: Most recent thread execution (sorted by `completed_at`)

**All**: All matching threads (bounded by limit)

**Best Performing**: Thread with best metrics (lowest duration, highest success rate)

---

## Configuration Integration

**config.yml**:
```yaml
agentic:
  goal_context:
    plan_limit: 10
    execute_limit: 10
    enabled: true
    include_similar_goals: true
    thread_selection_strategy: latest
    similarity_threshold: 0.7
    embedding_role: embedding
```

---

## Verification

**Commands**:
```bash
# Run unit tests
pytest packages/soothe/tests/unit/cognition/agent_loop/test_thread_relationship.py

# Run verification script
./scripts/verify_finally.sh
```

**Success Criteria**:
1. ThreadRelationshipModule implements RFC-609 API
2. Goal similarity computation returns expected hierarchy
3. Context construction includes thread ecosystem
4. Integration with GoalContextManager works
5. Configuration extension validated
6. All tests pass (unit + integration)

---

## Migration Notes

**Backward Compatibility**:
- GoalContextConfig defaults maintain existing behavior
- `include_similar_goals=False` disables thread ecosystem context
- Existing GoalContextManager code path preserved for simple filtering

**Opt-in Behavior**:
- Thread ecosystem context requires `include_similar_goals=True`
- Embedding model integration required for semantic similarity
- Graceful fallback if embedding model unavailable

---

## References

- RFC-609: Goal Context Management
- RFC-400: ContextRetrievalModule (goal-centric retrieval)
- Gap Analysis: `docs/gap-analysis-brainstorming-to-rfc.md`
- Brainstorming Session: `_bmad-output/brainstorming/brainstorming-session-2026-04-17-144552.md`

---

**Implementation Status**: In Progress
**Next Action**: Implement ThreadRelationshipModule core (Task 1)
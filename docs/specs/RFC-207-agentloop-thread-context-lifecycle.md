# RFC-207: AgentLoop Thread Management & Goal Context

**RFC**: 207
**Title**: AgentLoop Thread Management & Goal Context
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-17
**Dependencies**: RFC-201, RFC-203, RFC-608
**Related**: RFC-213 (Reasoning)

---

## Abstract

This RFC defines AgentLoop thread lifecycle management and goal context integration, consolidating thread lifecycle (multi-thread spanning), goal context manager (previous goal injection), thread relationship module (similarity-based context), and executor thread coordination. AgentLoop threads span multiple CoreAgent executions with goal-level context bridging thread switches while maintaining architectural isolation between loop history (goals) and thread history (messages).

---

## Thread Lifecycle & Multi-Thread Spanning

### Thread Lifecycle Model

AgentLoop executions span multiple CoreAgent threads:
- **Primary thread**: User query thread (conversation history)
- **Thread switches**: Switch to new threads for health/performance reasons
- **Thread spanning**: Loop checkpoint spans multiple thread IDs

### Thread Health Metrics

```python
class ThreadHealthMetrics(BaseModel):
    """Thread health for switch decisions."""
    message_count: int = 0
    """Number of messages in thread."""
    token_count: int = 0
    """Token count in thread state."""
    context_percentage: float = 0.0
    """Context window utilization."""
    error_rate: float = 0.0
    """Error rate in recent executions."""
    last_updated: datetime

class AgentLoopCheckpoint(BaseModel):
    """AgentLoop state spanning multiple threads."""

    # Thread spanning
    thread_ids: list[str] = []
    """All thread IDs used in this loop."""
    current_thread_id: str = ""
    """Active thread for execution."""
    thread_switch_pending: bool = False
    """Flag indicating thread just switched."""
    total_thread_switches: int = 0
    """Cumulative thread switches."""
    thread_health_metrics: dict[str, ThreadHealthMetrics] = {}
    """Per-thread health tracking."""

    # Goal history (cross-thread)
    goal_history: list[GoalRecord] = []
    """Previous goal summaries across threads."""

    # Loop state
    iteration: int = 0
    total_iterations: int = 0
```

### Thread Switch Detection

**Trigger conditions**:
- Context window >80% full
- Message count >threshold
- Error rate >threshold
- Performance degradation detected

```python
def check_thread_health(checkpoint: AgentLoopCheckpoint) -> bool:
    """Determine if thread switch needed."""
    health = checkpoint.thread_health_metrics[checkpoint.current_thread_id]
    return (
        health.context_percentage > 0.8 or
        health.message_count > 200 or
        health.error_rate > 0.3
    )
```

### Thread Switch Execution

```python
def execute_thread_switch(new_thread_id: str) -> None:
    """Execute thread switch with goal briefing flag."""
    checkpoint.thread_ids.append(new_thread_id)
    checkpoint.current_thread_id = new_thread_id
    checkpoint.thread_switch_pending = True  # Flag for goal briefing
    checkpoint.total_thread_switches += 1
    checkpoint.thread_health_metrics[new_thread_id] = ThreadHealthMetrics()
    save_checkpoint(checkpoint)

    emit soothe.agentic.thread_switched
```

---

## Goal Context Manager

### Unified Goal-Level Context Provider

AgentLoop mirrors CoreAgent's context separation pattern:
- **CoreAgent**: Conversation history (thread state) vs execution context (configurable briefings)
- **AgentLoop**: Goal-level history (loop checkpoint) vs iteration context (LoopState excerpts)

**Key constraint**: Keep loop history (goals) separate from thread history (messages).

### GoalContextManager Interface

```python
class GoalContextManager:
    """Unified goal-level context provider for AgentLoop.

    Injection rules:
    - Plan phase: ALWAYS inject previous goal summaries (LLM needs goal-level
      context for strategy decisions, regardless of thread continuity)
    - Execute phase: ONLY inject on thread switch (when CoreAgent conversation
      history is lost, goal briefing provides essential knowledge transfer)

    Same-thread constraint: Plan phase only injects goals from current thread.
    Cross-thread scope: Execute briefing includes goals from all threads.
    """

    def __init__(
        self,
        state_manager: AgentLoopStateManager,
        config: GoalContextConfig,
        embedding_model: Embeddings,
    ) -> None:
        self._state_manager = state_manager
        self._config = config
        self._thread_relationship = ThreadRelationshipModule(embedding_model)

    def get_plan_context(self, limit: int | None = None) -> list[str]:
        """Get previous goal summaries for Plan phase (XML blocks).

        Always injects - Plan phase needs goal-level strategy context
        even when CoreAgent has conversation continuity.

        Same-thread constraint: Only goals from checkpoint.current_thread_id.
        """

    def get_execute_briefing(self, limit: int | None = None) -> str | None:
        """Get goal briefing for Execute phase (only on thread switch).

        Thread-switch constraint: Only inject when checkpoint.thread_switch_pending.

        Cross-thread scope: Includes goals from all threads for knowledge transfer.
        """
```

### Plan Phase Integration

Inject previous goal context at AgentLoop initialization:

```python
async def run_with_progress(...):
    state_manager = AgentLoopStateManager(thread_id, workspace)
    goal_context_manager = GoalContextManager(state_manager, config.goal_context)

    # Inject previous goal context
    plan_goal_excerpts = goal_context_manager.get_plan_context(limit=10)

    # Combine with step-derived context
    plan_excerpts = plan_goal_excerpts + list(state_manager.derive_plan_conversation(limit=5))

    state = LoopState(
        plan_conversation_excerpts=plan_excerpts,
        ...
    )
```

### Execute Phase Integration

Inject goal briefing on thread switch via CoreAgent config:

```python
async def execute(decision, state):
    goal_briefing = goal_context_manager.get_execute_briefing(limit=10)

    config = {
        "configurable": {
            "thread_id": state.thread_id,
            "soothe_goal_briefing": goal_briefing,  # None or markdown string
            "soothe_step_tools": step.tools,
            ...
        }
    }

    # CoreAgent receives briefing in system prompt
    async for chunk in core_agent.astream(step.description, config=config):
        ...
```

---

## Thread Relationship Module

### Goal Similarity & Context Construction

Thread relationship analysis for goal context construction:

When thread-derived context participates in failure diagnosis/backoff preparation, evidence payloads must align with the canonical shared contract in `RFC-200` (`EvidenceBundle`, `GoalSubDAGStatus`) to avoid cross-layer schema drift.

```python
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
    """Thread relationship analysis for goal context."""

    def compute_similarity(self, goal_a: Goal, goal_b: Goal) -> float:
        """Goal similarity for thread clustering.

        Hierarchy (exact > semantic > dependency):
        - Exact match: 1.0 (same goal_id)
        - Semantic similarity: embedding distance
        - Dependency relationship: same DAG path
        """

    def construct_goal_context(
        self,
        goal_id: str,
        goal_history: list[GoalRecord],
        options: ContextConstructionOptions,
    ) -> GoalContext:
        """Context construction with thread ecosystem awareness."""
```

### Similarity Hierarchy

1. **Exact Match**: Same goal_id (score: 1.0)
2. **Semantic Similarity**: Embedding distance on goal descriptions
3. **Dependency Relationship**: Goals in same DAG dependency chain

### Context Construction Strategies

| Strategy | Selection Logic |
|----------|-----------------|
| `latest` | Most recent thread execution |
| `all` | All matching threads (bounded by limit) |
| `best_performing` | Thread with best metrics (duration, success) |

### GoalContextManager Integration

```python
def get_execute_briefing(self, limit: int | None = None) -> str | None:
    checkpoint = self._state_manager.load()
    if not checkpoint or not checkpoint.thread_switch_pending:
        return None

    # Clear flag
    checkpoint.thread_switch_pending = False
    self._state_manager.save(checkpoint)

    # Use thread relationship module
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

---

## Executor Thread Coordination

### Thread Assignment Logic

Executor assigns threads based on execution mode:

**Parallel execution**: All steps use parent thread_id (langgraph handles concurrency)
```python
results = await asyncio.gather([
    execute_step(step, thread_id=parent_tid)
    for step in steps
])
```

**Sequential execution**: Combined input on parent thread
```python
combined_input = build_sequential_input(steps)
results = await core_agent.astream(combined_input, thread_id=parent_tid)
```

**Subagent delegation**: Task tool creates isolated thread branch automatically

### Event-Driven Monitoring

CoreAgent threads emit execution events:

```python
class ThreadExecutionEvent(BaseModel):
    """Thread execution event emitted by CoreAgent."""
    thread_id: str
    step_id: str
    event_type: Literal["started", "progress", "completed", "failed"]
    progress: float | None
    error: str | None
```

Executor subscribes to events for monitoring:
- Progress tracking
- Status updates
- Error detection
- Completion signaling

### Report-back alternative (symmetric pattern)

**Push events** (above) are one valid integration pattern. The **report-back** alternative places responsibility on CoreAgent (or middleware hooks) to **emit summaries or status payloads** at milestones so the Executor ingests the same facts without subscribing to a streaming event bus.

Both patterns are **architecturally acceptable** for building Layer 2 monitoring and checkpoint updates, provided evidence payloads remain compatible with the shared contracts in RFC-200 (for example `EvidenceBundle` usage) and ordering constraints in RFC-203. Implementations choose push, pull, or both per transport and runtime constraints.

---

## Content Format

### Plan Phase Format (XML Blocks)

```xml
<previous_goal>
Goal: analyze performance bottlenecks in data pipeline
Status: completed
Thread: thread_abc123
Iteration: 3
Duration: 15.2s
Output:
I identified three critical bottlenecks:
1. Database query N+1 problem in user_service.py:142
2. Unbatched API calls in data_fetcher.py:89
3. Missing cache layer for frequently accessed configs
</previous_goal>
```

### Execute Phase Format (Markdown Briefing)

```
## Previous Goal Context (Thread Switch Recovery)

**Goal 1** (thread_abc123, completed in 3 iterations):
Query: analyze performance bottlenecks
Key findings: Database N+1 queries, unbatched API calls
Critical files: user_service.py:142, data_fetcher.py:89
Result: 67% performance improvement

**Current thread**: thread_xyz789 (new thread)
**Instruction**: Use previous goal context. Reference critical files.
```

---

## Configuration

```yaml
agentic:
  thread_lifecycle:
    max_messages_per_thread: 200
    max_context_percentage: 0.8
    enable_thread_switching: true

  goal_context:
    plan_limit: 10  # Previous goals for Plan phase
    execute_limit: 10  # Previous goals for Execute briefing
    include_similar_goals: true
    thread_selection_strategy: latest
    similarity_threshold: 0.7
    embedding_role: embedding
```

---

## Implementation Status

- ✅ Thread lifecycle multi-thread spanning
- ✅ Thread health metrics tracking
- ✅ Thread switch detection logic
- ✅ Goal context manager integration
- ✅ Thread relationship module
- ✅ Similarity computation (exact, semantic)
- ✅ Context construction strategies
- ⚠️ Executor thread monitoring (in progress)

---

## References

- RFC-201: AgentLoop Plan-Execute Loop Architecture
- RFC-203: AgentLoop State & Memory Architecture
- RFC-608: Loop Multi-Thread Lifecycle (original source)
- RFC-609: Goal Context Management (original source)

---

## Changelog

### 2026-04-17
- Consolidated RFC-207 (Thread Lifecycle), RFC-207 (Goal Context Manager), RFC-207 (Thread Relationship Module), RFC-207 (Executor Coordination) into unified thread management architecture
- Combined thread lifecycle with goal context integration
- Unified similarity-based context construction with thread switching
- Maintained architectural isolation (loop history vs thread history)
- Added thread health metrics and switch detection logic

---

*AgentLoop thread management with lifecycle spanning, goal context bridging, similarity-based context construction, and executor coordination.*
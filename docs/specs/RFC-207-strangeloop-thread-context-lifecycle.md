# RFC-207: StrangeLoop Thread Lifecycle & Goal Context Management

**RFC**: 207
**Title**: StrangeLoop Thread Lifecycle & Goal Context Management
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-17
**Updated**: 2026-06-19
**Dependencies**: RFC-201, RFC-203
**Supersedes**: RFC-216 (Multi-Thread Infinite Lifecycle)
**Related**: RFC-213 (Reasoning), RFC-217 (Goal Context Management)

---

## Abstract

This RFC defines StrangeLoop thread lifecycle management and goal context integration, consolidating thread lifecycle (multi-thread spanning), goal context manager (previous goal injection), thread relationship module (similarity-based context), and executor thread coordination. StrangeLoop threads span multiple CoreAgent executions with goal-level context bridging thread switches while maintaining architectural isolation between loop history (goals) and thread history (messages).

This specification supersedes RFC-216 by integrating its comprehensive multi-thread lifecycle architecture, including infinite loop lifecycle, automatic thread switching, goal-thread relevance analysis, and knowledge transfer mechanisms.

## Motivation

### Current Problem

StrangeLoop checkpoint is goal-scoped: each new goal on the same thread initializes a fresh checkpoint (iteration=0, empty history), discarding previous goal execution traces. This creates two critical issues:

1. **Same-thread continuation failure**: When user sends "translate to chinese" on thread where "count readme files" completed, StrangeLoop loses previous final_report context, causing agent to ask "请提供需要翻译成中文的文本" instead of translating the previous report.

2. **Thread context pollution**: LangGraph threads accumulate message history unbounded. When message history grows too large (100K+ tokens), execution becomes slow and expensive. No mechanism to reset execution context while preserving loop-level knowledge.

### Proposed Solution

StrangeLoop becomes an abstract orchestration entity spanning multiple threads:

- **Infinite lifecycle**: Loop persists across multiple goals and multiple threads (status flow: `ready_for_next_goal` → `running` → `ready_for_next_goal` → ... → `finalized`)
- **Multi-thread spanning**: Loop has unique `loop_id` (independent of thread_id), tracks thread history (`thread_ids` list), can switch between threads
- **Automatic thread switching**: Policy-based triggers detect thread problems (message history threshold, consecutive failures, checkpoint errors, subagent issues) and switch to fresh thread
- **Goal-thread relevance analysis**: LLM-based semantic analysis evaluates if current thread context hinders next goal (goal independence, domain mismatch, message pollution) before execution
- **Auto /recall knowledge transfer**: When thread switches, automatically search previous threads' goal_history and inject top-K relevant knowledge into new thread's Plan phase
- **Complete goal history**: Loop checkpoint maintains all goal execution records across all threads (GoalExecutionRecord includes thread_id)
- **Knowledge-aware routing (optional policy dimension)**: In addition to LLM goal–thread relevance, policies MAY prefer threads whose **goal_history or tool evidence** aligns with the current goal's topic or domain (for example embedding-neighbor goals or same-domain subagent traces, aligned with RFC-217 thread-relationship options). This does not replace semantic relevance analysis; it **narrows or ranks** candidate threads when multiple LangGraph threads are eligible.

---

## Architecture

### Core Concept

**StrangeLoop = Abstract orchestration entity spanning multiple threads**

- **Identity**: `loop_id` (UUID, independent of thread_id)
- **Thread binding**: `current_thread_id` (active thread) + `thread_ids` (all threads loop has operated on)
- **Lifecycle**: Infinite (persists across goals and threads)
- **Thread switching**: Automatic, policy-based triggers
- **Knowledge transfer**: Auto /recall on thread switch

**Key Principle**: Loop transcends thread boundaries; goals are execution units. Loop provides continuity and context; goals provide task-specific execution.

### Layer Integration

This RFC extends RFC-203 (Layer 2 Unified State Model) and RFC-201 (Agentic Goal Execution):

- **Layer 2 StrangeLoop**: Manages Plan → Execute loop across multiple threads
- **Layer 1 CoreAgent**: Executes on specific thread (LangGraph thread_id)
- **Thread switching**: Layer 2 decides when to switch, Layer 1 executes on new thread

---

## Data Models

### StrangeLoopCheckpoint (v2.0)

```python
class StrangeLoopCheckpoint(BaseModel):
    """Abstract loop checkpoint spanning multiple threads."""

    # Identity
    loop_id: str  # Unique loop identifier (UUID)
    thread_ids: list[str]  # All threads loop has operated on (full history)
    current_thread_id: str  # Active thread for current goal execution
    thread_switch_pending: bool = False  # Flag indicating thread just switched

    # Status (infinite lifecycle)
    status: Literal["running", "ready_for_next_goal", "finalized", "cancelled"]

    # Goal execution history (across all threads)
    goal_history: list[GoalExecutionRecord]  # All goals (chronological)
    current_goal_index: int  # Index of active goal (0-based, -1 if none)

    # Working memory (cleared per-goal)
    working_memory_state: WorkingMemoryState

    # Thread health monitoring
    thread_health_metrics: dict[str, ThreadHealthMetrics] = {}
    """Per-thread health tracking."""

    # Loop-level metrics
    total_goals_completed: int  # Count of completed goals
    total_thread_switches: int  # Count of thread switches
    total_duration_ms: int  # Cumulative across all goals
    total_tokens_used: int  # Cumulative across all goals

    # Timestamps
    created_at: datetime  # Loop creation
    updated_at: datetime  # Last modification

    schema_version: str = "2.0"  # v1.0 was goal-scoped, v2.0 is loop-scoped
```

**Changes from v1.0**:
- Added `loop_id`, `thread_ids`, `current_thread_id` (multi-thread identity)
- Added `thread_health_metrics` (health monitoring)
- Added `total_thread_switches` (switch counter)
- Status changed: goal-scoped → loop-scoped (`ready_for_next_goal`, `running`, `finalized`)
- No backward compatibility with v1.0 (fresh start)

### GoalExecutionRecord

```python
class GoalExecutionRecord(BaseModel):
    """Single goal execution record (on specific thread)."""

    # Identity
    goal_id: str  # "{loop_id}_goal_{seq}"
    goal_text: str  # Original goal description
    thread_id: str  # Thread where goal was executed

    # Execution state
    iteration: int  # Current iteration (0-based)
    max_iterations: int  # Maximum iterations
    status: Literal["completed", "failed", "cancelled"]

    # Execution traces
    reason_history: list[ReasonStepRecord]  # Plan phase decisions
    act_history: list[ActWaveRecord]  # Execute phase waves

    # Goal output
    final_report: str  # Final report (generated at completion)
    evidence_summary: str  # Condensed evidence

    # Metrics
    duration_ms: int  # Goal execution duration
    tokens_used: int  # Tokens consumed

    # Timestamps
    started_at: datetime
    completed_at: datetime | None
```

**Goal ID Generation**: `{loop_id}_goal_{seq}` (independent of thread_id, sequence increments per goal across entire loop)

### ThreadHealthMetrics

```python
class ThreadHealthMetrics(BaseModel):
    """Current thread health state for switching policy."""

    thread_id: str  # Thread being monitored
    last_updated: datetime  # Metrics timestamp

    # Message history metrics
    message_count: int = 0
    """Number of messages in thread."""
    estimated_tokens: int  # Estimated token count
    message_history_size_mb: float  # Storage size
    context_percentage: float = 0.0
    """Context window utilization."""

    # Execution health metrics
    consecutive_goal_failures: int  # Consecutive failed goals
    last_goal_status: Literal["completed", "failed", "cancelled"] | None
    error_rate: float = 0.0
    """Error rate in recent executions."""

    # LangGraph checkpoint health
    checkpoint_errors: int  # Checkpoint read/write errors
    last_checkpoint_error: str | None
    checkpoint_corruption_detected: bool

    # Subagent execution health
    subagent_timeout_count: int  # Subagent timeouts
    subagent_crash_count: int  # Subagent crashes
    last_subagent_error: str | None

    # Custom metrics (extensible)
    custom_metrics: dict[str, Any] = {}
```

### ThreadSwitchPolicy

```python
class ThreadSwitchPolicy(BaseModel):
    """Extensible policy for automatic thread switching."""

    # Quantitative triggers (configurable)
    message_history_token_threshold: int | None = 100000  # Token threshold
    consecutive_goal_failure_threshold: int | None = 3  # Failure threshold
    checkpoint_error_threshold: int | None = 2  # Error threshold
    subagent_timeout_threshold: int | None = 2  # Timeout threshold

    # Semantic trigger
    goal_thread_relevance_check_enabled: bool = True  # LLM-based relevance analysis
    relevance_analysis_model: str | None = None  # Model for analysis (None = default)
    relevance_confidence_threshold: float = 0.7  # Switch threshold

    # Switch behavior
    auto_switch_enabled: bool = True
    max_thread_switches_per_loop: int | None = None  # Unlimited by default
    knowledge_transfer_limit: int = 10  # Top-K results on thread switch

    # Custom triggers (extensible)
    custom_triggers: list[CustomSwitchTrigger] = []

    # Metadata
    policy_name: str = "default"
    policy_version: str = "1.0"
```

### GoalThreadRelevanceAnalysis

```python
class GoalThreadRelevanceAnalysis(BaseModel):
    """LLM-based analysis of goal-thread relevance."""

    thread_summary: str  # Thread context summary
    next_goal: str  # Goal to analyze

    # LLM response
    is_relevant: bool  # Thread relevant to goal?
    hindering_reasons: list[str]  # Detected factors (goal independence, domain mismatch, pollution)
    confidence: float  # LLM confidence (0.0-1.0)
    reasoning: str  # Detailed explanation

    # Decision
    should_switch_thread: bool  # True if hindering detected (confidence >= threshold)
```

**Hindering Criteria**:
- Goal independence: No connection to thread's previous work
- Context domain mismatch: Thread focus contradicts goal needs (e.g., backend thread → frontend goal)
- Message history pollution: Irrelevant tangents, off-topic discussions

**NOT Hindering**: Failed execution history (provides learning context)

---

## State Transitions

### Loop Initialization

**Trigger**: Thread created (first input)

**Process**:
1. Generate `loop_id` (UUID)
2. Create StrangeLoopCheckpoint:
   - `loop_id = generated_uuid`
   - `thread_ids = [thread_id]`  # First thread
   - `current_thread_id = thread_id`
   - `status = "ready_for_next_goal"`
   - `goal_history = []`
   - `thread_health_metrics = ThreadHealthMetrics(thread_id=thread_id)`
3. Save to `SOOTHE_HOME/runs/{loop_id}/strange_loop_checkpoint.json`

### Goal Execution Start

**Trigger**: User sends goal, loop status=`ready_for_next_goal`

**Process**:
1. Load loop checkpoint (by `loop_id`)
2. Evaluate ThreadSwitchPolicy (all triggers including goal-thread relevance)
3. If thread switch triggered → Execute Thread Switch
4. Generate goal_id: `{loop_id}_goal_{len(goal_history)}`
5. Create GoalExecutionRecord (include `thread_id`)
6. Append to `goal_history`, update `current_goal_index`
7. Clear `working_memory_state` (fresh working memory)
8. Inject context into Plan phase:
   - Previous goal final_report (if goal_history has previous goals)
   - Auto /recall results (if thread just switched)
9. Update status=`running`

### Thread Switch Execution

**Trigger**: ThreadSwitchPolicy evaluation returns `switch_thread=True`

**Pre-conditions**:
- Loop status=`ready_for_next_goal`
- Thread health triggers met OR goal-thread relevance hindering detected
- Switch limit not exceeded

**Process**:
1. Log switch trigger reason
2. Create new LangGraph thread → `new_thread_id`
3. Update loop checkpoint:
   - `thread_ids.append(new_thread_id)`
   - `current_thread_id = new_thread_id`
   - `thread_switch_pending = True`  # Flag for goal briefing
   - `total_thread_switches += 1`
   - `thread_health_metrics[new_thread_id] = ThreadHealthMetrics()`
4. Auto /recall knowledge transfer:
   - Query previous threads' goal_history
   - Vector search: `goal_text`, `final_report`
   - Select top-K (K = `knowledge_transfer_limit`)
   - Format as `<recalled_knowledge>` blocks
   - Inject into next goal's Plan phase
5. Save checkpoint
6. Emit `soothe.agentic.thread_switched` event

**Example**:
- Loop L1 on thread A: message_history_tokens = 105K (threshold=100K) → Switch triggered
- Create thread B → Update: thread_ids=["A", "B"], current_thread_id="B"
- Auto /recall: Search thread A's goal_history → Inject top-10 results
- Next goal on thread B: Fresh execution context with essential knowledge

### Thread Switch Detection (Legacy)

**Trigger conditions**:
- Context window >80% full
- Message count >threshold
- Error rate >threshold
- Performance degradation detected

```python
def check_thread_health(checkpoint: StrangeLoopCheckpoint) -> bool:
    """Determine if thread switch needed."""
    health = checkpoint.thread_health_metrics[checkpoint.current_thread_id]
    return (
        health.context_percentage > 0.8 or
        health.message_count > 200 or
        health.error_rate > 0.3
    )
```

### Goal Completion

**Trigger**: Plan phase returns `status="done"`

**Process**:
1. Generate final_report via CoreAgent
2. Update GoalExecutionRecord: `status="completed"`, `final_report=...`
3. Update StrangeLoopCheckpoint:
   - `status="ready_for_next_goal"`
   - `total_goals_completed += 1`
   - Update `thread_health_metrics` (reset consecutive_goal_failures on success)
4. Save checkpoint

---

## Thread Health Monitoring

### Metrics Collection

**Timing**: Collected after each goal completion

**Process**:
1. **Message history**: Query LangGraph checkpointer → message_count, estimated_tokens, size_mb
2. **Execution health**: Track goal status, consecutive_goal_failures count
3. **Checkpoint health**: Monitor read/write errors, corruption detection
4. **Subagent health**: Track timeouts, crashes via Executor
5. Update ThreadHealthMetrics, save checkpoint

### Policy Evaluation

**Timing**: Before each goal start (when status=`ready_for_next_goal`)

**Evaluation Logic**:
```python
# Check quantitative triggers
if metrics.estimated_tokens > policy.message_history_token_threshold:
    trigger("Message history too large")

if metrics.consecutive_goal_failures >= policy.consecutive_goal_failure_threshold:
    trigger("Consecutive goal failures")

if metrics.checkpoint_errors >= policy.checkpoint_error_threshold:
    trigger("Checkpoint errors")

if metrics.subagent_timeout_count >= policy.subagent_timeout_threshold:
    trigger("Subagent timeouts")

if metrics.checkpoint_corruption_detected:
    trigger("Checkpoint corruption")

# Check semantic trigger
if policy.goal_thread_relevance_check_enabled:
    analysis = analyze_goal_thread_relevance(next_goal, checkpoint, model)
    if analysis.should_switch_thread:
        trigger(f"Goal-thread relevance: {analysis.hindering_reasons}")
```

### Goal-Thread Relevance Analysis

**Implementation**:
- LLM prompt: Analyze thread summary + goal history + next goal against hindering criteria
- Response format: Structured JSON (is_relevant, hindering_reasons, confidence, reasoning, should_switch_thread)
- Decision: Switch if hindering detected AND confidence >= threshold

**Example**:
- Thread A: Backend debugging goals (database optimization)
- Next goal: "Design frontend login UI"
- LLM analysis: is_relevant=false, hindering_reasons=["Goal independence", "Context domain mismatch"], confidence=0.85 → should_switch_thread=true

---

## Knowledge Transfer

### Auto /recall on Thread Switch

**Process**:
1. Identify previous threads: `thread_ids[:-1]` (exclude current new thread)
2. Build searchable corpus: goal_history from previous threads (`goal_text`, `final_report`)
3. Vector search: Query = next goal text or generic query
4. Select top-K relevant results (K = `knowledge_transfer_limit`)
5. Format as `<recalled_knowledge>` blocks
6. Inject into next goal's Plan phase `plan_conversation_excerpts`

**Example**:
- Thread A: 2 goals completed
- Thread switch → Thread B: Auto /recall searches goal_0, goal_1 → Inject top-10 results into thread B's first goal

### Cross-Thread /recall Command

**Mechanism**: User-triggered semantic search across all loops + MemoryProtocol

**Process**:
1. Parse `/recall {query}`
2. Discover all loop checkpoints (scan `SOOTHE_HOME/runs/{loop_id}/`)
3. Vector search: `goal_text`, `final_report` across all goal_history
4. Combine with MemoryProtocol results
5. Inject into current loop's Plan phase

---

## Storage Location

**Path**: Indexed by `loop_id` (independent of thread_id)

```
SOOTHE_HOME/
  runs/
    {loop_id}/  # Loop checkpoint directory
      strange_loop_checkpoint.json  # Loop checkpoint (v2.0)
      loop/
        step-{goal_id}-{step_id}-{seq}.md  # Working memory spill files

    {thread_A}/  # LangGraph thread (managed by LangGraph)
      checkpoint.json  # Message history, execution state
    {thread_B}/  # Another thread
      checkpoint.json
```

**Cross-Reference**:
- Loop checkpoint references threads in `thread_ids`
- GoalExecutionRecord includes `thread_id` field
- Thread health metrics tracked per thread (stored in loop checkpoint)

---

## Goal Context Manager

### Unified Goal-Level Context Provider

StrangeLoop mirrors CoreAgent's context separation pattern:
- **CoreAgent**: Conversation history (thread state) vs execution context (configurable briefings)
- **StrangeLoop**: Goal-level history (loop checkpoint) vs iteration context (LoopState excerpts)

**Key constraint**: Keep loop history (goals) separate from thread history (messages).

### GoalContextManager Interface

```python
class GoalContextManager:
    """Unified goal-level context provider for StrangeLoop.

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
        state_manager: StrangeLoopStateManager,
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

Inject previous goal context at StrangeLoop initialization:

```python
async def run_with_progress(...):
    state_manager = StrangeLoopStateManager(thread_id, workspace)
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
            "soothe_step_subagent": step.subagent,
            "soothe_step_expected_output": step.expected_output,
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

## Module Organization

### New Files

**checkpoint.py**:
- Add GoalExecutionRecord (thread_id field)
- Add ThreadHealthMetrics, ThreadSwitchPolicy, GoalThreadRelevanceAnalysis
- Extend StrangeLoopCheckpoint (loop_id, thread_ids, thread_health_metrics)

**state_manager.py**:
- Update initialize(loop_id, thread_id)
- Update load(loop_id), save()
- Add start_new_goal(), finalize_goal()
- Add execute_thread_switch(), auto_recall_on_thread_switch()

**thread_switch_policy.py** (new):
- ThreadSwitchPolicyManager (policy evaluation, custom trigger support)

**goal_thread_relevance.py** (new):
- analyze_goal_thread_relevance() (LLM invocation)
- build_thread_summary(), parse_llm_analysis_response()

**strange_loop.py**:
- Modify run_with_progress() (loop_id primary key, thread switching logic)
- Add _should_switch_thread(), _execute_thread_switch()
- Add _analyze_goal_thread_relevance(), _update_thread_health_metrics()

### Integration Points

**thread_registry.py**: Add create_thread_for_loop(loop_id) → thread_id

**query_engine.py**: Add /recall command detection, handle_recall_command()

**VectorStoreProtocol**: Index goal_history for semantic search

---

## Implementation Tasks

### Phase 1: Schema & State Manager
- Add new models (ThreadHealthMetrics, ThreadSwitchPolicy, GoalThreadRelevanceAnalysis)
- Extend StrangeLoopCheckpoint schema
- Update state_manager methods (initialize, load, save, thread switch logic)

### Phase 2: Thread Switching Policy
- Create thread_switch_policy.py
- Implement policy evaluation logic
- Add custom trigger extensibility

### Phase 3: StrangeLoop Integration
- Modify run_with_progress() for multi-thread execution
- Add thread health monitoring
- Add goal-thread relevance analysis integration

### Phase 4: /recall Command
- Add /recall command handler
- Implement checkpoint discovery and vector search

### Phase 5: Testing
- Unit tests for multi-thread logic
- Integration tests for thread switching scenarios
- Goal-thread relevance analysis tests

---

## Verification

**Success Criteria**:
- Loop indexed by loop_id (independent of thread_id)
- Automatic thread switching works (policy triggers evaluated)
- Goal-thread relevance analysis prevents context pollution
- Auto /recall transfers essential knowledge on thread switch
- Same-thread goal continuation preserved
- All tests pass

---

## Open Questions

1. Loop ID generation: UUID or user name? (recommendation: UUID)
2. Thread switch timing: Before goal start (clean transition)
3. Auto /recall query: Current goal text (relevance)
4. Policy configuration: Global with loop override option
5. Custom trigger safety: Predefined operators (no arbitrary code execution)

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

- RFC-201: StrangeLoop Plan-Execute Loop Architecture
- RFC-203: StrangeLoop State & Memory Architecture
- RFC-213: StrangeLoop Reasoning Quality
- RFC-217: Goal Context Management
- RFC-216: StrangeLoop Multi-Thread Infinite Lifecycle (superseded)

---

## Changelog

### 2026-06-19
- **Superseded RFC-216**: Consolidated RFC-216 (StrangeLoop Multi-Thread Infinite Lifecycle) into this specification
- Added comprehensive motivation section explaining goal-scoped checkpoint problems
- Integrated complete data models: StrangeLoopCheckpoint v2.0, GoalExecutionRecord, ThreadHealthMetrics, ThreadSwitchPolicy, GoalThreadRelevanceAnalysis
- Added detailed state transitions: Loop initialization, goal execution start, thread switch execution, goal completion
- Integrated thread health monitoring with metrics collection and policy evaluation
- Added knowledge transfer mechanisms: Auto /recall on thread switch and cross-thread /recall command
- Added storage location specification with loop_id indexing
- Added module organization and implementation tasks from RFC-216
- Added verification criteria and open questions

### 2026-04-17
- Consolidated RFC-207 (Thread Lifecycle), RFC-207 (Goal Context Manager), RFC-207 (Thread Relationship Module), RFC-207 (Executor Coordination) into unified thread management architecture
- Combined thread lifecycle with goal context integration
- Unified similarity-based context construction with thread switching
- Maintained architectural isolation (loop history vs thread history)
- Added thread health metrics and switch detection logic

---

*StrangeLoop thread management with lifecycle spanning, goal context bridging, similarity-based context construction, and executor coordination.*
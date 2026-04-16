# RFC-608: AgentLoop Multi-Thread Infinite Lifecycle

**RFC**: 0608
**Title**: AgentLoop Multi-Thread Infinite Lifecycle with Automatic Thread Switching
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-16
**Dependencies**: RFC-205 (Layer 2 Unified State Model), RFC-201 (Agentic Goal Execution)

## Abstract

This RFC defines an architecture for AgentLoop to span multiple LangGraph threads with infinite lifecycle, enabling automatic thread switching when current thread becomes problematic. The loop maintains complete goal execution history across threads, performs semantic goal-thread relevance analysis (LLM-based) before execution, and automatically transfers essential knowledge via /recall when switching threads. This architecture provides seamless continuation, execution context isolation, and extensible policy-based thread management.

## Motivation

### Current Problem

AgentLoop checkpoint is goal-scoped: each new goal on the same thread initializes a fresh checkpoint (iteration=0, empty history), discarding previous goal execution traces. This creates two critical issues:

1. **Same-thread continuation failure**: When user sends "translate to chinese" on thread where "count readme files" completed, AgentLoop loses previous final_report context, causing agent to ask "请提供需要翻译成中文的文本" instead of translating the previous report.

2. **Thread context pollution**: LangGraph threads accumulate message history unbounded. When message history grows too large (100K+ tokens), execution becomes slow and expensive. No mechanism to reset execution context while preserving loop-level knowledge.

### Proposed Solution

AgentLoop becomes an abstract orchestration entity spanning multiple threads:

- **Infinite lifecycle**: Loop persists across multiple goals and multiple threads (status flow: `ready_for_next_goal` → `running` → `ready_for_next_goal` → ... → `finalized`)
- **Multi-thread spanning**: Loop has unique `loop_id` (independent of thread_id), tracks thread history (`thread_ids` list), can switch between threads
- **Automatic thread switching**: Policy-based triggers detect thread problems (message history threshold, consecutive failures, checkpoint errors, subagent issues) and switch to fresh thread
- **Goal-thread relevance analysis**: LLM-based semantic analysis evaluates if current thread context hinders next goal (goal independence, domain mismatch, message pollution) before execution
- **Auto /recall knowledge transfer**: When thread switches, automatically search previous threads' goal_history and inject top-K relevant knowledge into new thread's Plan phase
- **Complete goal history**: Loop checkpoint maintains all goal execution records across all threads (GoalExecutionRecord includes thread_id)

## Architecture

### Core Concept

**AgentLoop = Abstract orchestration entity spanning multiple threads**

- **Identity**: `loop_id` (UUID, independent of thread_id)
- **Thread binding**: `current_thread_id` (active thread) + `thread_ids` (all threads loop has operated on)
- **Lifecycle**: Infinite (persists across goals and threads)
- **Thread switching**: Automatic, policy-based triggers
- **Knowledge transfer**: Auto /recall on thread switch

**Key Principle**: Loop transcends thread boundaries; goals are execution units. Loop provides continuity and context; goals provide task-specific execution.

### Layer Integration

This RFC extends RFC-205 (Layer 2 Unified State Model) and RFC-201 (Agentic Goal Execution):

- **Layer 2 AgentLoop**: Manages Plan → Execute loop across multiple threads
- **Layer 1 CoreAgent**: Executes on specific thread (LangGraph thread_id)
- **Thread switching**: Layer 2 decides when to switch, Layer 1 executes on new thread

## Data Models

### AgentLoopCheckpoint (v2.0)

```python
class AgentLoopCheckpoint(BaseModel):
    """Abstract loop checkpoint spanning multiple threads."""

    # Identity
    loop_id: str  # Unique loop identifier (UUID)
    thread_ids: list[str]  # All threads loop has operated on (full history)
    current_thread_id: str  # Active thread for current goal execution

    # Status (infinite lifecycle)
    status: Literal["running", "ready_for_next_goal", "finalized", "cancelled"]

    # Goal execution history (across all threads)
    goal_history: list[GoalExecutionRecord]  # All goals (chronological)
    current_goal_index: int  # Index of active goal (0-based, -1 if none)

    # Working memory (cleared per-goal)
    working_memory_state: WorkingMemoryState

    # Thread health monitoring
    thread_health_metrics: ThreadHealthMetrics  # Current thread health state

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
    message_count: int  # Total messages in LangGraph checkpoint
    estimated_tokens: int  # Estimated token count
    message_history_size_mb: float  # Storage size

    # Execution health metrics
    consecutive_goal_failures: int  # Consecutive failed goals
    last_goal_status: Literal["completed", "failed", "cancelled"] | None

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

    # Semantic trigger (NEW)
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

## State Transitions

### Loop Initialization

**Trigger**: Thread created (first input)

**Process**:
1. Generate `loop_id` (UUID)
2. Create AgentLoopCheckpoint:
   - `loop_id = generated_uuid`
   - `thread_ids = [thread_id]`  # First thread
   - `current_thread_id = thread_id`
   - `status = "ready_for_next_goal"`
   - `goal_history = []`
   - `thread_health_metrics = ThreadHealthMetrics(thread_id=thread_id)`
3. Save to `SOOTHE_HOME/runs/{loop_id}/agent_loop_checkpoint.json`

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
   - `total_thread_switches += 1`
   - `thread_health_metrics = ThreadHealthMetrics(thread_id=new_thread_id)`
4. Auto /recall knowledge transfer:
   - Query previous threads' goal_history
   - Vector search: `goal_text`, `final_report`
   - Select top-K (K = `knowledge_transfer_limit`)
   - Format as `<recalled_knowledge>` blocks
   - Inject into next goal's Plan phase
5. Save checkpoint

**Example**:
- Loop L1 on thread A: message_history_tokens = 105K (threshold=100K) → Switch triggered
- Create thread B → Update: thread_ids=["A", "B"], current_thread_id="B"
- Auto /recall: Search thread A's goal_history → Inject top-10 results
- Next goal on thread B: Fresh execution context with essential knowledge

### Goal Completion

**Trigger**: Plan phase returns `status="done"`

**Process**:
1. Generate final_report via CoreAgent
2. Update GoalExecutionRecord: `status="completed"`, `final_report=...`
3. Update AgentLoopCheckpoint:
   - `status="ready_for_next_goal"`
   - `total_goals_completed += 1`
   - Update `thread_health_metrics` (reset consecutive_goal_failures on success)
4. Save checkpoint

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

# Check semantic trigger (NEW)
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

## Storage Location

**Path**: Indexed by `loop_id` (independent of thread_id)

```
SOOTHE_HOME/
  runs/
    {loop_id}/  # Loop checkpoint directory
      agent_loop_checkpoint.json  # Loop checkpoint (v2.0)
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

## Module Organization

### New Files

**checkpoint.py**:
- Add GoalExecutionRecord (thread_id field)
- Add ThreadHealthMetrics, ThreadSwitchPolicy, GoalThreadRelevanceAnalysis
- Extend AgentLoopCheckpoint (loop_id, thread_ids, thread_health_metrics)

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

**agent_loop.py**:
- Modify run_with_progress() (loop_id primary key, thread switching logic)
- Add _should_switch_thread(), _execute_thread_switch()
- Add _analyze_goal_thread_relevance(), _update_thread_health_metrics()

### Integration Points

**thread_registry.py**: Add create_thread_for_loop(loop_id) → thread_id

**query_engine.py**: Add /recall command detection, handle_recall_command()

**VectorStoreProtocol**: Index goal_history for semantic search

## Implementation Tasks

### Phase 1: Schema & State Manager
- Add new models (ThreadHealthMetrics, ThreadSwitchPolicy, GoalThreadRelevanceAnalysis)
- Extend AgentLoopCheckpoint schema
- Update state_manager methods (initialize, load, save, thread switch logic)

### Phase 2: Thread Switching Policy
- Create thread_switch_policy.py
- Implement policy evaluation logic
- Add custom trigger extensibility

### Phase 3: AgentLoop Integration
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

## Verification

**Success Criteria**:
- Loop indexed by loop_id (independent of thread_id)
- Automatic thread switching works (policy triggers evaluated)
- Goal-thread relevance analysis prevents context pollution
- Auto /recall transfers essential knowledge on thread switch
- Same-thread goal continuation preserved
- All tests pass

## Open Questions

1. Loop ID generation: UUID or user name? (recommendation: UUID)
2. Thread switch timing: Before goal start (clean transition)
3. Auto /recall query: Current goal text (relevance)
4. Policy configuration: Global with loop override option
5. Custom trigger safety: Predefined operators (no arbitrary code execution)

## Related Specifications

- RFC-205: Layer 2 Unified State Model
- RFC-201: Agentic Goal Execution
- RFC-203: Loop Working Memory
- RFC-002: MemoryProtocol
- RFC-103: VectorStoreProtocol

## Changelog

**2026-04-16 (created)**:
- Initial RFC for AgentLoop multi-thread infinite lifecycle
- Automatic thread switching with extensible policy
- Goal-thread relevance analysis (LLM semantic evaluation)
- Auto /recall knowledge transfer
- Thread health monitoring
- Multi-thread spanning architecture
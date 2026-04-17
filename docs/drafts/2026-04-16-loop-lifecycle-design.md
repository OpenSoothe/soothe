# AgentLoop Multi-Thread Infinite Lifecycle Design

**Date**: 2026-04-16
**Status**: Draft
**Depends on**: RFC-203 (Layer 2 Unified State Model and Independent Checkpoint), RFC-200 (Agentic Goal Execution)

## Problem Statement

### Current Behavior

AgentLoop checkpoint is goal-scoped: each new goal on the same thread initializes a fresh checkpoint (iteration=0, empty history), discarding previous goal execution traces.

**Example**:
- Thread `5ru93n8luabj` completes goal "count all readme of this project" → final_report saved
- User sends "translate to chinese" on SAME thread
- AgentLoop loads previous checkpoint (status="completed"), then **initializes new checkpoint** (iteration=0, goal_history=[])
- Plan phase has NO context of previous final report → Agent asks "请提供需要翻译成中文的文本"
- Expected: Agent should see previous report and translate it

**Root Cause** (agent_loop.py:141):
```python
if checkpoint and checkpoint.status == "running":
    # Recovery case
else:
    checkpoint = state_manager.initialize(goal, max_iterations)  # NEW checkpoint!
```

When previous goal completed (status="completed"), new goal creates a new checkpoint, losing all execution history.

### Architectural Vision

**Loop Lifecycle**: AgentLoop should be an abstract orchestration entity with infinite lifecycle, capable of spanning multiple LangGraph threads and persisting across multiple goal executions.

**Core Requirements**:
- Each loop has unique `loop_id` (independent of thread_id)
- Loop can switch between threads automatically (when current thread becomes problematic)
- Loop tracks thread history (all threads it has operated on)
- Loop maintains complete goal execution history across all threads
- Thread switching triggers automatic /recall (injects essential knowledge from previous threads)
- Extensible policy-based thread switching triggers (configurable, can be enhanced/removed)
- Cross-thread knowledge retrieval via `/recall` command (searches all loop checkpoints + MemoryProtocol)

---

## Architecture

### Core Concept

**AgentLoop = Abstract orchestration entity spanning multiple threads with infinite lifecycle**

- **Identity**: Unique `loop_id` (independent of thread_id, can switch threads)
- **Scope**: Loop can operate across multiple LangGraph threads (thread_history)
- **Thread binding**: Active thread (`current_thread_id`) + thread history (`thread_ids`)
- **State**: Tracks execution history (goal_history across all threads), current goal, thread_health_metrics
- **Transitions**: `ready_for_next_goal` → `running` → `ready_for_next_goal` → ... → `finalized`
- **Thread switching**: Automatic when thread becomes problematic (policy-based triggers)
- **Knowledge transfer**: Auto /recall from previous threads on thread switch
- **Cross-thread**: `/recall` searches checkpoints across all threads + MemoryProtocol

**Key Principle**: Loop is the orchestration entity transcending thread boundaries; goals are execution units within the loop. Loop provides continuity and context across threads; goals provide task-specific execution.

---

### Lifecycle States

**Status Flow** (with thread switching):
```
Thread A created → Initialize Loop (loop_id=L1, thread_ids=[A], current_thread_id=A, status=ready_for_next_goal)
Goal 1 on thread A → Loop runs (status=running) → Goal completed (status=ready_for_next_goal)
Thread A becomes problematic → ThreadSwitchPolicy triggers switch
Create thread B → Loop updates (thread_ids=[A, B], current_thread_id=B) → Auto /recall from thread A
Goal 2 on thread B → Loop runs (fresh execution context) → Goal completed
... repeat ...
Loop finalized → No more goals accepted
```

**Thread Switching Events**:
- Thread A: Message history exceeds threshold (e.g., 100K tokens)
- Thread A: LangGraph checkpoint error (corruption, database failure)
- Thread A: Repeated goal failures (3 consecutive failed goals)
- Thread A: Subagent execution issues (timeout, crash)
- → Trigger: Automatic thread switch to thread B

**Status Semantics**:
- `ready_for_next_goal`: Waiting for next goal input (previous goal completed or initial state)
- `running`: Currently executing goal N on current_thread_id (Plan → Execute loop active)
- `finalized`: Loop archived, no more goals accepted (across all threads)
- `cancelled`: Loop cancelled mid-execution on current_thread_id

---

### Identity Model

**Loop Identity**:
- `loop_id`: Unique identifier (UUID or user-specified name, independent of thread_id)
- `thread_ids`: List of all threads loop has operated on (thread history)
- `current_thread_id`: Active thread for current goal execution
- Goal IDs: `{loop_id}_goal_{seq}` (e.g., "L1_goal_0", "L1_goal_1" - goal IDs independent of thread)

**Thread Binding**:
- Initial: Loop created on first thread (loop_id ≠ thread_id, thread_ids=[thread_A])
- Thread switching: Loop adds new thread to thread_ids, updates current_thread_id
- Thread history: Full audit trail (thread_ids grows unbounded, archived threads retained)

**Example**:
- Loop L1 starts on thread A: thread_ids=["A"], current_thread_id="A"
- Thread switch to thread B: thread_ids=["A", "B"], current_thread_id="B"
- Thread switch to thread C: thread_ids=["A", "B", "C"], current_thread_id="C"
- Goal IDs: L1_goal_0 (thread A), L1_goal_1 (thread B), L1_goal_2 (thread C)

---

## Data Models

### AgentLoopCheckpoint (Thread-Scoped)

```python
class AgentLoopCheckpoint(BaseModel):
    """Abstract loop checkpoint spanning multiple threads with infinite lifecycle."""

    # Identity
    loop_id: str  # Unique loop identifier (UUID or user name, independent of thread)
    thread_ids: list[str]  # All threads loop has operated on (full history)
    current_thread_id: str  # Active thread for current goal execution

    # Status (infinite lifecycle)
    status: Literal["running", "ready_for_next_goal", "finalized", "cancelled"]

    # Goal execution history (across all threads)
    goal_history: list[GoalExecutionRecord]  # All goals (chronological across threads)
    current_goal_index: int  # Index of active goal (0-based, -1 if none)

    # Working memory (shared across goals, cleared per-goal)
    working_memory_state: WorkingMemoryState

    # Thread health metrics (for switching policy)
    thread_health_metrics: ThreadHealthMetrics  # Current thread health state

    # Loop-level metrics
    total_goals_completed: int  # Count of completed goals (across all threads)
    total_thread_switches: int  # Count of thread switches
    total_duration_ms: int  # Cumulative across all goals
    total_tokens_used: int  # Cumulative across all goals

    # Timestamps
    created_at: datetime  # Loop creation
    updated_at: datetime  # Last modification

    schema_version: str = "2.0"
```

**Changes from v1.0**:
- Added `loop_id`, `thread_id` (identity)
- Added `goal_history` (list of GoalExecutionRecord)
- Added `current_goal_index` (active goal tracking)
- Added `total_goals_completed` (loop-level metrics)
- Status changed: goal-scoped (`running`, `completed`, `failed`) → loop-scoped (`running`, `ready_for_next_goal`, `finalized`, `cancelled`)
- **No backward compatibility with v1.0** (fresh start)

---

### GoalExecutionRecord (Per-Goal)

```python
class GoalExecutionRecord(BaseModel):
    """Single goal execution record within a loop (on a specific thread)."""

    # Identity
    goal_id: str  # "{loop_id}_goal_{seq}"
    goal_text: str  # Original goal description
    thread_id: str  # Thread where this goal was executed

    # Execution state
    iteration: int  # Current iteration number (0-based)
    max_iterations: int  # Maximum allowed iterations
    status: Literal["completed", "failed", "cancelled"]  # Goal completion status

    # Execution traces
    reason_history: list[ReasonStepRecord]  # Plan phase decisions (per-goal)
    act_history: list[ActWaveRecord]  # Execute phase waves (per-goal)

    # Goal output
    final_report: str  # Comprehensive final report (generated at completion)
    evidence_summary: str  # Condensed evidence summary

    # Metrics
    duration_ms: int  # Goal execution duration
    tokens_used: int  # Tokens consumed by this goal

    # Timestamps
    started_at: datetime  # Goal start
    completed_at: datetime  # Goal completion (set when finalized)
```

**Goal ID Generation**:
- Format: `{loop_id}_goal_{seq}`
- Example: "L1_goal_0", "L1_goal_1" (goal IDs independent of thread)
- Sequence increments per goal across entire loop (not per-thread)

---

### ThreadHealthMetrics (New Model)

```python
class ThreadHealthMetrics(BaseModel):
    """Current thread health state for switching policy evaluation."""

    thread_id: str  # Thread being monitored
    last_updated: datetime  # Metrics timestamp

    # Message history metrics
    message_count: int  # Total messages in LangGraph checkpoint
    estimated_tokens: int  # Estimated token count for message history
    message_history_size_mb: float  # Message history storage size

    # Execution health metrics
    consecutive_goal_failures: int  # Count of consecutive failed goals on this thread
    last_goal_status: Literal["completed", "failed", "cancelled"] | None  # Previous goal outcome

    # LangGraph checkpoint health
    checkpoint_errors: int  # Count of checkpoint read/write errors
    last_checkpoint_error: str | None  # Last error message
    checkpoint_corruption_detected: bool  # Flag for corruption

    # Subagent execution health
    subagent_timeout_count: int  # Count of subagent timeouts on this thread
    subagent_crash_count: int  # Count of subagent crashes
    last_subagent_error: str | None  # Last error message

    # Custom metrics (extensible)
    custom_metrics: dict[str, Any] = {}  # Policy-specific metrics
```

**Purpose**: Tracks thread health for automatic switching decisions. Extensible design allows custom metrics for policy-specific triggers.

---

### ThreadSwitchPolicy (New Model)

```python
class ThreadSwitchPolicy(BaseModel):
    """Extensible policy for automatic thread switching triggers."""

    # Enabled triggers (configurable)
    message_history_token_threshold: int | None = 100000  # Switch when tokens exceed threshold
    consecutive_goal_failure_threshold: int | None = 3  # Switch after N consecutive failures
    checkpoint_error_threshold: int | None = 2  # Switch after N checkpoint errors
    subagent_timeout_threshold: int | None = 2  # Switch after N subagent timeouts
    
    # Goal-thread relevance analysis (NEW)
    goal_thread_relevance_check_enabled: bool = True  # Enable LLM-based relevance analysis
    relevance_analysis_model: str | None = None  # Model for LLM analysis (None = use default planner model)
    relevance_confidence_threshold: float = 0.7  # Switch if LLM confidence >= threshold that thread hinders goal

    # Switch behavior
    auto_switch_enabled: bool = True  # Enable/disable automatic switching
    max_thread_switches_per_loop: int | None = None  # Limit total switches (None = unlimited)
    knowledge_transfer_limit: int = 10  # Top-K results from /recall on thread switch

    # Custom triggers (extensible)
    custom_triggers: list[CustomSwitchTrigger] = []  # Policy-specific triggers

    # Metadata
    policy_name: str = "default"  # Policy name for configuration
    policy_version: str = "1.0"  # Version for compatibility checks

class CustomSwitchTrigger(BaseModel):
    """Custom thread switching trigger (extensible)."""

    trigger_name: str  # Trigger identifier
    trigger_condition: str  # Condition expression (e.g., "metric.custom_metrics.my_metric > threshold")
    trigger_threshold: float  # Threshold value
    trigger_action: Literal["switch_thread", "alert_user", "log_warning"]  # Action to take

class GoalThreadRelevanceAnalysis(BaseModel):
    """LLM-based analysis of goal-thread relevance."""

    thread_summary: str  # Summary of current thread's goal_history + message themes
    next_goal: str  # Next goal to execute
    
    # LLM response fields
    is_relevant: bool  # True = thread relevant to goal, False = thread irrelevant/hindering
    hindering_reasons: list[str]  # Specific hindering factors detected (goal independence, domain mismatch, pollution)
    confidence: float  # LLM confidence in analysis (0.0-1.0)
    reasoning: str  # LLM's detailed reasoning
    
    # Decision
    should_switch_thread: bool  # True if hindering detected with confidence >= threshold
```

**Policy Design**: Extensible architecture allows adding/removing triggers without changing core logic. Policies can be configured per-loop or globally. Future policies: token budget projection, execution time limits, custom domain-specific triggers.

---

### GoalThreadRelevanceAnalysis (New Trigger)

**Purpose**: LLM-based semantic analysis to determine if current thread context is relevant to next goal execution or may hinder goal completion.

**Trigger Conditions** (LLM evaluates):
1. **Goal independence**: Next goal has NO connection to current thread's previous work (no dependency on thread outputs, no need to reference previous context)
2. **Context domain mismatch**: Current thread's focus/domain contradicts next goal's needs (e.g., thread focused on backend debugging, next goal is frontend UI design)
3. **Message history pollution**: Thread conversation contains irrelevant tangents, off-topic discussions, clutter that distracts from next goal execution

**NOT a Hindering Factor**: Failed execution history (failed attempts can provide valuable learning context, not considered hindering)

**Analysis Process** (LLM prompt structure):

```python
class GoalThreadRelevanceAnalysis(BaseModel):
    """LLM-based analysis of goal-thread relevance."""
    
    thread_summary: str  # Summary of current thread's goal_history + message themes
    next_goal: str  # Next goal to execute
    analysis_prompt: str  # LLM prompt for relevance analysis
    
    # LLM response fields
    is_relevant: bool  # True = thread relevant to goal, False = thread irrelevant/hindering
    hindering_reasons: list[str]  # Specific hindering factors detected
    confidence: float  # LLM confidence in analysis (0.0-1.0)
    reasoning: str  # LLM's detailed reasoning
    
    # Decision
    should_switch_thread: bool  # True if hindering detected with confidence >= threshold
```

**LLM Prompt Template**:

```text
Analyze whether the current thread context is relevant to the next goal execution or may hinder goal completion.

**Current Thread Context Summary**:
{thread_summary}

**Thread Goal History**:
- Goal 1: {goal_1_text} → Status: {goal_1_status}
- Goal 2: {goal_2_text} → Status: {goal_2_status}
...

**Next Goal**: {next_goal}

**Analysis Criteria**:
Evaluate if the current thread context has any of these hindering factors:

1. **Goal Independence**: Does the next goal have NO connection to the thread's previous work?
   - No dependency on thread's outputs or findings
   - No need to reference or build upon previous context
   - Completely independent task

2. **Context Domain Mismatch**: Does the thread's focus/domain contradict the next goal's needs?
   - Thread focused on different domain (e.g., backend vs frontend)
   - Thread's problem-solving approach inappropriate for next goal
   - Context themes conflict with next goal's requirements

3. **Message History Pollution**: Does the thread contain irrelevant/distracting content?
   - Off-topic tangents unrelated to next goal
   - Clutter that doesn't contribute to next goal
   - Distractions that might mislead execution

**Response Format**:
Provide your analysis as structured JSON:

```json
{
  "is_relevant": true/false,
  "hindering_reasons": ["reason1", "reason2", ...],
  "confidence": 0.0-1.0,
  "reasoning": "detailed explanation of analysis",
  "should_switch_thread": true/false
}
```

**Note**: Failed execution attempts are NOT hindering - they provide valuable learning context. Only switch thread if clear hindering factors detected with confidence >= {confidence_threshold}.
```

**Implementation** (in agent_loop.py or new goal_thread_relevance.py):

```python
async def _analyze_goal_thread_relevance(
    self,
    checkpoint: AgentLoopCheckpoint,
    next_goal: str,
    policy: ThreadSwitchPolicy,
    model: BaseChatModel
) -> GoalThreadRelevanceAnalysis:
    """LLM-based analysis of goal-thread relevance for thread switching."""
    
    # Build thread summary (from goal_history + message themes)
    thread_summary = self._build_thread_summary(checkpoint)
    goal_history_text = self._format_goal_history(checkpoint.goal_history)
    
    # Construct LLM prompt
    analysis_prompt = RELEVANCE_PROMPT_TEMPLATE.format(
        thread_summary=thread_summary,
        goal_history=goal_history_text,
        next_goal=next_goal,
        confidence_threshold=policy.relevance_confidence_threshold
    )
    
    # Call LLM for analysis
    response = await model.ainvoke([HumanMessage(content=analysis_prompt)])
    
    # Parse structured response
    analysis_result = parse_llm_analysis_response(response.content)
    
    # Determine should_switch_thread
    analysis_result.should_switch_thread = (
        not analysis_result.is_relevant 
        and analysis_result.confidence >= policy.relevance_confidence_threshold
    )
    
    return analysis_result

def _build_thread_summary(self, checkpoint: AgentLoopCheckpoint) -> str:
    """Build summary of current thread context for relevance analysis."""
    
    # Summarize goal_history themes + domains
    goal_summaries = [
        f"Goal: {g.goal_text}\nOutcome: {g.status}\nDomain: {extract_domain(g.goal_text)}"
        for g in checkpoint.goal_history[-5:]  # Last 5 goals for summary
    ]
    
    # Summarize message themes (optional: use message_history first 10 messages)
    # Could query LangGraph checkpoint for message themes
    
    return "\n".join(goal_summaries)
```

**Integration in Policy Evaluation**:

```python
def _should_switch_thread(
    self, 
    checkpoint: AgentLoopCheckpoint, 
    next_goal: str,
    policy: ThreadSwitchPolicy,
    model: BaseChatModel
) -> tuple[bool, str]:
    """Evaluate thread switching policy including goal-thread relevance."""
    
    # ... existing triggers evaluation (message history, failures, checkpoint errors)
    
    # NEW: Goal-thread relevance analysis
    if policy.goal_thread_relevance_check_enabled:
        relevance_analysis = await self._analyze_goal_thread_relevance(
            checkpoint, next_goal, policy, model
        )
        
        if relevance_analysis.should_switch_thread:
            reasons.append(
                f"Goal-thread relevance: {', '.join(relevance_analysis.hindering_reasons)}"
            )
    
    # ... rest of policy evaluation
```

**Example Scenario**:
- Thread A: Goals focused on backend debugging (goal_0: "fix database connection", goal_1: "optimize SQL queries")
- Next goal: "Design frontend login UI"
- LLM analysis:
  - is_relevant: false
  - hindering_reasons: ["Goal independence (no connection)", "Context domain mismatch (backend vs frontend)"]
  - confidence: 0.85
  - should_switch_thread: true (confidence >= 0.7 threshold)
- Thread switch → Create thread B → Execute frontend UI goal on fresh thread

---

## State Transitions

### New Loop Initialization

**Trigger**: Thread created (first user input)

**Process**:
1. Generate loop_id: UUID or user-specified name (independent of thread_id)
2. Create AgentLoopCheckpoint:
   - `loop_id = generated_loop_id`
   - `thread_ids = [thread_id]`  # First thread
   - `current_thread_id = thread_id`
   - `status = "ready_for_next_goal"`
   - `goal_history = []`
   - `current_goal_index = -1`  # No active goal
   - `working_memory_state = WorkingMemoryState(entries=[], spill_files=[])`
   - `thread_health_metrics = ThreadHealthMetrics(thread_id=thread_id, ...)`
   - `total_goals_completed = 0`
   - `total_thread_switches = 0`
3. Save checkpoint to `SOOTHE_HOME/runs/{loop_id}/agent_loop_checkpoint.json` (indexed by loop_id, not thread_id)

**Next**: User sends first goal → Transition to `running`

---

### Goal Execution Start

**Trigger**: Thread created (first user input)

**Process**:
1. Create AgentLoopCheckpoint:
   - `loop_id = thread_id`
   - `thread_id = thread_id`
   - `status = "ready_for_next_goal"`
   - `goal_history = []`
   - `current_goal_index = -1` (no active goal)
   - `working_memory_state = WorkingMemoryState(entries=[], spill_files=[])`
   - `total_goals_completed = 0`
2. Save checkpoint to `SOOTHE_HOME/runs/{thread_id}/agent_loop_checkpoint.json`

**Next**: User sends first goal → Transition to `running`

---

### Goal Execution Start

**Trigger**: User sends goal on loop with `status=ready_for_next_goal`

**Process**:
1. Load loop checkpoint (by loop_id)
2. Evaluate ThreadSwitchPolicy (check if current thread needs switching)
3. If thread switch triggered → Execute Thread Switch (see below)
4. Generate goal_id: `{loop_id}_goal_{len(goal_history)}`
5. Create GoalExecutionRecord:
   - `goal_id = goal_id`
   - `goal_text = goal`
   - `thread_id = checkpoint.current_thread_id`  # Goal executed on current thread
   - `iteration = 0`
   - `max_iterations = max_iterations`
   - `status = "running"` (implicit)
   - `reason_history = []`
   - `act_history = []`
   - `started_at = now()`
6. Append to `goal_history`
7. Update `current_goal_index = len(goal_history) - 1`
8. Update `status = "running"`
9. Clear `working_memory_state` (fresh working memory for new goal)
10. **Inject previous goal context** (if goal_history has previous goals):
    - Extract previous goal's `final_report`
    - Format as `<previous_goal>` XML block
    - Inject into Plan phase `plan_conversation_excerpts`
11. **Inject thread switch context** (if thread just switched):
    - Auto /recall from previous threads (top-K relevant knowledge)
    - Format as `<recalled_knowledge>` XML blocks
    - Inject into Plan phase `plan_conversation_excerpts`
12. Save checkpoint

**Next**: Enter Plan → Execute loop on current_thread_id

---

### Thread Switch Execution

**Trigger**: ThreadSwitchPolicy evaluation returns `switch_thread=True`

**Pre-conditions**:
- Loop has `status=ready_for_next_goal` (before goal starts)
- ThreadHealthMetrics indicates thread problem (policy triggers met)
- Thread switching not disabled (`auto_switch_enabled=True`)
- Switch limit not exceeded (`total_thread_switches < max_thread_switches_per_loop`)

**Process**:
1. **Log thread switch trigger**: Record reason (message_history_tokens, consecutive_failures, checkpoint_error, etc.)
2. **Create new LangGraph thread**: Call `runner.create_persisted_thread()` → new_thread_id
3. **Update loop checkpoint**:
   - `thread_ids.append(new_thread_id)`  # Add to thread history
   - `current_thread_id = new_thread_id`  # Switch active thread
   - `total_thread_switches += 1`  # Increment switch counter
   - `thread_health_metrics = ThreadHealthMetrics(thread_id=new_thread_id, ...)`  # Fresh metrics
4. **Auto /recall knowledge transfer**:
   - Query previous threads in `thread_ids` (exclude current new thread)
   - Vector search: `goal_text`, `final_report` from previous goal_history
   - Select top-K relevant results (K = policy.knowledge_transfer_limit)
   - Format as `<recalled_knowledge>` blocks
   - Inject into next goal's Plan phase context
5. **Update thread registry**: Register new thread workspace, metadata
6. **Save checkpoint**

**Post-condition**: Loop ready to execute next goal on new_thread_id with essential knowledge from previous threads

**Example**:
- Loop L1 on thread A: message_history_tokens = 105K (threshold=100K)
- Policy triggers switch → Create thread B
- Update loop: thread_ids=["A", "B"], current_thread_id="B", total_thread_switches=1
- Auto /recall: Search thread A's goal_history → Inject top-10 results into thread B's first goal
- Next goal on thread B: Fresh execution context, essential knowledge transferred

---

### Goal Execution Loop

**Trigger**: Loop checkpoint status = `running`

**Process** (existing RFC-200 logic, unchanged):
- Plan phase: Generate PlanResult (status, decision, steps)
- Execute phase: Execute steps via Layer 1 CoreAgent
- Record iteration: Append ReasonStepRecord to `goal_record.reason_history`, ActWaveRecord to `goal_record.act_history`
- Decision: `done` → finalize goal, `continue`/`replan` → next iteration

**Iteration Recording** (modified):
```python
# In state_manager.record_iteration():
goal_record = checkpoint.goal_history[checkpoint.current_goal_index]
goal_record.reason_history.append(reason_record)
goal_record.act_history.append(act_record)
goal_record.iteration += 1
checkpoint.save()
```

---

### Goal Completion

**Trigger**: Plan phase returns `status="done"` (goal achieved)

**Process**:
1. Generate final_report via CoreAgent (existing RFC-211 logic)
2. Update GoalExecutionRecord:
   - `status = "completed"`
   - `final_report = generated_report`
   - `completed_at = now()`
   - `duration_ms = calculated_duration`
   - `tokens_used = calculated_tokens`
3. Update AgentLoopCheckpoint:
   - `status = "ready_for_next_goal"`
   - `total_goals_completed += 1`
   - `total_duration_ms += goal_record.duration_ms`
   - `total_tokens_used += goal_record.tokens_used`
4. Save checkpoint

**Next**: User can send next goal (Loop status=`ready_for_next_goal`) or finalize thread

---

### Thread Finalization

**Trigger**: Loop archived/deleted by user or daemon cleanup

**Process**:
1. Load loop checkpoint
2. Update `status = "finalized"`
3. Save checkpoint
4. Archive all threads in `thread_ids` (mark as archived in thread registry)
5. No more goals accepted on this loop

---

## Thread Health Monitoring

### Metrics Collection

**Timing**: Metrics collected during goal execution and after goal completion

**Collection Process**:
1. **Message history metrics**: Query LangGraph checkpointer for message count, estimated tokens, storage size
2. **Execution health metrics**: Track goal completion status, consecutive failure count
3. **Checkpoint health metrics**: Monitor checkpoint read/write operations, catch errors, detect corruption
4. **Subagent execution metrics**: Track subagent timeouts, crashes via Executor metrics
5. **Update ThreadHealthMetrics**: Store in loop checkpoint, persist after each goal

**Implementation** (in agent_loop.py):

```python
async def _update_thread_health_metrics(self, checkpoint: AgentLoopCheckpoint):
    """Update thread health metrics after goal execution."""
    
    thread_id = checkpoint.current_thread_id
    metrics = checkpoint.thread_health_metrics
    
    # Message history metrics (query LangGraph checkpointer)
    thread_state = await self.core_agent.checkpointer.aget_tuple(
        config={"configurable": {"thread_id": thread_id}}
    )
    metrics.message_count = len(thread_state.channel_values["messages"])
    metrics.estimated_tokens = estimate_token_count(thread_state.channel_values["messages"])
    metrics.message_history_size_mb = calculate_message_size_mb(thread_state)
    
    # Execution health metrics (from goal_history)
    if checkpoint.goal_history:
        last_goal = checkpoint.goal_history[-1]
        metrics.last_goal_status = last_goal.status
        metrics.consecutive_goal_failures = (
            metrics.consecutive_goal_failures + 1 if last_goal.status == "failed"
            else 0  # Reset on success
        )
    
    # Checkpoint health metrics (from state_manager operations)
    metrics.checkpoint_errors = state_manager.get_checkpoint_error_count(thread_id)
    metrics.last_checkpoint_error = state_manager.get_last_checkpoint_error(thread_id)
    metrics.checkpoint_corruption_detected = state_manager.detect_corruption(thread_id)
    
    # Subagent execution metrics (from executor)
    metrics.subagent_timeout_count = executor.get_timeout_count(thread_id)
    metrics.subagent_crash_count = executor.get_crash_count(thread_id)
    metrics.last_subagent_error = executor.get_last_error(thread_id)
    
    metrics.last_updated = datetime.now(UTC)
```

---

### Policy Evaluation

**Timing**: Evaluated before each goal execution start (when `status=ready_for_next_goal`)

**Evaluation Logic** (in agent_loop.py):

```python
def _should_switch_thread(
    self, 
    checkpoint: AgentLoopCheckpoint, 
    policy: ThreadSwitchPolicy
) -> tuple[bool, str]:
    """Evaluate thread switching policy. Returns (should_switch, reason)."""
    
    if not policy.auto_switch_enabled:
        return False, "Auto-switch disabled"
    
    if policy.max_thread_switches_per_loop is not None:
        if checkpoint.total_thread_switches >= policy.max_thread_switches_per_loop:
            return False, "Thread switch limit reached"
    
    metrics = checkpoint.thread_health_metrics
    reasons = []
    
    # Check message history threshold
    if policy.message_history_token_threshold:
        if metrics.estimated_tokens > policy.message_history_token_threshold:
            reasons.append(
                f"Message history tokens ({metrics.estimated_tokens}) > threshold ({policy.message_history_token_threshold})"
            )
    
    # Check consecutive goal failures
    if policy.consecutive_goal_failure_threshold:
        if metrics.consecutive_goal_failures >= policy.consecutive_goal_failure_threshold:
            reasons.append(
                f"Consecutive goal failures ({metrics.consecutive_goal_failures}) >= threshold ({policy.consecutive_goal_failure_threshold})"
            )
    
    # Check checkpoint errors
    if policy.checkpoint_error_threshold:
        if metrics.checkpoint_errors >= policy.checkpoint_error_threshold:
            reasons.append(
                f"Checkpoint errors ({metrics.checkpoint_errors}) >= threshold ({policy.checkpoint_error_threshold})"
            )
    
    # Check subagent timeout threshold
    if policy.subagent_timeout_threshold:
        if metrics.subagent_timeout_count >= policy.subagent_timeout_threshold:
            reasons.append(
                f"Subagent timeouts ({metrics.subagent_timeout_count}) >= threshold ({policy.subagent_timeout_threshold})"
            )
    
    # Check checkpoint corruption
    if metrics.checkpoint_corruption_detected:
        reasons.append("Checkpoint corruption detected")
    
    # NEW: Goal-thread relevance analysis (LLM-based)
    if policy.goal_thread_relevance_check_enabled and next_goal:
        relevance_analysis = await self._analyze_goal_thread_relevance(
            checkpoint, next_goal, policy, model
        )
        
        if relevance_analysis.should_switch_thread:
            reasons.append(
                f"Goal-thread relevance: {', '.join(relevance_analysis.hindering_reasons)}"
            )
    
    # Evaluate custom triggers (extensible)
    for custom_trigger in policy.custom_triggers:
        if self._evaluate_custom_trigger(metrics, custom_trigger):
            reasons.append(f"Custom trigger: {custom_trigger.trigger_name}")
    
    should_switch = len(reasons) > 0
    reason_str = "; ".join(reasons) if reasons else "No trigger met"
    
    return should_switch, reason_str
```

---

### Goal-Thread Relevance Analysis Implementation

**Purpose**: LLM-based semantic analysis to determine if current thread context is relevant to next goal execution or may hinder goal completion.

**Trigger Conditions** (LLM evaluates):
1. **Goal independence**: Next goal has NO connection to current thread's previous work (no dependency on thread outputs, no need to reference previous context)
2. **Context domain mismatch**: Current thread's focus/domain contradicts next goal's needs (e.g., thread focused on backend debugging, next goal is frontend UI design)
3. **Message history pollution**: Thread conversation contains irrelevant tangents, off-topic discussions, clutter that distracts from next goal execution

**NOT a Hindering Factor**: Failed execution history (failed attempts provide valuable learning context, not considered hindering)

**LLM Prompt Template**:

```text
Analyze whether the current thread context is relevant to the next goal execution or may hinder goal completion.

**Current Thread Context Summary**:
{thread_summary}

**Thread Goal History**:
{goal_history_text}

**Next Goal**: {next_goal}

**Analysis Criteria**:
Evaluate if the current thread context has any of these hindering factors:

1. **Goal Independence**: Does the next goal have NO connection to the thread's previous work?
   - No dependency on thread's outputs or findings
   - No need to reference or build upon previous context
   - Completely independent task

2. **Context Domain Mismatch**: Does the thread's focus/domain contradict the next goal's needs?
   - Thread focused on different domain (e.g., backend vs frontend)
   - Thread's problem-solving approach inappropriate for next goal
   - Context themes conflict with next goal's requirements

3. **Message History Pollution**: Does the thread contain irrelevant/distracting content?
   - Off-topic tangents unrelated to next goal
   - Clutter that doesn't contribute to next goal
   - Distractions that might mislead execution

**Response Format**:
Provide your analysis as structured JSON:

```json
{
  "is_relevant": true/false,
  "hindering_reasons": ["reason1", "reason2", ...],
  "confidence": 0.0-1.0,
  "reasoning": "detailed explanation of analysis",
  "should_switch_thread": true/false
}
```

**Note**: Failed execution attempts are NOT hindering - they provide valuable learning context. Only switch thread if clear hindering factors detected with confidence >= {confidence_threshold}.
```

**Implementation** (in new file `goal_thread_relevance.py` or agent_loop.py):

```python
async def _analyze_goal_thread_relevance(
    self,
    checkpoint: AgentLoopCheckpoint,
    next_goal: str,
    policy: ThreadSwitchPolicy,
    model: BaseChatModel
) -> GoalThreadRelevanceAnalysis:
    """LLM-based analysis of goal-thread relevance for thread switching."""
    
    # Build thread summary (from goal_history + message themes)
    thread_summary = self._build_thread_summary(checkpoint)
    goal_history_text = self._format_goal_history(checkpoint.goal_history[-5:])  # Last 5 goals
    
    # Construct LLM prompt
    analysis_prompt = RELEVANCE_PROMPT_TEMPLATE.format(
        thread_summary=thread_summary,
        goal_history_text=goal_history_text,
        next_goal=next_goal,
        confidence_threshold=policy.relevance_confidence_threshold
    )
    
    # Call LLM for analysis
    response = await model.ainvoke([HumanMessage(content=analysis_prompt)])
    
    # Parse structured response (extract JSON from response content)
    analysis_result = parse_llm_analysis_response(response.content)
    
    # Determine should_switch_thread
    analysis_result.should_switch_thread = (
        not analysis_result.is_relevant 
        and analysis_result.confidence >= policy.relevance_confidence_threshold
    )
    
    return analysis_result

def _build_thread_summary(self, checkpoint: AgentLoopCheckpoint) -> str:
    """Build summary of current thread context for relevance analysis."""
    
    # Summarize goal_history themes + domains
    goal_summaries = [
        f"Goal: {g.goal_text}\nOutcome: {g.status}\nDomain: {extract_domain_keywords(g.goal_text)}"
        for g in checkpoint.goal_history[-5:]  # Last 5 goals for summary
    ]
    
    # Extract thread domain focus (from goal themes)
    thread_domains = extract_thread_domains(checkpoint.goal_history)
    
    summary = f"Thread Domain Focus: {', '.join(thread_domains)}\n\n" + "\n".join(goal_summaries)
    
    return summary

def _format_goal_history(self, goal_history: list[GoalExecutionRecord]) -> str:
    """Format goal_history for LLM prompt."""
    
    formatted = []
    for idx, goal in enumerate(goal_history):
        formatted.append(
            f"- Goal {idx}: {goal.goal_text} → Status: {goal.status}, Thread: {goal.thread_id}"
        )
    
    return "\n".join(formatted)

def parse_llm_analysis_response(response_content: str) -> GoalThreadRelevanceAnalysis:
    """Parse LLM structured JSON response into GoalThreadRelevanceAnalysis."""
    
    # Extract JSON from response (handle markdown code blocks, etc.)
    json_match = extract_json_from_response(response_content)
    
    if json_match:
        data = json.loads(json_match)
        return GoalThreadRelevanceAnalysis(
            is_relevant=data.get("is_relevant", True),
            hindering_reasons=data.get("hindering_reasons", []),
            confidence=data.get("confidence", 0.0),
            reasoning=data.get("reasoning", ""),
            should_switch_thread=data.get("should_switch_thread", False),
            thread_summary="",  # Not needed in response
            next_goal=""  # Not needed in response
        )
    else:
        # Fallback: if JSON not found, parse response text
        return parse_text_analysis_response(response_content)
```

**Example Scenario**:

- **Thread A**: Goals focused on backend debugging
  - goal_0: "Fix database connection pool leak" → completed
  - goal_1: "Optimize SQL query performance" → completed
  - Thread domain focus: backend, database, performance optimization

- **Next goal**: "Design frontend login UI with modern React components"

- **LLM analysis**:
  - is_relevant: false
  - hindering_reasons: [
      "Goal independence: Next goal has no dependency on backend/database work",
      "Context domain mismatch: Thread focused on backend debugging, next goal is frontend UI design"
    ]
  - confidence: 0.85
  - reasoning: "The thread's backend debugging context provides no value for frontend UI design. Backend optimization knowledge doesn't help with React component design. Message history contains database queries, connection pool discussions - irrelevant to frontend work. Fresh thread recommended for clean frontend context."
  - should_switch_thread: true (confidence 0.85 >= threshold 0.7)

- **Thread switch**: Create thread B → Execute frontend UI goal on fresh thread → Avoid backend context pollution

**Performance Considerations**:
- LLM call adds latency (500-1500ms depending on model)
- Optional: Cache previous relevance analyses (if same goal pattern repeats)
- Future optimization: Use smaller/faster model for relevance check (e.g., Haiku instead of Sonnet)

**Configuration Options**:
- Disable check: `goal_thread_relevance_check_enabled: false` (skip LLM analysis)
- Adjust threshold: Lower threshold (0.5) → more aggressive thread switching, Higher threshold (0.9) → conservative switching
- Custom model: Use specific model for analysis (e.g., lighter Haiku model for faster checks)

**Custom Trigger Evaluation** (extensible):

```python
def _evaluate_custom_trigger(
    self, 
    metrics: ThreadHealthMetrics, 
    trigger: CustomSwitchTrigger
) -> bool:
    """Evaluate custom trigger condition (extensible policy)."""
    
    # Simple expression evaluation (e.g., "metric.custom_metrics.my_metric > threshold")
    # Could use safe expression parser or predefined operators
    try:
        condition_value = self._extract_metric_value(metrics, trigger.trigger_condition)
        return condition_value > trigger.trigger_threshold
    except Exception as e:
        logger.warning(f"Custom trigger evaluation failed: {e}")
        return False
```

---

## Thread Switching Knowledge Transfer

### Auto /recall on Thread Switch

**Trigger**: Thread switch execution (see Thread Switch Execution process)

**Purpose**: Transfer essential knowledge from previous threads to new thread's execution context

**Mechanism**: Automatic semantic search + injection into Plan phase

**Process**:
1. Identify previous threads: `checkpoint.thread_ids[:-1]` (exclude current new thread)
2. Build searchable corpus:
   - For each previous thread's goal_history: Extract `goal_text`, `final_report`
   - For each goal: Combine into searchable document: `"{goal_text}\n{final_report}"`
3. Vector search:
   - Query: Current goal text (if available) or generic "essential knowledge from previous work"
   - Corpus: All previous goal documents
   - Top-K: `policy.knowledge_transfer_limit` (default: 10)
4. Format results:
   - Each match → `<recalled_knowledge>` XML block
   - Include thread_id, goal_text, final_report excerpt
5. Inject into Plan phase:
   - Append to `plan_conversation_excerpts`
   - Plan phase receives essential context from previous threads

**Implementation** (in agent_loop.py or state_manager.py):

```python
def _auto_recall_on_thread_switch(
    self, 
    checkpoint: AgentLoopCheckpoint, 
    current_goal: str | None,
    policy: ThreadSwitchPolicy,
    vector_store: VectorStoreProtocol
) -> list[str]:
    """Auto /recall knowledge from previous threads during thread switch."""
    
    previous_thread_ids = checkpoint.thread_ids[:-1]  # Exclude current new thread
    
    # Build searchable corpus from previous goal_history
    documents = []
    for goal_record in checkpoint.goal_history:
        if goal_record.thread_id in previous_thread_ids:
            doc_text = f"{goal_record.goal_text}\n{goal_record.final_report}"
            documents.append({
                "thread_id": goal_record.thread_id,
                "goal_id": goal_record.goal_id,
                "goal_text": goal_record.goal_text,
                "text": doc_text
            })
    
    if not documents:
        return []  # No previous goals to recall
    
    # Vector search
    query = current_goal or "essential knowledge from previous work on this loop"
    results = await vector_store.similarity_search(
        query=query,
        documents=[doc["text"] for doc in documents],
        top_k=policy.knowledge_transfer_limit
    )
    
    # Format as context excerpts
    context_excerpts = []
    for result in results[:policy.knowledge_transfer_limit]:
        # Find matching document
        matched_doc = documents[result.index]
        excerpt = (
            f"<recalled_knowledge>\n"
            f"From thread {matched_doc['thread_id']}, goal: {matched_doc['goal_text']}\n"
            f"Output:\n{matched_doc['goal_text']}\n{result.text[:500]}...\n"  # Truncate if large
            f"</recalled_knowledge>"
        )
        context_excerpts.append(excerpt)
    
    return context_excerpts
```

**Example**:
- Thread A: 2 goals completed (goal_0: "analyze project structure", goal_1: "count readme files")
- Thread switch to thread B triggered (message history too large)
- Auto /recall: Vector search across goal_0, goal_1 final_reports
- Top-10 results injected into thread B's first goal Plan phase
- Thread B goal_2: "translate to chinese" → Receives previous project analysis + readme count context

**Note**: Auto /recall only happens on thread switch, not every goal. Same-thread goals use previous_goal injection (see below).

---

## Same-Thread Goal Continuation

### Problem

"translate to chinese" on same thread where "count readme files" completed should see previous final_report.

### Solution

**Context Injection**: When new goal starts on thread with previous completed goal, inject previous goal's final_report into Plan phase.

**Implementation** (in agent_loop.py):

```python
async def run_with_progress(self, goal: str, thread_id: str, ...):
    state_manager = AgentLoopStateManager(thread_id)
    checkpoint = state_manager.load()

    # New goal on existing loop
    if checkpoint and checkpoint.status == "ready_for_next_goal":
        # Extract previous goal's final report
        if checkpoint.goal_history:
            previous_goal = checkpoint.goal_history[checkpoint.current_goal_index]
            plan_excerpts = [
                f"<previous_goal>\n"
                f"Goal: {previous_goal.goal_text}\n"
                f"Status: {previous_goal.status}\n"
                f"Output:\n{previous_goal.final_report}\n"
                f"</previous_goal>"
            ]
        else:
            plan_excerpts = []  # First goal on this thread

        # Create new goal record
        new_goal_record = state_manager.start_new_goal(goal, max_iterations)
        checkpoint.goal_history.append(new_goal_record)
        checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
        checkpoint.status = "running"
        state_manager.save(checkpoint)

    # New thread, new loop
    elif not checkpoint:
        checkpoint = state_manager.initialize(thread_id)
        new_goal_record = state_manager.start_new_goal(goal, max_iterations)
        checkpoint.goal_history.append(new_goal_record)
        checkpoint.current_goal_index = 0
        checkpoint.status = "running"
        plan_excerpts = []
        state_manager.save(checkpoint)

    # Recovery: Loop running (mid-execution crash)
    elif checkpoint.status == "running":
        goal_record = checkpoint.goal_history[checkpoint.current_goal_index]
        # ... recovery logic (derive prior outputs from goal_record.act_history)
        plan_excerpts = state_manager.derive_plan_conversation(checkpoint)

    # Initialize LoopState with plan_conversation_excerpts
    state = LoopState(
        goal=goal,
        thread_id=thread_id,
        iteration=goal_record.iteration,
        plan_conversation_excerpts=plan_excerpts,  # Injected context
        ...
    )

    # Main Plan → Execute loop
    while goal_record.iteration < goal_record.max_iterations:
        # ... existing logic

    # Goal completed
    final_report = await self._generate_final_report(...)
    state_manager.finalize_goal(goal_record, final_report)
    checkpoint.status = "ready_for_next_goal"
    state_manager.save(checkpoint)
```

**Plan Phase Behavior**:
- Reason receives `<previous_goal>` XML block in `plan_conversation_excerpts`
- Can reference previous outputs: "The previous goal produced X, I will translate it to Chinese"
- Decision: Execute step with subagent="claude", step description="Translate previous final report to Chinese"

---

## Cross-Thread /recall Command

### Mechanism

**Trigger**: User sends `/recall {query}` command

**Process**:
1. Parse `/recall` command (extract query, e.g., "previous translation work")
2. Vector search across:
   - **Loop checkpoints**: All threads, match on `goal_text`, `final_report`, `reason_history.reasoning`
   - **MemoryProtocol**: Memorized facts (existing RFC-002)
3. Rank results by semantic similarity
4. Select top-K matches (default: 10)
5. Inject into current loop's Plan phase as `<recalled_knowledge>` blocks

---

### Implementation

**CLI Handler** (in daemon message_router.py or new recall_handler.py):

```python
async def handle_recall_command(query: str, current_thread_id: str, config: SootheConfig):
    """Handle /recall command - search across all loop checkpoints + MemoryProtocol."""

    # 1. Discover all loop checkpoints
    all_checkpoints = discover_all_loop_checkpoints()  # Scan SOOTHE_HOME/runs/

    # 2. Search loop checkpoints
    loop_matches = []
    for checkpoint in all_checkpoints:
        for goal_record in checkpoint.goal_history:
            # Combine searchable text
            searchable_text = f"{goal_record.goal_text}\n{goal_record.final_report}"
            for reason in goal_record.reason_history:
                searchable_text += f"\n{reason.reasoning}"

            # Vector similarity search
            similarity = await vector_store.similarity_search(
                query=query,
                documents=[searchable_text],
                top_k=1
            )

            if similarity.score > THRESHOLD:
                loop_matches.append({
                    "thread_id": checkpoint.thread_id,
                    "goal_id": goal_record.goal_id,
                    "goal_text": goal_record.goal_text,
                    "final_report": goal_record.final_report,
                    "similarity": similarity.score,
                })

    # 3. Search MemoryProtocol
    memory_matches = await memory_protocol.search(query, limit=5)

    # 4. Combine + rank
    ranked_matches = combine_and_rank(loop_matches, memory_matches, limit=10)

    # 5. Format as context excerpts
    context_excerpts = []
    for match in ranked_matches:
        if "thread_id" in match:  # Loop checkpoint match
            excerpt = (
                f"<recalled_knowledge>\n"
                f"From thread {match['thread_id']}, goal: {match['goal_text']}\n"
                f"Output:\n{match['final_report']}\n"
                f"</recalled_knowledge>"
            )
        else:  # MemoryProtocol match
            excerpt = (
                f"<recalled_memory>\n"
                f"{match['content']}\n"
                f"</recalled_memory>"
            )
        context_excerpts.append(excerpt)

    return context_excerpts
```

**Checkpoint Discovery**:

```python
def discover_all_loop_checkpoints() -> list[AgentLoopCheckpoint]:
    """Scan SOOTHE_HOME/runs/ for all loop checkpoints."""
    runs_dir = Path(SOOTHE_HOME) / "runs"
    checkpoints = []

    for thread_dir in runs_dir.iterdir():
        if thread_dir.is_dir():
            checkpoint_path = thread_dir / "agent_loop_checkpoint.json"
            if checkpoint_path.exists():
                data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                checkpoint = AgentLoopCheckpoint.model_validate(data)
                checkpoints.append(checkpoint)

    return checkpoints
```

**Vector Store Integration**:

- Use `VectorStoreProtocol` (RFC-103, existing implementation)
- Embedding: Use configured embedding model (same as ContextProtocol)
- Search: `similarity_search(query, documents, top_k)`
- Indexing: Build index on checkpoint load (cache embeddings for efficiency)

---

### Integration with AgentLoop

**Query Engine** (in daemon query_engine.py):

```python
async def run_query(self, text: str, ...):
    # Detect /recall command
    if text.startswith("/recall "):
        query = text[len("/recall "):].strip()

        # Handle /recall
        context_excerpts = await handle_recall_command(query, thread_id, self._config)

        # Inject into agent loop
        stream_kwargs["recall_context"] = context_excerpts

    # Normal query handling
    async for chunk in d._runner.astream(text, **stream_kwargs):
        # ... existing logic
```

**AgentLoop Runner** (in core/runner/_runner_agentic.py):

```python
async def astream(self, text: str, recall_context: list[str] | None = None, ...):
    # Pass recall context to agent loop
    async for event in agent_loop.run_with_progress(
        goal=text,
        thread_id=thread_id,
        recall_context=recall_context,  # Injected by /recall
        ...
    ):
        # ... existing logic
```

**AgentLoop** (in agent_loop.py):

```python
async def run_with_progress(self, goal: str, recall_context: list[str] | None = None, ...):
    # ... checkpoint loading

    # Combine plan_excerpts (previous goal + recall context)
    plan_excerpts = plan_excerpts or []
    if recall_context:
        plan_excerpts.extend(recall_context)

    # Initialize state with combined context
    state = LoopState(
        goal=goal,
        plan_conversation_excerpts=plan_excerpts,
        ...
    )
```

---

## Working Memory Strategy

### Decision

**Clear working memory per-goal, preserve spill files in GoalExecutionRecord**

### Reasoning

**Why clear per-goal**:
- Each goal has focused working memory (no pollution from previous goal's steps)
- Previous outputs accessible via `/recall` (search final_report, not working memory)
- Simpler implementation (reset WorkingMemoryState on `start_new_goal()`)
- Clear mental model: working memory = current goal's execution state

**Why preserve spill files**:
- Large outputs saved in spill files (step-{goal_id}-{step_id}-{seq}.md)
- GoalExecutionRecord can reference spill files for large outputs
- `/recall` can load spill files if needed (future: searchable spill file content)

---

### Implementation

**State Manager** (in state_manager.py):

```python
def start_new_goal(self, goal: str, max_iterations: int) -> GoalExecutionRecord:
    """Create new goal record and clear working memory."""

    checkpoint = self._checkpoint
    goal_id = f"{checkpoint.thread_id}_goal_{len(checkpoint.goal_history)}"

    goal_record = GoalExecutionRecord(
        goal_id=goal_id,
        goal_text=goal,
        iteration=0,
        max_iterations=max_iterations,
        status="running",  # Implicit
        reason_history=[],
        act_history=[],
        final_report="",
        evidence_summary="",
        duration_ms=0,
        tokens_used=0,
        started_at=datetime.now(UTC),
        completed_at=None,
    )

    # Clear working memory for new goal
    checkpoint.working_memory_state = WorkingMemoryState(
        entries=[],
        spill_files=[]
    )

    return goal_record
```

**Spill File Naming**:
- Current: `step-{step_id}-{seq}.md` (RFC-203)
- Modified: `step-{goal_id}-{step_id}-{seq}.md` (e.g., "step-5ru93n8luabj_goal_0-step_001-1.md")
- Associates spill files with specific goal

---

## Module Organization

### File Changes

**checkpoint.py**:
- Add `GoalExecutionRecord` model (include `thread_id` field)
- Add `ThreadHealthMetrics` model (new)
- Add `ThreadSwitchPolicy` model (new)
- Add `CustomSwitchTrigger` model (new)
- Extend `AgentLoopCheckpoint` model (loop_id, thread_ids, current_thread_id, thread_health_metrics, total_thread_switches)
- Update schema_version to "2.0"

**state_manager.py**:
- Update `initialize(loop_id, thread_id) → AgentLoopCheckpoint` (loop_id as primary key)
- Update `load(loop_id) → AgentLoopCheckpoint` (load by loop_id, not thread_id)
- Update `save(checkpoint)` → Save to `SOOTHE_HOME/runs/{loop_id}/agent_loop_checkpoint.json`
- Add `start_new_goal(goal, max_iterations) → GoalExecutionRecord`
- Add `finalize_goal(goal_record, final_report)`
- Add `inject_previous_goal_context(checkpoint) → list[str]`
- Add `auto_recall_on_thread_switch(checkpoint, current_goal, policy) → list[str]` (new)
- Add `execute_thread_switch(checkpoint, runner) → new_thread_id` (new)
- Update `record_iteration()` (records to GoalExecutionRecord, update thread_health_metrics)

**agent_loop.py**:
- Modify `run_with_progress()`:
  - Accept `loop_id` parameter (primary key, not thread_id)
  - Evaluate ThreadSwitchPolicy before goal start
  - Execute thread switch if triggered
  - Inject previous goal context + auto /recall context
  - Create new goal record via `start_new_goal()`
  - Update thread_health_metrics after goal completion
  - Finalize goal via `finalize_goal()`
- Add `_should_switch_thread(checkpoint, policy) → (bool, str)` (new)
- Add `_execute_thread_switch(checkpoint, runner)` (new)
- Add `_update_thread_health_metrics(checkpoint)` (new)
- Add `_auto_recall_on_thread_switch(...)` (new)
- Add `recall_context` parameter handling

**thread_registry.py** (new or update daemon thread_registry):
- Add `create_thread_for_loop(loop_id) → thread_id` (create new thread for existing loop)
- Update thread-loop binding tracking (thread_id → loop_id mapping)

**query_engine.py** (or new **recall_handler.py**):
- Add `/recall` command detection
- Add `handle_recall_command()` function
- Integrate with VectorStoreProtocol and MemoryProtocol

**thread_switch_policy.py** (new file):
- Add `ThreadSwitchPolicyManager` class (manage policy configuration, evaluation)
- Add policy configuration loader (load from config.yml or defaults)
- Add policy extensibility hooks (custom trigger registration)

**VectorStoreProtocol Integration**:
- Use existing VectorStoreProtocol implementation (PGVector/Weaviate)
- Add checkpoint embedding indexing (index goal_history for /recall)
- Add thread health metrics custom embedding (optional, for custom triggers)

---

## Storage Location

**File Path**: Indexed by loop_id (not thread_id), goal_history spans multiple threads

```
SOOTHE_HOME/
  runs/
    {loop_id}/  # Loop checkpoint indexed by loop_id (e.g., "L1_abc123")
      agent_loop_checkpoint.json  # Loop checkpoint (v2.0 schema, spans multiple threads)
      loop/
        step-{goal_id}-{step_id}-{seq}.md  # Working memory spill files (goal_id includes loop_id)
    
    {thread_A}/  # LangGraph thread directories (managed by LangGraph checkpointer)
      checkpoint.json  # LangGraph checkpoint (message history, execution state)
      ...
    
    {thread_B}/  # Another thread (if loop switched threads)
      checkpoint.json
      ...
```

**Key Changes**:
- Loop checkpoint file indexed by `loop_id` (independent of thread_id)
- Loop checkpoint spans multiple threads (goal_history includes goals from all threads)
- LangGraph thread checkpoints managed separately (by LangGraph checkpointer, not loop checkpoint)
- Thread directories created by daemon thread registry (standard LangGraph structure)

**Checkpoint Cross-Reference**:
- Loop checkpoint references threads in `thread_ids` list
- GoalExecutionRecord includes `thread_id` field (which thread executed that goal)
- Thread health metrics tracked per thread (but stored in loop checkpoint)

**File Size Management**:
- Loop checkpoint file grows with multiple goals + thread switches
- Typical: 1-10 goals per loop, 1-3 thread switches (manageable size)
- Future optimization: Compress old goal_history entries (keep summaries, remove full final_reports for old goals)

---

---

## Error Handling

### Invalid Status Transitions

**Case**: User sends goal when `status=finalized` or `status=cancelled`

**Handling**:
- Reject goal with error event: "Thread is finalized/cancelled, cannot accept new goals"
- Suggest creating new thread

**Case**: Recovery when `status=running` but goal_history empty or current_goal_index invalid

**Handling**:
- Treat as corrupt checkpoint
- Initialize new loop, log warning

---

### Goal Failure

**Case**: Goal execution fails (max iterations exceeded, unhandled error)

**Handling**:
- Mark GoalExecutionRecord status="failed"
- Update loop status="ready_for_next_goal" (allow retry with new goal)
- Preserve failed goal_record in goal_history (accessible via /recall)
- Generate failure report: "Goal failed after N iterations, reason: ..."

---

### Checkpoint Corruption

**Case**: JSON file corrupted, schema validation fails

**Handling**:
- Log error, attempt recovery from backup (if exists)
- If unrecoverable: Initialize new loop, log warning
- Preserve corrupted file as `agent_loop_checkpoint.json.corrupted`

---

## Testing Strategy

### Unit Tests

**State Manager (Multi-Thread)**:
- Test `initialize(loop_id, thread_id)` creates loop with loop_id independent of thread_id
- Test `load(loop_id)` loads checkpoint by loop_id (not thread_id)
- Test `execute_thread_switch()` creates new thread, updates thread_ids, current_thread_id
- Test `auto_recall_on_thread_switch()` extracts knowledge from previous threads
- Test `start_new_goal()` creates GoalExecutionRecord with correct thread_id
- Test `finalize_goal()` marks goal completed, updates metrics
- Test `inject_previous_goal_context()` formats previous goal correctly
- Test thread_health_metrics update logic

**Thread Switch Policy**:
- Test `_should_switch_thread()` evaluation for each trigger:
  - message_history_token_threshold
  - consecutive_goal_failure_threshold
  - checkpoint_error_threshold
  - subagent_timeout_threshold
  - checkpoint_corruption_detected
- Test custom trigger evaluation
- Test policy configuration loading
- Test auto_switch_enabled/disable logic
- Test max_thread_switches_per_loop limit

**AgentLoop (Multi-Thread)**:
- Test new loop → goal → completion flow (single thread)
- Test same-thread goal continuation (previous goal context injection)
- Test thread switch triggered (message history threshold)
- Test thread switch execution (create new thread, auto /recall)
- Test goal execution on switched thread (fresh context)
- Test recovery from status=running (mid-execution crash on specific thread)
- Test recovery from status=ready_for_next_goal (thread switch happened)

**Recall Handler**:
- Test `/recall` command parsing
- Test checkpoint discovery across loops (indexed by loop_id)
- Test vector search integration
- Test memory + checkpoint result combination

---

### Integration Tests

**Same-Thread Goal Continuation**:
- Goal 1 on thread A: "count readme files" → Complete → final_report saved
- Goal 2 on thread A: "translate to chinese" → Plan phase receives Goal 1 final_report
- Verify translation output references Goal 1 content

**Thread Switch (Message History Threshold)**:
- Loop L1 on thread A: Execute goals until message_history_tokens > threshold
- Thread switch triggered → Create thread B
- Verify loop checkpoint: thread_ids=["A", "B"], current_thread_id="B", total_thread_switches=1
- Verify auto /recall: Thread B Plan phase receives knowledge from thread A goals

**Thread Switch (Consecutive Failures)**:
- Loop L1 on thread A: 3 consecutive failed goals
- Thread switch triggered → Create thread B
- Goal on thread B succeeds (fresh execution context)
- Verify consecutive_goal_failures reset on thread B

**Auto /recall on Thread Switch**:
- Thread A: 2 goals completed (goal_0, goal_1)
- Thread switch to thread B → Auto /recall searches goal_0, goal_1
- Verify top-K results injected into thread B's first goal Plan phase
- Verify knowledge transfer limited by knowledge_transfer_limit

**Cross-Thread /recall Command**:
- Loop L1 on thread A: Goal "analyze project structure" → Complete
- Loop L1 switched to thread B → `/recall previous analysis` → Search thread A checkpoint
- Verify thread B Plan phase receives thread A final_report

**Working Memory Clearing (Multi-Thread)**:
- Thread A: Goal 1 → Working memory populated
- Thread switch → Thread B: Goal 2 → Working memory cleared
- Verify Goal 2 working memory independent from Goal 1 (even across thread switch)

---

### Edge Cases

- First goal on new loop (empty goal_history)
- First goal on switched thread (auto /recall from previous thread)
- Multiple thread switches (thread_ids = ["A", "B", "C"])
- Thread switch disabled (auto_switch_enabled=False, triggers ignored)
- Thread switch limit reached (max_thread_switches_per_loop exceeded)
- Failed goal in goal_history (status="failed", thread switch triggered?)
- Very large final_report (truncation in auto /recall)
- /recall with no matches (return empty context excerpts)
- Thread health metrics collection error (graceful degradation)
- Custom trigger evaluation failure (log warning, continue)

---

## Implementation Tasks

### Phase 1: Schema & State Manager (core multi-thread architecture)

**Tasks**:
1. Add `GoalExecutionRecord` model to `checkpoint.py` (include `thread_id` field)
2. Add `ThreadHealthMetrics` model to `checkpoint.py` (new)
3. Add `ThreadSwitchPolicy` model to `checkpoint.py` (new)
4. Add `CustomSwitchTrigger` model to `checkpoint.py` (new)
5. Extend `AgentLoopCheckpoint` schema in `checkpoint.py`:
   - `loop_id` (independent of thread_id)
   - `thread_ids` (list of all threads)
   - `current_thread_id` (active thread)
   - `thread_health_metrics` (thread health state)
   - `total_thread_switches` (switch counter)
6. Update `AgentLoopStateManager.initialize(loop_id, thread_id)` (loop_id as primary key)
7. Update `AgentLoopStateManager.load(loop_id)` (load by loop_id, not thread_id)
8. Update `AgentLoopStateManager.save()` → Save to `{loop_id}/agent_loop_checkpoint.json`
9. Add `AgentLoopStateManager.start_new_goal()`
10. Add `AgentLoopStateManager.finalize_goal()`
11. Add `AgentLoopStateManager.inject_previous_goal_context()`
12. Add `AgentLoopStateManager.auto_recall_on_thread_switch()` (new)
13. Add `AgentLoopStateManager.execute_thread_switch()` (new)
14. Update `AgentLoopStateManager.record_iteration()` (update thread_health_metrics)
15. Update schema_version to "2.0"

**Files**:
- `packages/soothe/src/soothe/cognition/agent_loop/checkpoint.py`
- `packages/soothe/src/soothe/cognition/agent_loop/state_manager.py`

---

### Phase 2: Thread Switching Policy

**Tasks**:
1. Create `thread_switch_policy.py` (new file)
2. Add `ThreadSwitchPolicyManager` class (manage policy configuration)
3. Add policy evaluation logic (check thresholds, custom triggers)
4. Add policy configuration loader (load from config.yml)
5. Add custom trigger extensibility hooks (register custom triggers)
6. Integrate with AgentLoop (evaluate policy before goal start)

**Files**:
- `packages/soothe/src/soothe/cognition/agent_loop/thread_switch_policy.py` (new)
- `packages/soothe/src/soothe/config/models.py` (add ThreadSwitchPolicy config section)

---

### Phase 3: AgentLoop Integration (multi-thread execution)

**Tasks**:
1. Modify `AgentLoop.run_with_progress()`:
   - Accept `loop_id` parameter (primary key)
   - Evaluate ThreadSwitchPolicy before goal start
   - Execute thread switch if triggered (create new thread, update checkpoint)
   - Auto /recall on thread switch (inject knowledge from previous threads)
   - Inject previous goal context (same-thread continuation)
   - Create new goal record via `start_new_goal()`
   - Update thread_health_metrics after goal completion
   - Finalize goal via `finalize_goal()`
2. Add `_should_switch_thread(checkpoint, policy) → (bool, str)`
3. Add `_execute_thread_switch(checkpoint, runner)`
4. Add `_update_thread_health_metrics(checkpoint)`
5. Add `_auto_recall_on_thread_switch(...)`
6. Add `recall_context` parameter handling
7. Clear working memory on goal start
8. Update thread_registry integration (create_thread_for_loop)

**Files**:
- `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py`
- `packages/soothe/src/soothe/daemon/thread_registry.py` (add create_thread_for_loop)

---

### Phase 4: /recall Command (cross-thread knowledge)

**Tasks**:
1. Add `/recall` command detection in query_engine.py or daemon message_router.py
2. Implement `handle_recall_command()` function
3. Add checkpoint discovery (scan SOOTHE_HOME/runs/{loop_id}/)
4. Integrate VectorStoreProtocol for semantic search
5. Combine MemoryProtocol + checkpoint results
6. Inject recalled knowledge into agent loop
7. Support thread filtering (optional: limit search to specific threads)

**Files**:
- `packages/soothe/src/soothe/daemon/query_engine.py` (or new `recall_handler.py`)
- `packages/soothe/src/soothe/core/runner/_runner_agentic.py`

---

### Phase 5: Testing & Verification (multi-thread scenarios)

**Tasks**:
1. Write unit tests for state manager methods (multi-thread logic)
2. Write unit tests for thread switching policy evaluation
3. Write integration tests for same-thread goal continuation
4. Write integration tests for thread switching (message history threshold trigger)
5. Write integration tests for auto /recall on thread switch
6. Write integration tests for cross-thread /recall command
7. Test thread health metrics collection
8. Run `./scripts/verify_finally.sh` (all tests pass)
9. Manual testing: Multi-thread workflow (goal 1 on thread A → thread switch → goal 2 on thread B)

**Files**:
- `packages/soothe/tests/cognition/agent_loop/test_state_manager.py`
- `packages/soothe/tests/cognition/agent_loop/test_thread_switch_policy.py` (new)
- `packages/soothe/tests/cognition/agent_loop/test_agent_loop_multithread.py` (new)
- `packages/soothe/tests/daemon/test_recall_handler.py`

---

## Verification

**Success Criteria**:
- ✅ Loop indexed by loop_id (independent of thread_id)
- ✅ Loop tracks multiple threads (thread_ids list)
- ✅ Thread switching works automatically (policy triggers evaluated)
- ✅ Auto /recall on thread switch transfers essential knowledge
- ✅ Same-thread goal continuation works (previous final_report injected)
- ✅ `/recall` searches across loops (indexed by loop_id) and returns relevant results
- ✅ Working memory cleared per-goal (even across thread switches)
- ✅ Loop checkpoint persists across multiple goals and multiple threads
- ✅ Thread health metrics collected and updated
- ✅ Extensible policy allows adding/removing triggers
- ✅ All unit tests pass (multi-thread logic)
- ✅ `./scripts/verify_finally.sh` passes (900+ tests)

**Multi-Thread Workflow Example**:
- Loop L1 starts on thread A
- Goal 0 on thread A: "analyze project" → Complete → message_history_tokens = 80K
- Goal 1 on thread A: "count readme files" → Complete → message_history_tokens = 105K (threshold=100K)
- Goal 2 start → Thread switch triggered → Create thread B → Auto /recall goal_0, goal_1 → Inject top-10 results
- Goal 2 on thread B: "translate previous report" → Receives thread A knowledge → Complete
- Loop checkpoint: thread_ids=["A", "B"], current_thread_id="B", goal_history=[goal_0, goal_1, goal_2], total_thread_switches=1

---

## Related Documents

- **RFC-203**: Layer 2 Unified State Model and Independent Checkpoint
- **RFC-200**: Agentic Goal Execution Loop
- **RFC-203**: Loop Working Memory
- **RFC-002**: MemoryProtocol (Cross-thread long-term memory)
- **RFC-103**: VectorStoreProtocol

---

## Open Questions

1. **Loop ID generation**: UUID or user-specified name? (recommendation: UUID for uniqueness, user name optional alias)
2. **Thread switch timing**: Switch before goal start or mid-execution? (recommendation: before goal start for clean transition)
3. **Auto /recall query**: Use current goal text or generic query? (recommendation: current goal text for relevance)
4. **Thread switch logging**: Log trigger reason to checkpoint or separate log? (recommendation: checkpoint for audit trail)
5. **Checkpoint file size optimization**: Compress old goal_history entries? (recommendation: defer, monitor growth across threads)
6. **Thread archiving**: Archive old threads in thread_ids list or keep active? (recommendation: keep full history for audit)
7. **Policy configuration**: Global policy or per-loop policy? (recommendation: global policy with loop override option)
8. **Custom trigger safety**: How to safely evaluate custom trigger expressions? (recommendation: predefined operators, no arbitrary code execution)

---

## Changelog

**2026-04-16 (created)**:
- Initial design for AgentLoop thread-scoped infinite lifecycle
- Goal-scoped execution records within thread-scoped loop
- Same-thread goal continuation via previous final_report injection
- Cross-thread /recall command (searches checkpoints + memory)
- Working memory cleared per-goal
- No backward compatibility with v1.0

**2026-04-16 (expanded)**:
- Extended design for multi-thread spanning (loop independent of thread)
- Added ThreadHealthMetrics model (monitor thread health)
- Added ThreadSwitchPolicy model (extensible switching triggers)
- Added automatic thread switching (policy-based triggers)
- Added auto /recall on thread switch (knowledge transfer)
- Added thread_ids list (track all threads loop has operated on)
- Added goal_id independent of thread_id (goal IDs: {loop_id}_goal_{seq})
- Added custom trigger extensibility (policy-specific triggers)
- Loop indexed by loop_id (checkpoint path: SOOTHE_HOME/runs/{loop_id}/)
- Full thread history preserved (audit trail)
# AgentLoop Checkpoint Tree Architecture

> Design draft for branch-based checkpoint synchronization and smart retry with learning.
>
> **RFC Number**: RFC-611
> **Status**: Draft
> **Created**: 2026-04-22
> **Dependencies**: RFC-608 (Multi-Thread Lifecycle), IG-238 (Checkpoint Unified Integration)
> **Author**: Claude Sonnet 4.6

---

## Abstract

This RFC defines AgentLoop checkpoint tree architecture that synchronizes AgentLoop checkpoints with CoreAgent checkpoints through **branch-based checkpoint trees**. The design enables smart retry with learning: failed execution branches are preserved, analyzed for failure patterns, and learning insights are injected into retry attempts. Checkpoint anchors provide synchronization points between AgentLoop iterations and CoreAgent checkpoint history, enabling precise rewinding without garbage checkpoints.

---

## Motivation

### Current Problem

**IG-238** introduced `CoreAgentCheckpointRef` metadata linkage, but left a critical synchronization gap:

```
AgentLoop checkpoint at iteration 2 boundary
  ↓
CoreAgent executes: reason → tool → subagent (multiple checkpoints)
  ↓
FAILURE (iteration 3)
  ↓
Want to recover: Rewind to AgentLoop checkpoint (iteration 2)
  ↓
Problem: Which CoreAgent checkpoint_id to restore?
  - checkpoint_id_latest? Contains failed iteration 3 garbage
  - checkpoint_id_boundary? Correct state, but how do we know this ID?
```

**Root cause**: AgentLoop checkpoint lacks precise checkpoint anchor to CoreAgent checkpoint at iteration boundaries. Failed iteration creates garbage checkpoints in CoreAgent history, making rewinding ambiguous.

### Proposed Solution

**Branch-based checkpoint trees**:
- AgentLoop checkpoint references a **tree structure** (main_line + failed_branches)
- **Iteration checkpoint anchors**: Precise CoreAgent checkpoint_id captured at each iteration boundary
- **Failed branches**: Preserve execution path (checkpoint_ids from root → failure) for learning analysis
- **Smart retry**: Rewind to root checkpoint, inject learning insights, retry with adjustments
- **Checkpoint pruning**: Failed branches can be pruned after successful retry (optional cleanup)

---

## Architecture

### Core Concept: Checkpoint Tree Structure

```
Checkpoint Tree = {
  main_line_checkpoints: {
    iteration → checkpoint_id (successful execution)
  },
  failed_branches: {
    branch_id → {
      root_checkpoint_id,  // Where branch started (rewind target)
      failure_checkpoint_id,  // Where failure occurred
      execution_path: [checkpoint_ids],  // Full path from root → failure
      failure_insights,  // LLM analysis of failure
      avoid_patterns,  // Patterns to avoid in retry
      suggested_adjustments,  // Retry suggestions
    }
  }
}
```

**Key principle**: Main line = successful execution history. Failed branches = learning history (preserved for smart retry).

---

### Checkpoint Anchor Mechanism

**Iteration checkpoint anchors** captured at each iteration boundary:

```python
class CheckpointAnchor(BaseModel):
    """Synchronization point between AgentLoop iteration and CoreAgent checkpoint."""
    
    iteration: int
    thread_id: str  # Which thread this checkpoint belongs to
    checkpoint_id: str  # CoreAgent checkpoint_id at this boundary
    checkpoint_ns: str  # CoreAgent checkpoint namespace
    anchor_type: Literal["iteration_start", "iteration_end", "failure_point"]
    timestamp: datetime
    
    # Execution summary (for learning analysis)
    iteration_status: Literal["success", "failure", "partial"] | None
    next_action_summary: str | None
    tools_executed: list[str] = []
    reasoning_decision: str | None
```

**Capture triggers**:
- **Iteration start**: Capture anchor before Plan phase starts
- **Iteration end**: Capture anchor after Execute phase completes successfully
- **Failure point**: Capture anchor when failure detected (creates failed branch)

---

### Failed Branch Model

```python
class FailedBranchRecord(BaseModel):
    """Record of failed execution branch for learning."""
    
    branch_id: str  # UUID
    loop_id: str
    iteration: int  # Iteration where failure occurred
    thread_id: str  # Thread where failure occurred
    
    # Checkpoint references
    root_checkpoint_id: str  # Where branch started (parent iteration's checkpoint)
    failure_checkpoint_id: str  # Checkpoint where failure detected
    execution_path: list[str]  # All checkpoint_ids from root → failure
    
    # Failure context
    failure_reason: str  # High-level failure reason
    failure_insights: dict[str, Any]  # Structured analysis
    avoid_patterns: list[str]  # Patterns to avoid in retry
    suggested_adjustments: list[str]  # Retry suggestions
    
    # Metadata
    created_at: datetime
    analyzed_at: datetime | None  # When failure was analyzed
    pruned_at: datetime | None  # When branch was pruned (optional cleanup)
```

**Learning insights** (pre-computed for fast retry):
```json
{
  "root_cause": "Subagent timeout after 30s",
  "context": "Large file analysis exceeded timeout threshold",
  "patterns": [
    "Sequential file reads in single iteration",
    "Claude subagent used for files > 500KB without streaming"
  ],
  "suggestions": [
    "Use streaming mode for large file analysis",
    "Split file into chunks, analyze in parallel",
    "Increase subagent timeout to 60s for file analysis"
  ]
}
```

---

### Checkpoint Tree Reference Schema

```python
class CoreAgentCheckpointTreeRef(BaseModel):
    """Reference to CoreAgent checkpoint tree structure."""
    
    main_line_checkpoints: dict[int, str] = Field(default_factory=dict)
    """Mapping: iteration → checkpoint_id on main successful execution line."""
    
    failed_branches: dict[str, FailedBranchRecord] = Field(default_factory=dict)
    """Mapping: branch_id → failed branch execution record."""
    
    current_head_checkpoint_id: str | None = None
    """Latest checkpoint_id on current branch (main_line or retry branch)."""
```

**AgentLoopCheckpoint v3.1 schema** (extends IG-238 v3.0):
```python
class AgentLoopCheckpoint(BaseModel):
    """Complete AgentLoop state with checkpoint tree reference (v3.1)."""
    
    # Identity (RFC-608)
    loop_id: str  # UUID
    thread_ids: list[str] = Field(default_factory=list)
    current_thread_id: str
    
    # NEW: Checkpoint tree reference (v3.1)
    checkpoint_tree_ref: CoreAgentCheckpointTreeRef = Field(default_factory=CoreAgentCheckpointTreeRef)
    """Reference to CoreAgent checkpoint tree with branch management."""
    
    # CoreAgent checkpoint references (v3.0 from IG-238)
    coreagent_checkpoint_refs: dict[str, CoreAgentCheckpointRef] = Field(default_factory=dict)
    """Mapping: thread_id → CoreAgent checkpoint metadata (IG-238 linkage)."""
    
    # Status (RFC-608)
    status: Literal["running", "ready_for_next_goal", "finalized", "cancelled"]
    
    # Goal execution history (RFC-608)
    goal_history: list[GoalExecutionRecord] = Field(default_factory=list)
    current_goal_index: int = -1
    
    # Working memory (RFC-608)
    working_memory_state: WorkingMemoryState = Field(default_factory=WorkingMemoryState)
    
    # Thread health (RFC-608)
    thread_health_metrics: ThreadHealthMetrics
    
    # RFC-609: Goal context injection
    thread_switch_pending: bool = False
    
    # Loop metrics
    total_goals_completed: int = 0
    total_thread_switches: int = 0
    total_duration_ms: int = 0
    total_tokens_used: int = 0
    
    # Timestamps
    created_at: datetime
    updated_at: datetime
    
    schema_version: str = "3.1"  # v3.1 adds checkpoint tree reference
```

---

## Workflow

### Iteration Boundary Workflow

**Step 1: Iteration start anchor**:
```python
async def start_iteration(iteration: int, thread_id: str):
    """Capture iteration start anchor before Plan phase."""
    
    # Get current CoreAgent checkpoint
    checkpointer = get_langgraph_checkpointer(thread_id)
    config = {"configurable": {"thread_id": thread_id}}
    checkpoint_tuple = await checkpointer.aget_tuple(config)
    
    # Create anchor
    anchor = CheckpointAnchor(
        iteration=iteration,
        thread_id=thread_id,
        checkpoint_id=checkpoint_tuple.config["configurable"]["checkpoint_id"],
        checkpoint_ns=checkpoint_tuple.config["configurable"].get("checkpoint_ns", ""),
        anchor_type="iteration_start",
        timestamp=datetime.now(UTC),
    )
    
    # Save anchor
    await persistence_manager.save_checkpoint_anchor(
        loop_id=self.loop_id,
        iteration=iteration,
        thread_id=thread_id,
        checkpoint_id=anchor.checkpoint_id,
        anchor_type="iteration_start",
    )
    
    # Update main_line_checkpoints
    self.checkpoint.checkpoint_tree_ref.main_line_checkpoints[iteration] = anchor.checkpoint_id
    await self.save_checkpoint()
```

**Step 2: Iteration execution**:
- CoreAgent executes Plan → Execute (automatic per-node checkpointing)
- AgentLoop tracks execution progress (reason steps, act waves)
- CoreAgent checkpoint history grows: checkpoint_start → checkpoint_node_1 → checkpoint_node_2 → ...

**Step 3: Iteration end anchor (success)**:
```python
async def complete_iteration(iteration: int, thread_id: str, execution_summary: dict):
    """Capture iteration end anchor after successful Execute phase."""
    
    # Get latest CoreAgent checkpoint
    checkpointer = get_langgraph_checkpointer(thread_id)
    checkpoint_tuple = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
    
    # Create anchor with execution summary
    anchor = CheckpointAnchor(
        iteration=iteration,
        thread_id=thread_id,
        checkpoint_id=checkpoint_tuple.config["configurable"]["checkpoint_id"],
        anchor_type="iteration_end",
        timestamp=datetime.now(UTC),
        iteration_status="success",
        next_action_summary=execution_summary.get("next_action"),
        tools_executed=execution_summary.get("tools_executed", []),
        reasoning_decision=execution_summary.get("reasoning_decision"),
    )
    
    # Save anchor
    await persistence_manager.save_checkpoint_anchor(
        loop_id=self.loop_id,
        iteration=iteration,
        thread_id=thread_id,
        checkpoint_id=anchor.checkpoint_id,
        anchor_type="iteration_end",
        execution_summary=execution_summary,
    )
    
    # Update main_line_checkpoints (replace start with end)
    self.checkpoint.checkpoint_tree_ref.main_line_checkpoints[iteration] = anchor.checkpoint_id
    await self.save_checkpoint()
```

---

### Failure Detection & Branch Creation Workflow

**Step 1: Detect iteration failure**:
```python
async def detect_iteration_failure(iteration: int, failure_reason: str):
    """Detect iteration failure and create failed branch."""
    
    # Get current thread and checkpoint
    thread_id = self.checkpoint.current_thread_id
    checkpointer = get_langgraph_checkpointer(thread_id)
    checkpoint_tuple = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
    failure_checkpoint_id = checkpoint_tuple.config["configurable"]["checkpoint_id"]
    
    # Get root checkpoint (previous iteration's end anchor)
    prev_iteration = iteration - 1
    root_checkpoint_id = self.checkpoint.checkpoint_tree_ref.main_line_checkpoints.get(prev_iteration)
    
    if not root_checkpoint_id:
        # No previous anchor (first iteration failure)
        root_checkpoint_id = self.checkpoint.checkpoint_tree_ref.main_line_checkpoints.get(0, "initial")
    
    # Extract execution path (checkpoints from root → failure)
    execution_path = await get_checkpoints_between(
        thread_id=thread_id,
        start_checkpoint_id=root_checkpoint_id,
        end_checkpoint_id=failure_checkpoint_id,
    )
    
    # Create failed branch
    branch_id = f"branch_{uuid.uuid4().hex[:8]}"
    failed_branch = FailedBranchRecord(
        branch_id=branch_id,
        loop_id=self.loop_id,
        iteration=iteration,
        thread_id=thread_id,
        root_checkpoint_id=root_checkpoint_id,
        failure_checkpoint_id=failure_checkpoint_id,
        execution_path=execution_path,
        failure_reason=failure_reason,
        created_at=datetime.now(UTC),
    )
    
    # Save failed branch
    await persistence_manager.save_failed_branch(
        branch_id=branch_id,
        loop_id=self.loop_id,
        iteration=iteration,
        root_checkpoint_id=root_checkpoint_id,
        failure_checkpoint_id=failure_checkpoint_id,
        failure_reason=failure_reason,
        execution_path=execution_path,
    )
    
    # Update checkpoint tree
    self.checkpoint.checkpoint_tree_ref.failed_branches[branch_id] = failed_branch
    await self.save_checkpoint()
    
    return failed_branch
```

---

### Failure Analysis Workflow

**Step 2: Analyze failure (LLM call)**:
```python
async def analyze_failure(branch: FailedBranchRecord) -> FailedBranchRecord:
    """Analyze failure context and compute learning insights."""
    
    # Extract failure context from CoreAgent checkpoints
    failure_context = await extract_failure_context_from_checkpoints(
        thread_id=branch.thread_id,
        execution_path=branch.execution_path,
    )
    
    # LLM analysis prompt
    analysis_prompt = f"""
Analyze this execution failure and provide structured insights:

Failure Reason: {branch.failure_reason}

Execution Context:
{failure_context}

Provide:
1. Root cause analysis
2. Patterns that led to failure (avoid_patterns)
3. Suggested adjustments for retry (suggested_adjustments)

Format as JSON.
"""
    
    # Call LLM for analysis
    model = self.config.create_chat_model("default")
    response = await model.ainvoke(analysis_prompt)
    
    # Parse LLM response
    insights = parse_llm_analysis_response(response.content)
    
    # Update branch with learning
    branch.failure_insights = insights
    branch.avoid_patterns = insights.get("avoid_patterns", [])
    branch.suggested_adjustments = insights.get("suggested_adjustments", [])
    branch.analyzed_at = datetime.now(UTC)
    
    # Save updated branch
    await persistence_manager.update_branch_analysis(
        branch_id=branch.branch_id,
        loop_id=self.loop_id,
        failure_insights=branch.failure_insights,
        avoid_patterns=branch.avoid_patterns,
        suggested_adjustments=branch.suggested_adjustments,
    )
    
    # Update checkpoint tree
    self.checkpoint.checkpoint_tree_ref.failed_branches[branch.branch_id] = branch
    await self.save_checkpoint()
    
    return branch
```

---

### Smart Retry Workflow

**Step 3: Rewind and retry with learning**:
```python
async def smart_retry_with_learning(branch: FailedBranchRecord):
    """Rewind to root checkpoint and retry with learning insights."""
    
    # Rewind CoreAgent to root checkpoint
    await restore_coreagent_checkpoint(
        thread_id=branch.thread_id,
        checkpoint_id=branch.root_checkpoint_id,
    )
    
    # Inject learning into Plan phase
    retry_context = {
        "previous_failure": {
            "reason": branch.failure_reason,
            "avoid_patterns": branch.avoid_patterns,
            "suggested_adjustments": branch.suggested_adjustments,
        },
        "retry_mode": True,
        "learning_applied": branch.suggested_adjustments,
    }
    
    # Emit branch retry event
    await emit_event({
        "type": BRANCH_RETRY_STARTED,
        "branch_id": branch.branch_id,
        "retry_iteration": self.checkpoint.current_goal_index + 1,
        "learning_applied": branch.suggested_adjustments,
    })
    
    # Execute retry with learning context injected
    await self.execute_plan_phase_with_context(retry_context)
```

---

## Checkpoint Pruning Strategy

### Pruning Policy

**Optional cleanup** of old failed branches:

```python
class BranchPruningPolicy(BaseModel):
    """Policy for pruning old failed branches."""
    
    retention_days: int = 30  # Keep branches created within this period
    keep_successful_retry_branches: bool = True  # Keep branches that led to successful retry
    keep_unanalyzed_branches: bool = False  # Prune unanalyzed branches immediately
    max_branches_per_loop: int | None = 100  # Limit total branches (optional)
```

**Pruning workflow**:
```python
async def prune_old_branches(loop_id: str, policy: BranchPruningPolicy):
    """Prune old failed branches based on policy."""
    
    threshold = datetime.now(UTC) - timedelta(days=policy.retention_days)
    
    branches = await persistence_manager.get_failed_branches_for_loop(loop_id)
    
    for branch in branches:
        # Check pruning criteria
        should_prune = (
            branch.created_at < threshold  # Old branch
            and (not policy.keep_successful_retry_branches or not has_successful_retry(branch))  # Not valuable
            and (policy.keep_unanalyzed_branches or branch.analyzed_at is not None)  # Analyzed
        )
        
        if should_prune:
            # Mark as pruned (soft delete)
            await persistence_manager.mark_branch_pruned(branch.branch_id, loop_id)
```

---

## Implementation Tasks

### Phase 1: Schema Migration
- Add `CheckpointAnchor` model
- Add `FailedBranchRecord` model
- Add `CoreAgentCheckpointTreeRef` model
- Update `AgentLoopCheckpoint` schema to v3.1

### Phase 2: Checkpoint Anchor Management
- Implement `save_checkpoint_anchor()` in persistence manager
- Implement `get_checkpoint_anchors_for_range()` for failure analysis
- Integrate with AgentLoop iteration boundaries

### Phase 3: Failed Branch Management
- Implement `detect_iteration_failure()` and branch creation
- Implement `analyze_failure()` with LLM analysis
- Implement `save_failed_branch()` and `update_branch_analysis()`

### Phase 4: Smart Retry Integration
- Implement `restore_coreagent_checkpoint()` rewinding
- Implement learning injection into Plan phase
- Integrate with AgentLoop retry logic

### Phase 5: Pruning & Cleanup
- Implement branch pruning policy
- Implement `prune_old_branches()` cleanup
- Add CLI command for manual pruning

---

## Success Criteria

1. Iteration checkpoint anchors captured at boundaries ✓
2. Failed branches preserve execution path ✓
3. Failure analysis computes learning insights ✓
4. Smart retry rewinds to correct checkpoint ✓
5. Learning injected into retry execution ✓
6. Branches can be pruned after successful retry ✓
7. No checkpoint synchronization ambiguity ✓
8. History reconstruction includes failed branches ✓

---

## Related Specifications

- RFC-608: AgentLoop Multi-Thread Lifecycle
- RFC-409: AgentLoop Persistence Backend
- RFC-411: Event Stream Replay & History Reconstruction
- IG-238: AgentLoop Checkpoint Unified Integration

---

**End of RFC-611 Draft**
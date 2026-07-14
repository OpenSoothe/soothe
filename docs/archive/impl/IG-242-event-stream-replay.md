# Event Stream Replay Implementation

> Implementation guide for history reconstruction from checkpoint tree (RFC-411).
>
> **RFC**: RFC-411 (Event Stream Replay)
> **Dependencies**: IG-239 (Persistence), IG-240 (Checkpoint Tree), IG-241 (Loop UX)
> **Language**: Python 3.11+

---

## 1. Overview

Implement event stream reconstruction from checkpoint tree for **loop reattachment**. When client reattaches to detached loop, reconstruct complete history (goals + iterations + steps + tools + branches) and replay to TUI/CLI via event stream.

## 2. Event Stream Reconstruction

### 2.1 Reconstruct from Checkpoint Tree

**Location**: `packages/soothe/src/soothe/core/event_replay/reconstructor.py`

```python
async def reconstruct_event_stream(
    checkpoint: AgentLoopCheckpoint,
    persistence_manager: AgentLoopCheckpointPersistenceManager,
) -> list[dict[str, Any]]:
    """Reconstruct event stream from checkpoint tree.
    
    Process:
    1. Load goal_history → emit GOAL_CREATED events
    2. Load checkpoint_anchors → emit ITERATION_STARTED events
    3. Load reason_history/act_history → emit AGENT_LOOP_STEP events
    4. Load failed_branches → emit BRANCH_CREATED/BRANCH_RETRY events
    
    Returns:
        Chronological event stream (sorted by timestamp).
    """
    events = []
    
    # Goal events
    for goal in checkpoint.goal_history:
        events.append({"type": GOAL_CREATED, "goal_id": goal.goal_id, ...})
    
    # Branch events (NEW)
    for branch_id, branch in checkpoint.checkpoint_tree_ref.failed_branches.items():
        events.append({"type": BRANCH_CREATED, "branch_id": branch_id, ...})
        events.append({"type": BRANCH_RETRY_STARTED, "branch_id": branch_id, ...})
    
    events.sort(key=lambda e: e["timestamp"])
    return events
```

---

## 3. CoreAgent Enrichment

### 3.1 Enrich with Message Details

**Location**: `packages/soothe/src/soothe/core/event_replay/enricher.py`

```python
async def enrich_events_with_coreagent_details(
    events: list[dict],
    checkpointer: BaseCheckpointSaver,
) -> list[dict]:
    """Enrich events with CoreAgent checkpoint details.
    
    For each event with checkpoint_id:
    1. Load CoreAgent checkpoint
    2. Extract messages
    3. Add checkpoint_ref metadata
    """
    for event in events:
        if "checkpoint_id" in event:
            checkpoint_tuple = await checkpointer.aget_tuple(...)
            messages = checkpoint_tuple.checkpoint["channel_values"]["messages"]
            event["checkpoint_ref"] = {
                "message_count": len(messages),
                "estimated_tokens": sum(len(m.content) for m in messages) // 4,
            }
    
    return events
```

---

## 4. TUI Card Mapping

### 4.1 Create BranchCard Widget

**Location**: `packages/soothe-cli/src/soothe_cli/tui/widgets/branch_card.py`

```python
class BranchCardMessage(Vertical):
    """Widget displaying failed branch with learning insights.
    
    Shows:
    - Branch ID, Failure reason
    - Avoid patterns, Suggested adjustments
    - Retry outcome
    """
    
    def __init__(self, branch_id: str, failure_reason: str, ...):
        # Build card content
        self.mount(
            Static(f"[bold red]Branch: {branch_id}[/bold red]"),
            Static(f"Failure: {failure_reason}"),
            Static(f"Avoid Patterns: {avoid_patterns}"),
            Static(f"Suggestions: {suggested_adjustments}"),
        )
```

---

## 5. Reattachment Workflow

### 5.1 Handle Loop Reattachment

**Location**: `packages/soothe/src/soothe/daemon/reattachment_handler.py`

```python
async def handle_loop_reattach(loop_id: str, client_session: ClientSession):
    """Handle loop reattachment: reconstruct history and replay.
    
    Process:
    1. Load AgentLoop checkpoint
    2. Reconstruct event stream
    3. Enrich with CoreAgent details
    4. Send history_replay event to client
    5. Send LOOP_REATTACHED event
    """
    
    # Load checkpoint
    checkpoint = await persistence_manager.load_agentloop_checkpoint(loop_id)
    
    # Reconstruct stream
    event_stream = await reconstruct_event_stream(checkpoint, persistence_manager)
    
    # Enrich
    enriched_stream = await enrich_events_with_coreagent_details(event_stream, checkpointer)
    
    # Send to client
    await client_session.send_event({
        "type": "history_replay",
        "loop_id": loop_id,
        "events": enriched_stream,
    })
    
    await client_session.send_event({
        "type": LOOP_REATTACHED,
        "loop_id": loop_id,
    })
```

---

## 6. Event Constants Module

### 6.1 Create Centralized Constants

**Location**: `packages/soothe/src/soothe/core/event_constants.py`

```python
"""Centralized event type string constants."""

# NEW: Branch events
BRANCH_CREATED = "soothe.cognition.branch.created"
BRANCH_ANALYZED = "soothe.cognition.branch.analyzed"
BRANCH_RETRY_STARTED = "soothe.cognition.branch.retry.started"

# NEW: Loop reattachment events
LOOP_REATTACHED = "soothe.lifecycle.loop.reattached"
HISTORY_REPLAY_COMPLETE = "soothe.lifecycle.loop.history.replayed"

# Existing events (reuse)
GOAL_CREATED = "soothe.cognition.goal.created"
GOAL_COMPLETED = "soothe.cognition.goal.completed"
ITERATION_STARTED = "soothe.lifecycle.iteration.started"
AGENT_LOOP_STEP_STARTED = "soothe.cognition.agent_loop.step.started"
```

---

## 7. Testing

```bash
# Unit tests
pytest tests/unit/core/event_replay/test_reconstructor.py

# Integration tests
soothe "query" --loop test_loop
# Detach client
soothe loop detach test_loop
# Reattach and verify history replay
soothe loop subscribe test_loop  # Should receive history_replay event
```

---

## 8. Files to Create/Modify

**Create**:
- `packages/soothe/src/soothe/core/event_replay/__init__.py`
- `packages/soothe/src/soothe/core/event_replay/reconstructor.py`
- `packages/soothe/src/soothe/core/event_replay/enricher.py`
- `packages/soothe/src/soothe/daemon/reattachment_handler.py`
- `packages/soothe-cli/src/soothe_cli/tui/widgets/branch_card.py`
- `packages/soothe/src/soothe/core/event_constants.py`

**Modify**:
- `packages/soothe/src/soothe/core/event_catalog.py` (register new events)

---

**End of Phase 4 Implementation Guide (IG-242)**


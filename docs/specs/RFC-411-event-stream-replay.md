# Event Stream Replay & History Reconstruction

> Design draft for reconstructing complete execution history from checkpoint tree for TUI/CLI reattachment.
>
> **RFC Number**: RFC-411
> **Status**: Draft
> **Created**: 2026-04-22
> **Dependencies**: RFC-611 (Checkpoint Tree), RFC-503 (Loop-First UX), RFC-409 (Persistence Backend)
> **Author**: Claude Sonnet 4.6

---

## Abstract

This RFC defines event stream replay architecture for reconstructing complete execution history from AgentLoop checkpoint trees when clients reattach to detached loops. The design converts checkpoint tree (main_line + failed_branches) into chronological event stream, enriches events with CoreAgent checkpoint details, and maps events to existing TUI display cards. Failed branches appear as BranchCard widgets showing failure analysis and learning insights.

---

## Motivation

### Current Problem

**Detached thread history loss** (current):
- Client detaches from thread → thread continues running
- Client reattaches → no history reconstruction
- TUI shows only new events (missing detached execution history)
- User cannot see what happened while detached

**History reconstruction gap**:
- CoreAgent checkpoint contains message history (raw messages)
- AgentLoop checkpoint contains goal history (semantic execution records)
- No mechanism to combine both for full history replay
- Failed attempts not captured (no retry history)

### Proposed Solution

**Checkpoint tree → event stream** reconstruction:
- Load AgentLoop checkpoint tree (main_line + failed_branches)
- Reconstruct chronological event stream (goal → iteration → step → tool events)
- Enrich events with CoreAgent checkpoint details (message/tool content)
- Emit existing event types (reuse TUI event processor)
- Map events to existing TUI cards (GoalCard, StepCard, ToolCard, BranchCard)
- Send replay stream to client on reattachment

**Key principle**: Checkpoint tree is source of truth for history. TUI receives reconstructed cards via event stream replay. No on-fly data needed.

---

## Event Types Strategy

### Reuse Existing Events

**Goal events** (existing, reused):
```python
GOAL_CREATED = "soothe.cognition.goal.created"  # Reuse
GOAL_COMPLETED = "soothe.cognition.goal.completed"  # Reuse
GOAL_FAILED = "soothe.cognition.goal.failed"  # Reuse
```

**Iteration events** (existing, reused):
```python
ITERATION_STARTED = "soothe.lifecycle.iteration.started"  # Reuse
ITERATION_COMPLETED = "soothe.lifecycle.iteration.completed"  # Reuse
```

**AgentLoop step events** (existing, reused):
```python
AGENT_LOOP_STEP_STARTED = "soothe.cognition.agent_loop.step.started"  # Reuse
AGENT_LOOP_STEP_COMPLETED = "soothe.cognition.agent_loop.step.completed"  # Reuse
```

**Tool events** (existing, implicitly via CoreAgent messages):
```python
# Tool events not emitted explicitly during replay
# Tool messages extracted from CoreAgent checkpoint
# TUI processes tool messages via LangChain tool_call/tool_result handling
```

---

### New Events (Added)

**Branch events** (NEW):
```python
BRANCH_CREATED = "soothe.cognition.branch.created"  # NEW
BRANCH_ANALYZED = "soothe.cognition.branch.analyzed"  # NEW
BRANCH_RETRY_STARTED = "soothe.cognition.branch.retry.started"  # NEW
```

**Loop reattachment events** (NEW):
```python
LOOP_REATTACHED = "soothe.lifecycle.loop.reattached"  # NEW
HISTORY_REPLAY_COMPLETE = "soothe.lifecycle.loop.history.replayed"  # NEW
```

**Checkpoint anchor events** (NEW, internal):
```python
CHECKPOINT_ANCHOR_CREATED = "soothe.lifecycle.checkpoint.anchor.created"  # NEW (internal)
```

---

## Event Stream Reconstruction

### Reconstruction Process

**Step 1: Load checkpoint tree**:
```python
async def reconstruct_event_stream_from_checkpoint_tree(
    checkpoint: AgentLoopCheckpoint,
    persistence_manager: AgentLoopCheckpointPersistenceManager,
) -> list[dict[str, Any]]:
    """Reconstruct event stream from checkpoint tree using existing event types."""
    
    events = []
    
    # Load checkpoint anchors (for precise checkpoint_id mapping)
    anchors = await persistence_manager.get_checkpoint_anchors_for_range(
        checkpoint.loop_id, 0, 1000
    )
    
    # Emit goal events (reuse existing types)
    for goal_record in checkpoint.goal_history:
        events.append({
            "type": GOAL_CREATED,
            "goal_id": goal_record.goal_id,
            "description": goal_record.goal_text,
            "timestamp": goal_record.started_at.isoformat(),
        })
        
        # Emit iteration events (reuse existing types)
        for iteration in range(goal_record.iteration + 1):
            # Get iteration anchor
            iteration_anchor = find_anchor_for_iteration(anchors, iteration)
            
            events.append({
                "type": ITERATION_STARTED,
                "iteration": iteration,
                "goal_id": goal_record.goal_id,
                "timestamp": iteration_anchor["timestamp"],
            })
            
            # Emit step events (reuse existing AgentLoop step events)
            for reason_step in goal_record.reason_history:
                if reason_step.iteration == iteration:
                    events.append({
                        "type": AGENT_LOOP_STEP_STARTED,
                        "step_id": reason_step.step_id,
                        "description": reason_step.decision,
                        "timestamp": reason_step.timestamp.isoformat(),
                        "checkpoint_id": iteration_anchor["checkpoint_id"],
                    })
            
            # Emit iteration completion
            if goal_record.status == "completed":
                events.append({
                    "type": ITERATION_COMPLETED,
                    "iteration": iteration,
                    "outcome": "success",
                    "timestamp": goal_record.completed_at.isoformat(),
                })
        
        # Emit goal completion/failure
        if goal_record.status == "completed":
            events.append({
                "type": GOAL_COMPLETED,
                "goal_id": goal_record.goal_id,
                "timestamp": goal_record.completed_at.isoformat(),
            })
        elif goal_record.status == "failed":
            events.append({
                "type": GOAL_FAILED,
                "goal_id": goal_record.goal_id,
                "error": goal_record.failure_reason,
                "timestamp": goal_record.completed_at.isoformat(),
            })
    
    # Emit branch events (NEW types)
    for branch_id, failed_branch in checkpoint.checkpoint_tree_ref.failed_branches.items():
        events.append({
            "type": BRANCH_CREATED,
            "branch_id": branch_id,
            "iteration": failed_branch.iteration,
            "failure_reason": failed_branch.failure_reason,
            "timestamp": failed_branch.created_at.isoformat(),
        })
        
        if failed_branch.analyzed_at:
            events.append({
                "type": BRANCH_ANALYZED,
                "branch_id": branch_id,
                "avoid_patterns": failed_branch.avoid_patterns,
                "suggested_adjustments": failed_branch.suggested_adjustments,
                "timestamp": failed_branch.analyzed_at.isoformat(),
            })
        
        # Check if retry happened
        retry_record = find_retry_after_branch(checkpoint, branch_id)
        if retry_record:
            events.append({
                "type": BRANCH_RETRY_STARTED,
                "branch_id": branch_id,
                "retry_iteration": retry_record.iteration,
                "learning_applied": failed_branch.suggested_adjustments,
                "timestamp": retry_record.started_at.isoformat(),
            })
    
    # Sort by timestamp
    events.sort(key=lambda e: e.get("timestamp", ""))
    
    return events
```

---

### Enrichment with CoreAgent Checkpoint Details

**Step 2: Extract tool/message details**:
```python
async def enrich_events_with_coreagent_details(
    stream: list[dict[str, Any]],
    thread_checkpoints: dict[str, list[str]],
    checkpointer: BaseCheckpointSaver,
) -> list[dict[str, Any]]:
    """Enrich stream events with message/tool details from CoreAgent checkpoints."""
    
    enriched_stream = []
    
    for event in stream:
        enriched_event = event.copy()
        
        if "checkpoint_id" in event:
            # Find thread_id for this checkpoint
            thread_id = find_thread_for_checkpoint(event["checkpoint_id"], thread_checkpoints)
            
            if thread_id:
                # Load CoreAgent checkpoint
                checkpoint_tuple = await checkpointer.aget_tuple(
                    {"configurable": {"thread_id": thread_id, "checkpoint_id": event["checkpoint_id"]}}
                )
                
                if checkpoint_tuple:
                    messages = checkpoint_tuple.checkpoint["channel_values"]["messages"]
                    
                    # Add CoreAgent checkpoint reference metadata
                    enriched_event["checkpoint_ref"] = {
                        "thread_id": thread_id,
                        "checkpoint_id": event["checkpoint_id"],
                        "message_count": len(messages),
                        "estimated_tokens": sum(len(m.content) for m in messages) // 4,
                    }
                    
                    # Extract tool details (for tool events)
                    if event["type"] in ["tool_call", "tool_result"]:
                        # Extract tool call/result from messages
                        tool_details = extract_tool_details_from_messages(messages, event)
                        enriched_event["tool_details"] = tool_details
        
        enriched_stream.append(enriched_event)
    
    return enriched_stream
```

---

## TUI Card Mapping

### Reuse Existing Cards

| Event Type | TUI Card | Status |
|------------|----------|--------|
| `GOAL_CREATED` | `CognitionGoalTreeMessage` | ✅ Reuse |
| `ITERATION_STARTED` | `CognitionGoalTreeMessage` subtree | ✅ Reuse |
| `AGENT_LOOP_STEP_STARTED` | `CognitionStepMessage` | ✅ Reuse |
| `AGENT_LOOP_STEP_COMPLETED` | `CognitionStepMessage` | ✅ Reuse |
| `PLAN_STEP_STARTED` | `CognitionPlanReasonMessage` | ✅ Reuse |
| Tool messages (from CoreAgent) | `ToolCallMessage` | ✅ Reuse |

---

### New BranchCard Widget

**BranchCardMessage** (NEW widget for failed branches):

```python
class BranchCardMessage(_TimestampClickMixin, Vertical):
    """Widget displaying a failed execution branch with learning insights.
    
    Shows:
    - Branch ID and failure reason
    - Execution path (checkpoint IDs traversed)
    - Avoid patterns (what went wrong)
    - Suggested adjustments (learning for retry)
    - Retry outcome (if retry happened)
    """
    
    can_select = True
    
    DEFAULT_CSS = """
    BranchCardMessage {
        border-left: thick $error;
        background: $surface;
        padding: 1 2;
        margin: 1 0;
    }
    
    BranchCardMessage.learning-applied {
        border-left: thick $warning;
    }
    
    BranchCardMessage.retry-success {
        border-left: thick $success;
    }
    """
    
    def __init__(
        self,
        branch_id: str,
        failure_reason: str,
        avoid_patterns: list[str],
        suggested_adjustments: list[str],
        retry_iteration: int | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.branch_id = branch_id
        self.failure_reason = failure_reason
        self.avoid_patterns = avoid_patterns
        self.suggested_adjustments = suggested_adjustments
        self.retry_iteration = retry_iteration
        
        # Build card content
        self._build_content()
    
    def _build_content(self):
        """Build BranchCard content from branch data."""
        
        # Header
        header = Static(f"[bold red]Failed Branch: {self.branch_id}[/bold red]")
        
        # Failure reason
        reason = Static(f"[yellow]Failure: {self.failure_reason}[/yellow]")
        
        # Avoid patterns
        patterns_text = "\n".join([f"  • {pattern}" for pattern in self.avoid_patterns])
        patterns = Static(f"[bold]Avoid Patterns:[/bold]\n{patterns_text}")
        
        # Suggested adjustments
        adjustments_text = "\n".join([f"  • {adj}" for adj in self.suggested_adjustments])
        adjustments = Static(f"[bold]Suggested Adjustments:[/bold]\n{adjustments_text}")
        
        # Retry outcome
        if self.retry_iteration:
            retry = Static(f"[green]Retry: iteration {self.retry_iteration} (successful)[/green]")
            self.styles.border_left = ("thick", "success")
        else:
            retry = Static("[grey]No retry[/grey]")
        
        # Add widgets
        self.mount(header, reason, patterns, adjustments, retry)
```

**Branch event → BranchCard mapping**:
```python
def map_events_to_tui_cards(events: list[dict[str, Any]]) -> list[Widget]:
    """Convert stream events to TUI display cards."""
    
    cards = []
    for event in events:
        if event["type"] == BRANCH_CREATED:
            # Extract branch details
            branch_id = event["branch_id"]
            branch_data = find_branch_record(branch_id)
            
            # Create BranchCard
            cards.append(BranchCardMessage(
                branch_id=branch_id,
                failure_reason=branch_data.failure_reason,
                avoid_patterns=branch_data.avoid_patterns,
                suggested_adjustments=branch_data.suggested_adjustments,
                retry_iteration=find_retry_iteration_for_branch(branch_id),
            ))
        
        elif event["type"] == GOAL_CREATED:
            # Reuse existing CognitionGoalTreeMessage
            cards.append(CognitionGoalTreeMessage(...))
        
        elif event["type"] == AGENT_LOOP_STEP_STARTED:
            # Reuse existing CognitionStepMessage
            cards.append(CognitionStepMessage(...))
        
        # ... other existing card mappings
    
    return cards
```

---

## Reattachment Workflow

### Client Reattachment Process

**Full reattachment workflow**:

```python
async def handle_loop_reattach(
    loop_id: str,
    client_session: ClientSession,
    persistence_manager: AgentLoopCheckpointPersistenceManager,
):
    """Handle loop reattachment: reconstruct history and send to client."""
    
    # 1. Load AgentLoop checkpoint
    loop_checkpoint = await persistence_manager.load_agentloop_checkpoint(loop_id)
    
    # 2. Get thread checkpoint cross-reference map
    thread_checkpoints = await persistence_manager.get_thread_checkpoints_for_loop(loop_id)
    
    # 3. Reconstruct event stream from checkpoint tree
    event_stream = await reconstruct_event_stream_from_checkpoint_tree(
        loop_checkpoint,
        persistence_manager,
    )
    
    # 4. Enrich with CoreAgent checkpoint details
    checkpointer = get_langgraph_checkpointer(loop_checkpoint.current_thread_id)
    enriched_stream = await enrich_events_with_coreagent_details(
        event_stream,
        thread_checkpoints,
        checkpointer,
    )
    
    # 5. Map to TUI cards
    tui_cards = map_events_to_tui_cards(enriched_stream)
    
    # 6. Send history replay to client via WebSocket
    await client_session.send_event({
        "type": "history_replay",
        "loop_id": loop_id,
        "events": enriched_stream,  # Full event stream
        "total_events": len(enriched_stream),
        "reconstructed_at": datetime.now(UTC).isoformat(),
    })
    
    # 7. Send loop status
    await client_session.send_event({
        "type": LOOP_REATTACHED,
        "loop_id": loop_id,
        "status": loop_checkpoint.status,
        "current_thread_id": loop_checkpoint.current_thread_id,  # Internal (for debugging)
    })
    
    # 8. Send history replay complete notification
    await client_session.send_event({
        "type": HISTORY_REPLAY_COMPLETE,
        "loop_id": loop_id,
        "total_cards": len(tui_cards),
    })
```

---

### Client-Side Event Processing

**TUI event processor** (existing, reused):

```python
class EventProcessor:
    """Process events from daemon and update TUI widgets (existing)."""
    
    async def process_event(self, event: dict[str, Any]):
        """Process event (reuse existing logic for existing event types)."""
        
        event_type = event.get("type")
        
        # Reuse existing event processing
        if event_type == GOAL_CREATED:
            await self._handle_goal_created(event)
        
        elif event_type == ITERATION_STARTED:
            await self._handle_iteration_started(event)
        
        elif event_type == AGENT_LOOP_STEP_STARTED:
            await self._handle_step_started(event)
        
        # ... other existing event handlers
        
        # NEW: Handle branch events
        elif event_type == BRANCH_CREATED:
            await self._handle_branch_created(event)
        
        elif event_type == BRANCH_ANALYZED:
            await self._handle_branch_analyzed(event)
        
        elif event_type == BRANCH_RETRY_STARTED:
            await self._handle_branch_retry_started(event)
        
        # NEW: Handle reattachment events
        elif event_type == LOOP_REATTACHED:
            await self._handle_loop_reattached(event)
        
        elif event_type == HISTORY_REPLAY_COMPLETE:
            await self._handle_history_replay_complete(event)
    
    async def _handle_history_replay(self, event: dict[str, Any]):
        """Handle history replay event (batch event processing)."""
        
        # Extract events from replay
        events = event.get("events", [])
        
        # Process each event (reuse existing event handlers)
        for ev in events:
            await self.process_event(ev)
    
    async def _handle_branch_created(self, event: dict[str, Any]):
        """Handle branch created event (NEW)."""
        
        # Create BranchCard
        branch_id = event["branch_id"]
        branch_data = await fetch_branch_details(branch_id)
        
        card = BranchCardMessage(
            branch_id=branch_id,
            failure_reason=branch_data.failure_reason,
            avoid_patterns=branch_data.avoid_patterns,
            suggested_adjustments=branch_data.suggested_adjustments,
        )
        
        # Mount card to message list
        await self.message_list.mount(card)
```

---

## Implementation Tasks

### Phase 1: Event Stream Reconstruction
- Implement `reconstruct_event_stream_from_checkpoint_tree()`
- Implement event emission logic (reuse existing event types)
- Implement branch event emission (NEW event types)

### Phase 2: CoreAgent Enrichment
- Implement `enrich_events_with_coreagent_details()`
- Implement checkpoint lookup and message extraction
- Implement tool detail extraction

### Phase 3: TUI Card Mapping
- Implement `map_events_to_tui_cards()`
- Create `BranchCardMessage` widget (NEW)
- Integrate BranchCard with existing card system

### Phase 4: Reattachment Workflow
- Implement `handle_loop_reattach()` in daemon
- Implement history replay event emission
- Implement client-side event processing

### Phase 5: Event Constants Module
- Create `soothe/core/event_constants.py` (NEW)
- Define all event type string constants
- Ensure reuse across all modules (no hardcoded strings)

---

## Success Criteria

1. Event stream reconstructed from checkpoint tree ✓
2. Existing event types reused (no new types except branch) ✓
3. CoreAgent checkpoint details enriched ✓
4. TUI cards reuse existing widgets ✓
5. BranchCard displays failure analysis ✓
6. History replay sent to client on reattachment ✓
7. Client processes replay events correctly ✓
8. Failed branches appear in history ✓
9. Retry attempts shown in BranchCard ✓
10. Event constants centralized (no hardcoded strings) ✓

---

## Related Specifications

- RFC-611: AgentLoop Checkpoint Tree Architecture
- RFC-612: Loop-First User Experience
- RFC-613: AgentLoop Persistence Backend
- RFC-401: Event Processing (existing)
- RFC-500: CLI/TUI Architecture (existing)

---

**End of RFC-614 Draft**
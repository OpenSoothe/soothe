# IG-271: Daemon Event Optimization and Logging Strategy

**Status**: Completed
**Created**: 2026-04-27
**Purpose**: Remove verbose unused daemon events while ensuring proper logging

> **IG-317 note:** Assistant answer bodies no longer use the `soothe.output.chitchat.*` / `quiz.*` events listed under “Output Domain” below; those rows reflect **traffic optimization work at the time**, not the current answer wire.

---

## Problem Statement

WebSocket clients receive **71 event types** from daemon, but only **~15 are actively used**. This causes:
- 60-70% unnecessary event traffic for normal queries
- 80-90% overhead in autonomous mode
- 95% idle heartbeat noise
- Poor performance on remote/low-bandwidth connections

**Goal**: Remove unused events while preserving audit trail via compact logging.

---

## Analysis Summary

### Unused Events by Category (37 events removed, 1 kept)

**Category 1: Internal Progress Tracking** (9 events)
- `soothe.lifecycle.iteration.*` (started/completed)
- `soothe.lifecycle.checkpoint.saved`
- `soothe.lifecycle.recovery.resumed`
- `soothe.lifecycle.thread.saved` (redundant with thread.ended)
- `soothe.cognition.plan.created`
- `soothe.cognition.plan.dag_snapshot`
- `soothe.cognition.plan.reflected`
- `soothe.intent.classified`
- `soothe.intent.goal_reused`

**Category 2: Autonomous Mode Infrastructure** (23 events)
- All `soothe.cognition.goal.*` events (7)
- All `soothe.system.autopilot.*` events (12)
- All `soothe.cognition.branch.*` events (4)

**Category 3: Protocol Telemetry** (4 events)
- `soothe.protocol.memory.recalled`
- `soothe.protocol.memory.stored`
- `soothe.protocol.policy.checked`
- `soothe.protocol.policy.denied`

**Category 4: Verbose Lifecycle** (3 events removed, 1 kept)
- `soothe.output.chitchat.started` (superseded by responded) ✅ Removed
- `soothe.output.quiz.started` (superseded by responded) ✅ Removed
- `soothe.system.daemon.heartbeat` (every 5s) ✅ **KEPT** - Required for client health monitoring and timeout detection

### Events to Keep (15 events)

**Lifecycle Domain** (3)
- `soothe.lifecycle.thread.started` ✅
- `soothe.lifecycle.thread.resumed` ✅
- `soothe.lifecycle.thread.ended` ✅

**Cognition - AgentLoop** (5) - **HEAVILY USED**
- `soothe.cognition.agent_loop.started` ✅
- `soothe.cognition.agent_loop.completed` ✅
- `soothe.cognition.agent_loop.step.started` ✅
- `soothe.cognition.agent_loop.step.completed` ✅
- `soothe.cognition.agent_loop.reasoned` ✅

**Cognition - Plan** (2) - Layer 1 only
- `soothe.cognition.plan.step.started` ✅
- `soothe.cognition.plan.step.completed` ✅

**Output domain (ancillary only after IG-317)** — keep only if your deployment still emits these for telemetry; they are **not** required for core-loop assistant answers (those use `messages` + `phase`).
- Optional `soothe.output.*` progress events when explicitly emitted by tools/libraries.

---

## Implementation Plan

### Phase 1: Event Removal with Logging Replacement

#### Step 1.1: Remove Category 1 Events (Internal Progress)

**Files affected**: `_runner_phases.py`, `_runner_autonomous.py`, `_runner_checkpoint.py`, `_runner_steps.py`, `_runner_agentic.py`

**Logging strategy**:
- Iteration events → INFO: "Iteration {n} started/completed"
- Checkpoint events → DEBUG: "Checkpoint saved: {thread_id}"
- Recovery events → INFO: "Recovery resumed from checkpoint"
- Thread saved → DEBUG: "Thread persisted: {thread_id}"
- Plan DAG → DEBUG: "Plan DAG: {step_count} steps"
- Intent classification → INFO: "Intent: {intent_type}"

**Example transformation**:
```python
# BEFORE (verbose event emission)
emit_event(IterationStartedEvent(iteration=5))

# AFTER (compact logging)
logger.info("Iteration %d started", iteration)
```

#### Step 1.2: Remove Category 2 Events (Autonomous Infrastructure)

**Files affected**: `_runner_autonomous.py`, `smart_retry_manager.py`

**Logging strategy**:
- Goal events → INFO: "Goal {goal_id}: created/completed/failed"
- Autopilot events → DEBUG: "Autopilot: {status} | Goal: {goal_id}"
- Branch events → DEBUG: "Branch retry: {branch_id} | Reason: {reason}"

**Example**:
```python
# BEFORE
emit_event(GoalCreatedEvent(goal_id="g1", description="..."))

# AFTER
logger.info("Goal %s created: %s", goal_id, description[:50])
```

#### Step 1.3: Remove Category 3 Events (Protocol Telemetry)

**Files affected**: `memory_backend.py`, `policy_backend.py`

**Logging strategy**:
- Memory events → DEBUG: "Memory: recalled {n} items | stored {key}"
- Policy events → INFO (denied): "Policy denied: {action} | Reason: {reason}"
- Policy events → DEBUG (checked): "Policy checked: {action} → allowed"

**Example**:
```python
# BEFORE
emit_event(PolicyDeniedEvent(action="execute_shell", reason="not whitelisted"))

# AFTER
logger.info("Policy denied: %s | Reason: %s", action, reason)
```

#### Step 1.4: Remove Category 4 Events (Verbose Lifecycle)

**Files affected**: `_runner_phases.py`, `server.py`

**Chitchat/Quiz started** → Remove completely (redundant)

**Daemon heartbeat** → Remove emission, add startup log instead:
```python
# BEFORE (every 5 seconds)
emit_event(DaemonHeartbeatEvent(...))

# AFTER (startup only)
logger.info("Daemon heartbeat started (interval: 5s)")
# Remove periodic emission entirely
```

---

### Phase 2: Conditional Events (Make Opt-In)

#### Step 2.1: Checkpoint Events

**Current**: Always emit `CheckpointSavedEvent`
**Optimized**: Only emit during recovery mode

**Implementation**:
```python
# Add config option
emit_checkpoint_events: bool = False  # Default off

# Conditional emission
if config.emit_checkpoint_events or is_recovery_mode:
    emit_event(CheckpointSavedEvent(...))
else:
    logger.debug("Checkpoint saved: %s", checkpoint_id)
```

#### Step 2.2: Recovery Events

**Current**: Always emit `RecoveryResumedEvent`
**Optimized**: Only emit when recovery actually happens

**Implementation**:
```python
if recovery_mode:
    emit_event(RecoveryResumedEvent(...))
    logger.info("Recovery resumed from checkpoint: %s", checkpoint_id)
else:
    # Normal execution - no event needed
    pass
```

---

### Phase 3: Log Classification (INFO vs DEBUG)

#### INFO Level (User-visible operations)

**Must log at INFO**:
- Thread lifecycle: started/resumed/ended
- Goal lifecycle: created/completed/failed
- Policy denials: action + reason
- Intent classification: type + confidence
- Recovery operations: resumed from checkpoint

**Format**: Brief, actionable, < 80 chars
```
INFO: Thread thr-123 started
INFO: Goal g-456 created: Implement feature X
INFO: Policy denied: execute_shell | Reason: not whitelisted
INFO: Intent: question (confidence: 0.92)
```

#### DEBUG Level (Internal diagnostics)

**Must log at DEBUG**:
- Iteration progress: started/completed
- Checkpoint saved: thread_id + location
- Memory operations: recalled/stored counts
- Policy checks (allowed): action
- Plan DAG: step count + dependencies
- Autopilot state changes
- Branch retry attempts

**Format**: Technical, detailed, can be > 80 chars
```
DEBUG: Iteration 5 started (thread: thr-123)
DEBUG: Checkpoint saved: thr-123 @ /path/to/checkpoint.json
DEBUG: Memory recalled: 3 items | Keywords: ['error', 'fix', 'previous']
DEBUG: Policy checked: execute_python → allowed
DEBUG: Plan DAG: 8 steps | Critical path: step1 → step3 → step7
```

---

### Phase 4: Implementation Files

#### Primary Files (Event Emission Points)

1. **`packages/soothe/src/soothe/core/runner/_runner_phases.py`**
   - Remove: `ThreadSavedEvent`, `ChitchatStartedEvent`, `QuizStartedEvent`
   - Add: INFO logs for thread lifecycle, DEBUG for thread saved

2. **`packages/soothe/src/soothe/core/runner/_runner_autonomous.py`**
   - Remove: All goal events, iteration events
   - Add: INFO logs for goal lifecycle, DEBUG for iterations

3. **`packages/soothe/src/soothe/core/runner/_runner_checkpoint.py`**
   - Remove: `CheckpointSavedEvent`, `RecoveryResumedEvent` (make conditional)
   - Add: DEBUG logs for checkpoint, INFO for recovery

4. **`packages/soothe/src/soothe/core/runner/_runner_steps.py`**
   - Remove: `PlanCreatedEvent`, `PlanDagSnapshotEvent`, `PlanBatchStartedEvent`
   - Add: DEBUG logs for plan DAG, batch progress

5. **`packages/soothe/src/soothe/core/runner/_runner_agentic.py`**
   - Remove: `IntentClassified` custom events
   - Add: INFO logs for intent classification

6. **`packages/soothe/src/soothe/cognition/agent_loop/smart_retry_manager.py`**
   - Remove: All branch events
   - Add: DEBUG logs for branch retry attempts

7. **`packages/soothe/src/soothe/daemon/server.py`**
   - Remove: `DaemonHeartbeatEvent` periodic emission
   - Add: INFO startup log for daemon status

#### Secondary Files (Protocol Backends)

8. **`packages/soothe/src/soothe/backends/memory/*.py`**
   - Remove: `MemoryRecalledEvent`, `MemoryStoredEvent`
   - Add: DEBUG logs for memory operations

9. **`packages/soothe/src/soothe/backends/policy/*.py`**
   - Remove: `PolicyCheckedEvent`, `PolicyDeniedEvent`
   - Add: INFO for denied, DEBUG for checked

---

### Phase 5: Testing & Verification

#### Test 1: WebSocket Client Compatibility

**Objective**: Ensure TUI/CLI still function correctly

**Steps**:
1. Run TUI with verbose logging: `soothe --debug "test query"`
2. Verify goal tree displays correctly (AgentLoop events)
3. Verify step cards show progress (AgentLoop step events)
4. Verify final output appears (Output events)
5. Check for missing event errors in logs

**Success criteria**: No client errors, all UI widgets render correctly

#### Test 2: Performance Measurement

**Objective**: Quantify event reduction

**Steps**:
1. Run benchmark query: `soothe "complex multi-step task"`
2. Count events before optimization: `grep "emit_event" logs/*.log | wc -l`
3. Apply optimization
4. Count events after: same command
5. Measure WebSocket traffic: monitor network payload size

**Success criteria**:
- Event count reduction: 60-70% for normal queries
- Network payload reduction: measurable decrease
- No latency increase

#### Test 3: Log Audit Trail

**Objective**: Verify removed events are logged correctly

**Steps**:
1. Enable DEBUG logs: `SOOTHE_LOG_LEVEL=DEBUG`
2. Run query with removed events (e.g., autonomous goal)
3. Check logs contain INFO/DEBUG replacements
4. Verify log format is compact and readable

**Success criteria**:
- All removed events have log entries
- INFO logs are user-visible, DEBUG logs are technical
- Log messages are < 100 chars on average

#### Test 4: Recovery Mode

**Objective**: Ensure conditional events work

**Steps**:
1. Start query, interrupt mid-execution
2. Resume from checkpoint: `soothe --resume <thread_id>`
3. Verify `RecoveryResumedEvent` emitted (conditional)
4. Check INFO log for recovery message

**Success criteria**: Recovery events emit only when needed

---

## Verification Checklist

Run after implementation:

```bash
# 1. Format check
make format-check

# 2. Linting (zero errors)
make lint

# 3. Unit tests (900+)
make test-unit

# 4. Integration test (daemon + TUI)
soothe --debug "test query"

# 5. Performance benchmark
./scripts/benchmark_events.sh  # (create this script)
```

---

## Expected Outcomes

### Performance Improvement

- **Event traffic**: 60-70% reduction for normal queries
- **WebSocket payload**: 40-50% smaller messages
- **Idle noise**: 95% reduction (heartbeat removed)

### Logging Quality

- **INFO logs**: User-visible operations (thread, goal, policy denials)
- **DEBUG logs**: Internal diagnostics (iterations, checkpoints, memory)
- **Log size**: Compact, < 100 chars per message
- **Audit trail**: Complete coverage of removed events

### Client Compatibility

- **TUI**: All widgets render correctly (no missing events)
- **CLI**: Final output displays correctly
- **No breakage**: Zero client errors

---

## Rollback Plan

If client breakage occurs:

1. **Immediate**: Re-enable specific event via config flag
   ```python
   emit_verbose_events: bool = True  # Emergency rollback
   ```

2. **Selective**: Re-add specific event type if needed
   ```python
   if config.emit_goal_events:
       emit_event(GoalCreatedEvent(...))
   ```

3. **Logging**: Keep audit logs regardless of event emission

---

## Dependencies

- RFC-400 (Event Processing): Event emission framework
- RFC-001 (Core Architecture): Runner modules
- RFC-600 (Plugin System): Event registration

---

## Notes

- **No new events**: Only removing existing unused events
- **Log-first**: Every removed event must have log replacement
- **Compact logs**: Brief messages, avoid verbose details
- **INFO vs DEBUG**: Clear separation based on user visibility
- **Conditional events**: Make opt-in via config flags
- **Heartbeat removal**: Clients handle timeouts independently

---

## References

- Analysis report: Agent exploration results (2026-04-27)
- Event catalog: `packages/soothe/src/soothe/core/event_catalog.py`
- Loop assistant phases (SDK): `packages/soothe-sdk/src/soothe_sdk/ux/loop_stream.py`
- TUI adapter: `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`
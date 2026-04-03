# Autopilot Mode Design

**Status**: Draft
**Created**: 2026-04-03
**Author**: Design session via Platonic Brainstorming
**Related**: RFC-200 (Layer 3), RFC-201 (Layer 2), RFC-202 (DAG Execution)

---

## 1. Overview

Autopilot mode enables Soothe to operate as a long-running autonomous agent capable of managing complex multi-goal workflows, entering a persistent "dreaming" state when idle, and continuously improving through memory consolidation. This design covers execution flow, goal management, user experience, and system integration.

---

## 2. Execution Flow

### 2.1 Layer Delegation Model

Layer 3 (Autopilot) treats Layer 2 (Agentic Execution) as a black-box ReAct engine:

- **Input**: Rich context envelope sent to Layer 2
- **Output**: JudgeResult with status, evidence, confidence
- **Visibility**: No intermediate step visibility during execution

**Context Envelope Contents**:

| Category | Delivery | Examples |
|----------|----------|----------|
| Core context | System prompt | Goal description, constraints, priority instructions |
| World info | System prompt | Current state, relevant environment data |
| Related goals | Query tool | `get_related_goals()`, `get_goal_progress()` |
| Memory | Query tool | `search_memory(query)` |
| Instructions | System prompt | High-level guidance, success criteria |

### 2.2 Bidirectional Layer 2 ↔ Layer 3 Communication

Layer 2 can query Layer 3 state and propose updates during execution:

**Query Operations** (read-only):
- `get_related_goals()` - Other goals that might inform current work
- `get_goal_progress(goal_id)` - Status/checkpoint of another goal
- `get_world_info()` - Current world state snapshot
- `search_memory(query)` - Cross-thread memory lookup

**Proposal Operations** (queued, applied after iteration):
- `report_progress(status, findings)` - Update current goal progress
- `add_finding(content, tags)` - Contribute to context ledger
- `suggest_goal(description, priority)` - Propose new goal
- `flag_blocker(reason, dependencies)` - Signal goal is blocked

**Queuing Behavior**: Proposals are collected during Layer 2 execution and applied by Layer 3 after the iteration completes. This preserves the black-box abstraction while enabling dynamic adaptation.

### 2.3 Consensus Loop

Layer 3 validates Layer 2's completion judgment rather than automatically accepting it:

**Process**:
1. Layer 2 returns JudgeResult with `status: "done"` and confidence
2. Layer 3's reflection LLM holistically evaluates:
   - Evidence quality and completeness
   - Success criteria satisfaction
   - Finding coherence
3. Layer 3 decides: accept, send back, or suspend

**Send-Back Mechanics**:
- Layer 3 can reject "done" and send Layer 2 back for more work
- Refined instructions accompany send-back (specific gaps to address)
- Separate send-back budget per goal (default: 3 rounds)
- Independent from Layer 2's internal ReAct iteration budget

**Budget Exhaustion**:
- When send-back budget exhausted but goal incomplete → suspend goal
- Suspended goals preserved with current state
- Continue with other ready goals

**Suspended Goal Revival**:
- Dependency-driven reactivation
- When a goal's blockers (dependencies) complete, it automatically reactivates
- Receives fresh send-back budget

### 2.4 Termination → Dreaming Transition

Autopilot does not terminate—it transitions to a persistent dreaming state:

**Trigger**: All goals resolved (completed or failed, none pending/active/suspended)

**Pre-Dreaming Signal**:
- Send `dreaming_entered` message via channel protocol
- User can acknowledge or submit new tasks before dreaming begins

**Dreaming Mode Activities**:

| Activity | Description | Frequency |
|----------|-------------|-----------|
| Memory consolidation | Extract patterns, merge duplicates, prune outdated, summarize verbose | Continuous |
| Background indexing | Re-index vectors, optimize search, warm caches | Periodic |
| Goal anticipation | Analyze patterns, pre-compute likely next steps, draft plans | Periodic |
| Health monitoring | Self-checks, daemon health, resource usage, anomaly alerts | Periodic |

**Dreaming Exit Triggers**:
- New task submitted via inbox
- User sends `wake` signal via channel
- Scheduled task becomes due

---

## 3. Goal Management

### 3.1 Goal Creation Sources

**File-Discovered Goals**:
- `SOOTHE_HOME/autopilot/GOAL.md` - Single goal
- `SOOTHE_HOME/autopilot/GOALS.md` - Multiple goals
- `SOOTHE_HOME/autopilot/goals/*/GOAL.md` - Per-goal subdirectories

**Autopilot-Created Goals**:
- Layer 2 proposals via `suggest_goal()`
- Layer 3 reflection findings that spawn new goals
- Scheduled tasks from SchedulerService

**MUST Goal Confirmation**:
- CriticalityEvaluator determines if goal requires user approval
- Evaluation module in GoalEngine
- Rules + LLM judgment for criticality assessment

**Criticality Signals** (rule-based):
- Affects external systems
- Security implications
- High resource cost
- Modifies user data
- Irreversible operations

**Criticality Signals** (LLM-judged):
- Context impact
- Risk assessment
- Reversibility
- Dependency breadth

### 3.2 Goal Lifecycle

**States** (7 total):

```
pending     → Goal created, waiting for dependencies
active      → Goal being executed by Layer 2
validated   → Layer 3 accepted completion, pending final report
completed   → Goal finished successfully
failed      → Goal failed unrecoverably
suspended   → Budget exhausted, waiting for fresh context
blocked     → External input needed
```

**State Transitions**:

```
pending → active           (ready_goals() activates)
active → validated         (Layer 3 accepts completion)
active → suspended         (send-back budget exhausted)
active → blocked           (external input needed)
active → failed            (unrecoverable error)
suspended → pending        (dependencies resolved)
blocked → pending          (external input received)
validated → completed      (reporting done)
```

### 3.3 Goal Relationships

**Relationship Types**:

| Type | Semantics | Scheduler Behavior |
|------|-----------|-------------------|
| `depends_on` | Hard dependency | Wait for completion |
| `informs` | Soft dependency | Enrich if available, don't block |
| `conflicts_with` | Mutual exclusion | Serialize execution |

**Relationship Discovery**:

- **Explicit declaration**: Author specifies in `GOAL.md` frontmatter
- **Auto-detection**: Layer 3 infers during execution

**Auto-Detection Signals**:

| Signal | Relationship | Confidence |
|--------|--------------|------------|
| Resource read overlap | `informs` | Medium |
| Resource write overlap | `conflicts_with` | High |
| Findings semantic correlation | `informs` | Variable (LLM) |
| Execution interference observed | `conflicts_with` | High |

**Confidence Weighting**:
- Multiple signals synthesize into confidence score
- Low-confidence relationships flagged for user review
- High-confidence relationships auto-applied

### 3.4 Progress Tracking

**Dual Storage**:

| Storage | Purpose | Content |
|---------|---------|---------|
| Goal files | Quick status check | Frontmatter status, Progress section |
| Run artifacts | Detailed audit trail | Step-by-step logs in `runs/{thread_id}/goals/{goal_id}/` |

**Update Behavior**:
- Status changes written to `GOAL.md` frontmatter
- Progress section updated as sub-goals complete
- Detailed step logs written to run artifacts
- Original file structure and comments preserved

---

## 4. User Experience

### 4.1 CLI Interface

CLI serves as a control surface, not a monitoring interface:

**Commands**:

```
soothe autopilot submit "task"      # Submit new task
soothe autopilot status             # Overall autopilot state
soothe autopilot list               # List all goals
soothe autopilot goal <id>          # Goal details
soothe autopilot cancel <id>        # Cancel goal
soothe autopilot approve <id>       # Approve MUST goal
soothe autopilot reject <id>        # Reject proposed goal
soothe autopilot wake               # Exit dreaming mode
soothe autopilot dream              # Force enter dreaming
soothe autopilot inbox              # View pending inbox tasks
```

**Output Behavior**:
- No streaming output to CLI
- Commands return immediately with confirmation
- Use `status` or `goal` commands to check progress

### 4.2 TUI Dashboard

Autopilot TUI is a read-only dashboard, distinct from chat mode:

**Panels** (4 total):

| Panel | Content |
|-------|---------|
| Goal DAG | Visual graph of goals, dependencies, status |
| Status Summary | Overall state, iteration count, active goals |
| Findings | Key discoveries from completed goals |
| Controls | Display of available CLI commands (not interactive) |

**Layout**:
- **Wide terminal**: Horizontal split - Goal DAG (left), other panels stacked (right)
- **Narrow terminal**: Vertical stack - Goal DAG (top), panels below

**No Interactive Controls**:
- TUI displays state only
- All control actions via CLI commands

### 4.3 Daemon Interface

Daemon mirrors CLI capabilities via HTTP and WebSocket:

**HTTP Endpoints**:

```
POST /autopilot/submit
GET  /autopilot/status
GET  /autopilot/goals
GET  /autopilot/goals/{id}
DELETE /autopilot/goals/{id}
POST /autopilot/goals/{id}/approve
POST /autopilot/goals/{id}/reject
POST /autopilot/wake
POST /autopilot/dream
GET  /autopilot/inbox
```

**WebSocket Events** (subscribe to receive):
- `autopilot.status_changed` - State transitions
- `autopilot.goal_created` - New goal added
- `autopilot.goal_progress` - Progress update
- `autopilot.goal_completed` - Goal finished
- `autopilot.dreaming_entered` - Entering dreaming
- `autopilot.dreaming_exited` - Exiting dreaming

### 4.4 Channel Protocol

Message-centric protocol for user ↔ Soothe communication:

**Message Structure**:

```python
@dataclass
class ChannelMessage:
    type: str           # e.g., "task_submit", "status_update"
    payload: dict       # Type-specific content
    timestamp: datetime
    sender: str         # "user", "soothe", "system"
```

**User → Soothe Types**:

| Type | Payload | Description |
|------|---------|-------------|
| `task_submit` | `{description, priority?, context?}` | New task request |
| `task_cancel` | `{goal_id}` | Cancel specific goal |
| `signal_interrupt` | `{}` | Pause execution |
| `signal_resume` | `{}` | Resume paused execution |
| `query_status` | `{}` | Request current state |
| `feedback` | `{goal_id, content}` | User guidance |

**Soothe → User Types**:

| Type | Payload | Description |
|------|---------|-------------|
| `status_update` | `{state, active_goals}` | State transition |
| `goal_progress` | `{goal_id, status, progress}` | Goal update |
| `finding_report` | `{goal_id, content}` | Significant finding |
| `blocker_alert` | `{goal_id, reason}` | Blocked needs input |
| `dreaming_entered` | `{}` | Entering dreaming mode |
| `session_summary` | `{goals_completed, findings}` | Periodic digest |

**Transport** (initial):
- File-based: `autopilot/inbox/` for incoming, `autopilot/outbox/` for outgoing
- Extensible for future IM/email adapters

---

## 5. Integration

### 5.1 Daemon Hosting

Autopilot runs within the daemon process:

- **Same process, shared state**
- Activates on explicit request only
- No separate process management

**Activation Triggers**:
- `soothe autopilot run "task"`
- `soothe autopilot submit "task"` (if daemon running)
- Inbox file submission while daemon active

### 5.2 Thread Model

**Thread per Goal** for parallel execution:

- Main session: `{session_id}`
- Parallel goals: `{session_id}__goal_{goal_id}`
- Isolated LangGraph state per goal thread
- Layer 3 aggregates results from parallel threads

### 5.3 Persistence

**Checkpoint Cadence**:

| Trigger | Behavior |
|---------|----------|
| Goal completed/failed | Full checkpoint |
| Goal suspended/blocked | Full checkpoint |
| Before dreaming | Full checkpoint |
| User interrupt | Full checkpoint |
| Every N iterations | Periodic snapshot (configurable) |

**Checkpoint Contents**:
- GoalEngine state (all goals, relationships)
- Accumulated findings
- Layer 3 working memory
- Scheduler pending tasks

### 5.4 Scheduler Service

**Location**: `soothe/cognition/scheduler/`

**Capabilities**:

| Feature | CLI Flag | Example |
|---------|----------|---------|
| Delayed execution | `--delay` | `--delay "2h"` |
| Specific time | `--at` | `--at "2026-04-04T09:00"` |
| Simple recurrence | `--every` | `--every "1h"` |
| Cron expression | `--cron` | `--cron "0 9 * * 1-5"` |

**Architecture**:
- Independent service that feeds GoalEngine
- Scheduler calls `GoalEngine.create_goal()` when scheduled time arrives
- Parses schedule expressions
- Maintains pending task queue
- Triggers goal creation at scheduled times

### 5.5 External Webhooks

**Outbound Notifications**:

Configure webhook URLs in `config.yml`:

```yaml
autopilot:
  webhooks:
    on_goal_completed: "https://example.com/webhook/goal-done"
    on_goal_failed: "https://example.com/webhook/goal-failed"
    on_dreaming_entered: "https://example.com/webhook/dreaming"
    on_dreaming_exited: "https://example.com/webhook/awake"
```

**Webhook Payload**:

```json
{
  "event": "goal_completed",
  "goal_id": "abc12345",
  "description": "Process data pipeline",
  "status": "completed",
  "timestamp": "2026-04-03T14:30:00Z",
  "summary": "Successfully processed 1000 records..."
}
```

---

## 6. File Structure

```
SOOTHE_HOME/
├── autopilot/
│   ├── GOAL.md                    # Single goal definition
│   ├── GOALS.md                   # Multiple goals definition
│   ├── inbox/                     # Incoming task files
│   │   └── TASK-001.md
│   ├── outbox/                    # Outgoing messages
│   │   └── MSG-001.json
│   ├── goals/                     # Per-goal subdirectories
│   │   ├── data-pipeline/
│   │   │   ├── GOAL.md
│   │   │   └── context.md
│   │   └── report-gen/
│   │       └── GOAL.md
│   ├── status.json                # Current autopilot state
│   └── checkpoint.json            # Last checkpoint
├── runs/
│   └── {thread_id}/
│       └── goals/
│           └── {goal_id}/
│               ├── report.json
│               └── report.md
└── memory/                        # Long-term memory (MemU)
```

---

## 7. Configuration

```yaml
autopilot:
  # Execution
  max_iterations: 50
  max_send_backs: 3              # Per-goal consensus rounds
  max_parallel_goals: 3

  # Dreaming
  dreaming_enabled: true
  dreaming_consolidation_interval: 300  # seconds
  dreaming_health_check_interval: 60    # seconds

  # Persistence
  checkpoint_interval: 10        # Iterations between periodic checkpoints

  # Scheduling
  scheduler_enabled: true
  max_scheduled_tasks: 100

  # Webhooks
  webhooks:
    on_goal_completed: null
    on_goal_failed: null
    on_dreaming_entered: null
    on_dreaming_exited: null
```

---

## 8. Implementation Phases

### Phase 1: Core Execution
- Layer 2 ↔ Layer 3 tool interface
- Consensus loop with send-back budget
- Goal lifecycle state machine

### Phase 2: Goal Management
- CriticalityEvaluator module
- Relationship auto-detection
- File-based progress tracking

### Phase 3: User Experience
- CLI commands
- TUI dashboard layout
- Daemon endpoints

### Phase 4: Integration
- Scheduler service
- Channel protocol (file-based)
- Webhook notifications
- Dreaming mode

---

## 9. Open Questions

1. Should dreaming mode have resource limits (CPU, memory caps)?
2. How to handle conflicting scheduled tasks with same cron expression?
3. Should inbox support non-markdown formats (JSON, YAML)?
4. Channel protocol: should messages have acknowledgment/retry?

---

## 10. References

- RFC-200: Layer 3 Autonomous Goal Management
- RFC-201: Layer 2 Agentic Goal Execution
- RFC-202: DAG Execution & Failure Recovery
- RFC-400: Daemon Communication Protocol
- RFC-500: CLI TUI Architecture
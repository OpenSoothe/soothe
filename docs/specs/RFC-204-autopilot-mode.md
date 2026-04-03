# RFC-204: Autopilot Mode

**RFC**: 0204
**Title**: Autopilot Mode
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-03
**Dependencies**: RFC-200, RFC-201, RFC-202, RFC-400, RFC-500

## Abstract

This RFC defines Autopilot Mode, an extension of Layer 3 that enables Soothe to operate as a long-running autonomous agent. Autopilot introduces: (1) a consensus loop for validating Layer 2 completions, (2) dreaming mode for continuous operation without termination, (3) a channel protocol for user communication, (4) a scheduler service for time-based task execution, and (5) comprehensive UX surfaces for monitoring and control. Autopilot treats Layer 2 as a black-box ReAct engine while maintaining bidirectional communication through query and proposal tools.

## Position in Architecture

### Layer 3 Extension

Autopilot extends RFC-200 (Layer 3 Autonomous Goal Management) with additional capabilities:

```
Layer 3: Autonomous Goal Management (RFC-200)
  ├─ Core: Goal DAG orchestration, Layer 2 delegation
  └─ Autopilot Extension (this RFC):
       ├─ Consensus loop with send-back budget
       ├─ Dreaming mode (no termination)
       ├─ Channel protocol for user communication
       ├─ Scheduler service for time-based tasks
       └─ UX surfaces (CLI, TUI dashboard, daemon)
```

### Relationship to RFC-200

| Aspect | RFC-200 | This RFC |
|--------|---------|----------|
| Goal creation | File-discovered + dynamic | Adds MUST confirmation, scheduler-fed |
| Layer 2 delegation | Black-box | Adds bidirectional tools |
| Completion | Layer 2 judges | Adds Layer 3 consensus validation |
| Termination | All goals resolved | Transitions to dreaming mode |
| Persistence | Checkpoint on state changes | Adds periodic + milestone checkpoints |

## 1. Execution Flow

### 1.1 Layer Delegation Model

Layer 3 treats Layer 2 as a black-box ReAct engine:

**Input**: Rich context envelope
**Output**: JudgeResult with status, evidence, confidence
**Visibility**: No intermediate step visibility

**Context Envelope Structure**:

| Category | Delivery Method | Contents |
|----------|-----------------|----------|
| Core context | System prompt | Goal description, constraints, priority |
| World info | System prompt | Current state, environment data |
| Related goals | Query tool | `get_related_goals()`, `get_goal_progress()` |
| Memory | Query tool | `search_memory(query)` |
| Instructions | System prompt | High-level guidance, success criteria |

### 1.2 Bidirectional Layer 2 ↔ Layer 3 Communication

Layer 2 can query and propose updates through tools:

**Query Operations** (read-only):
- `get_related_goals()` — Goals that might inform current work
- `get_goal_progress(goal_id)` — Status of another goal
- `get_world_info()` — Current world state snapshot
- `search_memory(query)` — Cross-thread memory lookup

**Proposal Operations** (queued, applied after iteration):
- `report_progress(status, findings)` — Update current goal progress
- `add_finding(content, tags)` — Contribute to context ledger
- `suggest_goal(description, priority)` — Propose new goal
- `flag_blocker(reason, dependencies)` — Signal goal is blocked

**Queuing Semantics**: Proposals collected during Layer 2 execution, applied by Layer 3 after iteration completes. Preserves black-box abstraction while enabling dynamic adaptation.

### 1.3 Consensus Loop

Layer 3 validates Layer 2's completion judgment:

**Process**:
1. Layer 2 returns `JudgeResult` with `status: "done"` and confidence
2. Layer 3 reflection LLM evaluates holistically:
   - Evidence quality and completeness
   - Success criteria satisfaction
   - Finding coherence
3. Layer 3 decides: accept, send back, or suspend

**Send-Back Mechanics**:
- Separate send-back budget per goal (default: 3 rounds)
- Refined instructions accompany send-back
- Independent from Layer 2's ReAct iteration budget

**Budget Exhaustion**:
- Suspended goals preserved with current state
- Continue with other ready goals
- Dependency-driven reactivation when blockers clear

### 1.4 Termination → Dreaming Transition

Autopilot does not terminate—it transitions to dreaming mode:

**Trigger**: All goals resolved (completed or failed)

**Pre-Dreaming Signal**:
- Send `dreaming_entered` message via channel protocol
- User can submit new tasks before dreaming begins

**Dreaming Mode Activities**:

| Activity | Description | Frequency |
|----------|-------------|-----------|
| Memory consolidation | Extract patterns, merge duplicates, summarize | Continuous |
| Background indexing | Re-index vectors, optimize search, warm caches | Periodic |
| Goal anticipation | Analyze patterns, draft plans for predicted tasks | Periodic |
| Health monitoring | Self-checks, resource usage, anomaly alerts | Periodic |

**Resource Limits**: No enforced limits. Dreaming runs freely; consolidation and indexing are lightweight operations. User monitors via health checks if concerned.

**Dreaming Exit Triggers**:
- New task submitted via inbox
- User sends `wake` signal via channel
- Scheduled task becomes due

## 2. Goal Management Extensions

### 2.1 Goal Creation Sources

**File-Discovered**:
- `SOOTHE_HOME/autopilot/GOAL.md` — Single goal
- `SOOTHE_HOME/autopilot/GOALS.md` — Multiple goals
- `SOOTHE_HOME/autopilot/goals/*/GOAL.md` — Per-goal subdirectories

**Autopilot-Created**:
- Layer 2 proposals via `suggest_goal()`
- Layer 3 reflection findings
- Scheduled tasks from SchedulerService

### 2.2 MUST Goal Confirmation

CriticalityEvaluator determines if goal requires user approval:

**Rule-Based Signals**:
- Affects external systems
- Security implications
- High resource cost
- Modifies user data
- Irreversible operations

**LLM-Judged Signals**:
- Context impact
- Risk assessment
- Reversibility
- Dependency breadth

**Output**: `criticality: "must" | "should" | "nice"`

MUST goals queue for user confirmation before creation.

### 2.3 Goal Lifecycle Extensions

**Extended States** (7 total):

| State | Meaning | Entry From |
|-------|---------|------------|
| pending | Waiting for dependencies | Created, reactivated |
| active | Being executed | pending → activated |
| validated | Layer 3 accepted completion | active → accepted |
| completed | Finished successfully | validated → reported |
| failed | Unrecoverable error | active → error |
| suspended | Budget exhausted, needs context | active → exhausted |
| blocked | External input needed | active → blocked |

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

### 2.4 Goal Relationships

**Relationship Types**:

| Type | Semantics | Scheduler Behavior |
|------|-----------|-------------------|
| `depends_on` | Hard dependency | Wait for completion |
| `informs` | Soft dependency | Enrich if available |
| `conflicts_with` | Mutual exclusion | Serialize execution |

**Discovery**:
- Explicit declaration in `GOAL.md` frontmatter
- Auto-detection by Layer 3 during execution

**Auto-Detection Signals**:

| Signal | Relationship | Confidence |
|--------|--------------|------------|
| Resource read overlap | `informs` | Medium |
| Resource write overlap | `conflicts_with` | High |
| Findings semantic correlation | `informs` | Variable (LLM) |
| Execution interference | `conflicts_with` | High |

### 2.5 Progress Tracking

**Dual Storage**:

| Storage | Purpose | Content |
|---------|---------|---------|
| Goal files | Quick status | Frontmatter, Progress section |
| Run artifacts | Audit trail | `runs/{thread_id}/goals/{goal_id}/` |

**Update Behavior**:
- Status changes → frontmatter
- Progress updates → Progress section
- Step details → run artifacts
- Original file structure preserved

## 3. Channel Protocol

### 3.1 Message Structure

Message-centric protocol for user ↔ Soothe communication:

```python
@dataclass
class ChannelMessage:
    type: str           # e.g., "task_submit", "status_update"
    payload: dict       # Type-specific content
    timestamp: datetime
    sender: str         # "user", "soothe", "system"
    requires_ack: bool  # True for critical messages
```

**Acknowledgment Behavior**:
- Messages with `requires_ack: true` require acknowledgment
- Critical message types: `blocker_alert`, `dreaming_entered`, MUST goal confirmations
- Unacknowledged messages retry with exponential backoff (max 3 retries)
- Non-critical messages are fire-and-forget

### 3.2 Message Types

**User → Soothe**:

| Type | Payload | Description |
|------|---------|-------------|
| `task_submit` | `{description, priority?, context?}` | New task request |
| `task_cancel` | `{goal_id}` | Cancel goal |
| `signal_interrupt` | `{}` | Pause execution |
| `signal_resume` | `{}` | Resume execution |
| `query_status` | `{}` | Request state |
| `feedback` | `{goal_id, content}` | User guidance |

**Soothe → User**:

| Type | Payload | Description |
|------|---------|-------------|
| `status_update` | `{state, active_goals}` | State transition |
| `goal_progress` | `{goal_id, status, progress}` | Goal update |
| `finding_report` | `{goal_id, content}` | Significant finding |
| `blocker_alert` | `{goal_id, reason}` | Blocked, needs input |
| `dreaming_entered` | `{}` | Entering dreaming |
| `session_summary` | `{goals_completed, findings}` | Periodic digest |

### 3.3 Transport

**Initial Implementation**: File-based
- Inbox: `autopilot/inbox/` — Accepts `.md` files only
- Outbox: `autopilot/outbox/`

**Inbox Format**: Markdown only. Keeps parsing simple and aligns with goal file format. Programmatic submissions should generate markdown files.

**Future Extensions**: IM, email adapters via plugin system

## 4. Scheduler Service

### 4.1 Location

`soothe/cognition/scheduler/` — Independent service feeding GoalEngine.

### 4.2 Capabilities

| Feature | CLI Flag | Example |
|---------|----------|---------|
| Delayed execution | `--delay` | `--delay "2h"` |
| Specific time | `--at` | `--at "2026-04-04T09:00"` |
| Simple recurrence | `--every` | `--every "1h"` |
| Cron expression | `--cron` | `--cron "0 9 * * 1-5"` |

### 4.3 Architecture

- Scheduler calls `GoalEngine.create_goal()` when scheduled time arrives
- Parses schedule expressions (cron, simple recurrence, delay)
- Maintains pending task queue
- Survives restarts via checkpoint

### 4.4 Same-Cron Conflict Handling

When multiple tasks share identical cron expressions:

- **Sequential execution** — Tasks execute one after another, not in parallel
- **Ordering** — By creation time (earliest first), or by `priority` field if specified
- **Guarantee** — No overlap between same-cron tasks

## 5. User Experience

### 5.1 CLI Commands

CLI is a control surface, not a monitoring interface:

```
soothe autopilot submit "task"      # Submit new task
soothe autopilot status             # Overall state
soothe autopilot list               # List goals
soothe autopilot goal <id>          # Goal details
soothe autopilot cancel <id>        # Cancel goal
soothe autopilot approve <id>       # Approve MUST goal
soothe autopilot reject <id>        # Reject proposed goal
soothe autopilot wake               # Exit dreaming
soothe autopilot dream              # Force enter dreaming
soothe autopilot inbox              # View pending tasks
```

**Output Behavior**: No streaming—submit and check status.

### 5.2 TUI Dashboard

Read-only dashboard, distinct from chat mode:

**Panels**:
- Goal DAG — Visual graph with status
- Status Summary — State, iterations, active goals
- Findings — Key discoveries
- Controls — Display of available CLI commands

**Layout**:
- Wide: Horizontal split (DAG left, panels right)
- Narrow: Vertical stack

**No Interactive Controls**: All actions via CLI.

### 5.3 Daemon Interface

Daemon mirrors CLI capabilities:

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

**WebSocket Events**:
- `autopilot.status_changed`
- `autopilot.goal_created`
- `autopilot.goal_progress`
- `autopilot.goal_completed`
- `autopilot.dreaming_entered`
- `autopilot.dreaming_exited`

## 6. Integration

### 6.1 Daemon Hosting

Autopilot runs within daemon process:
- Same process, shared state
- Activates on explicit request only
- No separate process management

### 6.2 Thread Model

Thread per goal for parallel execution:
- Main session: `{session_id}`
- Parallel goals: `{session_id}__goal_{goal_id}`
- Isolated LangGraph state per thread

### 6.3 Persistence

**Checkpoint Triggers**:
- Goal completed/failed/suspended/blocked
- Before dreaming
- User interrupt
- Every N iterations (configurable)

**Checkpoint Contents**:
- GoalEngine state
- Relationships
- Accumulated findings
- Scheduler pending tasks

### 6.4 External Webhooks

Outbound notifications configured in `config.yml`:

```yaml
autopilot:
  webhooks:
    on_goal_completed: "https://example.com/webhook/goal-done"
    on_goal_failed: "https://example.com/webhook/goal-failed"
    on_dreaming_entered: "https://example.com/webhook/dreaming"
    on_dreaming_exited: "https://example.com/webhook/awake"
```

## 7. File Structure

```
SOOTHE_HOME/
├── autopilot/
│   ├── GOAL.md                    # Single goal
│   ├── GOALS.md                   # Multiple goals
│   ├── inbox/                     # Incoming tasks
│   ├── outbox/                    # Outgoing messages
│   ├── goals/                     # Per-goal subdirs
│   │   └── {goal-name}/
│   │       └── GOAL.md
│   ├── status.json                # Current state
│   └── checkpoint.json            # Last checkpoint
├── runs/{thread_id}/goals/{goal_id}/
│   ├── report.json
│   └── report.md
└── memory/                        # Long-term memory
```

## 8. Configuration

```yaml
autopilot:
  # Execution
  max_iterations: 50
  max_send_backs: 3
  max_parallel_goals: 3

  # Dreaming
  dreaming_enabled: true
  dreaming_consolidation_interval: 300
  dreaming_health_check_interval: 60

  # Persistence
  checkpoint_interval: 10

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

## 9. Stream Events

| Type | Fields | Description |
|------|--------|-------------|
| `soothe.autopilot.dreaming_entered` | `timestamp` | Entered dreaming mode |
| `soothe.autopilot.dreaming_exited` | `timestamp`, `trigger` | Exited dreaming |
| `soothe.autopilot.goal_validated` | `goal_id`, `confidence` | Layer 3 accepted |
| `soothe.autopilot.goal_suspended` | `goal_id`, `reason` | Budget exhausted |
| `soothe.autopilot.send_back` | `goal_id`, `remaining_budget`, `feedback` | Sent back to Layer 2 |
| `soothe.autopilot.relationship_detected` | `from_goal`, `to_goal`, `type`, `confidence` | Auto-detected relationship |
| `soothe.autopilot.checkpoint.saved` | `thread_id`, `trigger` | Checkpoint persisted |

## 10. Constraints

- Layer 2 remains black-box—no mid-execution intervention
- Proposals queued, not applied immediately
- Send-back budget per goal, not global
- TUI is read-only—all control via CLI
- Channel protocol generic for future transport extensions

## 11. Implementation Phases

### Phase 1: Core Execution
- Layer 2 ↔ Layer 3 tool interface
- Consensus loop with send-back budget
- Extended goal lifecycle

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

## 12. Design Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Resource limits for dreaming? | No limits | Consolidation/indexing are lightweight; user monitors via health checks |
| Same-cron conflicts? | Sequential execution | Order by creation/priority; guarantees no overlap |
| Inbox formats? | Markdown only | Simple parsing, aligns with goal format; scripts generate markdown |
| Message acknowledgment? | Required for critical only | `requires_ack` field; retry with backoff for blockers/MUST goals |

## Related Documents

- [RFC-200](./RFC-200-autonomous-goal-management.md) — Layer 3 Foundation
- [RFC-201](./RFC-201-agentic-goal-execution.md) — Layer 2 Execution
- [RFC-202](./RFC-202-dag-execution.md) — DAG Execution
- [RFC-400](./RFC-400-daemon-communication.md) — Daemon Protocol
- [RFC-500](./RFC-500-cli-tui-architecture.md) — CLI/TUI Architecture

## Changelog

### 2026-04-03
- Initial RFC draft
- Defined consensus loop with send-back budget
- Defined dreaming mode and transitions
- Defined channel protocol
- Defined scheduler service
- Defined UX surfaces (CLI, TUI, daemon)
- Defined goal lifecycle extensions (7 states)
- Defined relationship types and auto-detection
- Resolved open questions: no dreaming limits, sequential same-cron, markdown-only inbox, ack-required for critical messages

---

*Autopilot Mode extends Layer 3 with continuous operation, consensus validation, and comprehensive user control surfaces.*
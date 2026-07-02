# RFC-204: Autopilot Mode

**RFC**: 204
**Title**: Autopilot Mode
**Status**: Implemented — runtime architecture refined by RFC-222 (revised 2026-05-28)
**Kind**: Architecture Design
**Created**: 2026-04-03
**Updated**: 2026-05-28
**Dependencies**: RFC-200, RFC-201, RFC-203, RFC-222, RFC-450, RFC-500
**Related**: RFC-229 (Cron Service for Autopilot — natural language scheduled jobs)

> **Compatibility note (2026-05-28)**: This RFC defines autopilot's **user-facing surface** — file layout (`SOOTHE_HOME/autopilot/`), CLI commands (`soothe autopilot ...`), HTTP endpoints (`/autopilot/*`), and consensus/dreaming semantics. The **runtime implementation** — daemon-owned `AutopilotService`, subprocess worker dispatch, `GoalDispatchContextBundle`, `WorkspaceReservation`, sticky-affinity `WorkerPool` — is specified in RFC-222 (revised). The two are complementary: RFC-204 owns "what users see and submit," RFC-222 owns "how the daemon executes it."
>
> **Update (2026-05-30)**: The file-based inbox/outbox channel transport (`autopilot/inbox/`, `autopilot/outbox/`) has been removed. Task submission and control use HTTP REST (`/api/v1/autopilot/*`) and CLI commands backed by the daemon-owned `AutopilotService`.

## Abstract

This RFC defines Autopilot Mode, an autonomous extension that enables Soothe to operate as a long-running agent. Autopilot introduces: (1) a consensus loop for validating StrangeLoop completions, (2) dreaming mode for continuous operation without termination, (3) a channel protocol for user communication, (4) a scheduler service for time-based task execution, and (5) comprehensive UX surfaces for monitoring and control. Autopilot treats StrangeLoop as a black-box ReAct engine while maintaining bidirectional communication through query and proposal tools.

## Position in Architecture

### Autonomous Goal Management Extension

Autopilot extends RFC-200 (Autonomous Goal Management) with additional capabilities:

```
Autonomous Goal Management (RFC-200)
  ├─ Core: Goal DAG orchestration, StrangeLoop delegation
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
| StrangeLoop delegation | Black-box | Adds bidirectional tools |
| Completion | StrangeLoop judges | Adds Autopilot consensus validation |
| Termination | All goals resolved | Transitions to dreaming mode |
| Persistence | Checkpoint on state changes | Adds periodic + milestone checkpoints |

## 1. Execution Flow

### 1.1 Delegation Model

Autopilot treats StrangeLoop as a black-box Plan-and-Execute engine:

**Input**: Rich context envelope
**Output**: PlanResult with status, evidence, confidence, goal_progress
**Visibility**: No intermediate step visibility

**Context Envelope Structure**:

| Category | Delivery Method | Contents |
|----------|-----------------|----------|
| Core context | System prompt | Goal description, constraints, priority |
| World info | System prompt | Current state, environment data |
| Related goals | Query tool | `get_related_goals()`, `get_goal_progress()` |
| Memory | Query tool | `search_memory(query)` |
| Instructions | System prompt | High-level guidance, success criteria |

### 1.2 Bidirectional StrangeLoop ↔ Autopilot Communication

StrangeLoop can query and propose updates through tools:

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

**Queuing Semantics**: Proposals collected during StrangeLoop execution, applied by Autopilot after iteration completes. Preserves black-box abstraction while enabling dynamic adaptation.

### 1.3 Consensus Loop

Autopilot validates StrangeLoop's completion judgment:

**Process**:
1. StrangeLoop returns `PlanResult` with `status: "done"` and confidence
2. Autopilot reflection LLM evaluates holistically:
   - Evidence quality and completeness
   - Success criteria satisfaction
   - Finding coherence
3. Autopilot decides: accept, send back, or suspend

**Send-Back Mechanics**:
- Separate send-back budget per goal (default: 3 rounds)
- Refined instructions accompany send-back
- Independent from StrangeLoop's Plan-and-Execute iteration budget

**Budget Exhaustion**:
- Suspended goals preserved with current state
- Continue with other ready goals
- Dependency-driven reactivation when blockers clear

**Reflection LLM Decision Criteria**:

| Decision | Conditions | Outcome |
|----------|------------|---------|
| **Accept** | Evidence satisfies success criteria; high confidence (>0.8); no unresolved blockers | Goal → `validated` state |
| **Send back** | Evidence incomplete; low confidence (<0.8); minor gaps in findings | Refined instructions → StrangeLoop retry |
| **Suspend** | Budget exhausted (3 send-backs); unrecoverable blocker; external dependency required | Goal → `suspended` state, await resolution |

**Suspension Triggers** (explicit conditions):
1. Send-back budget exhausted (3 rounds without acceptable result)
2. External blocker identified (user input required, resource unavailable)
3. Dependency on suspended/blocked goal
4. Unrecoverable error (tool failure, permission denied, timeout exceeded)

> **Implementation Note**: The reflection LLM is configured via `agentic.reflection_model` (separate from the StrangeLoop planner/executor model). Reflection prompts include: goal description, success criteria, accumulated evidence, StrangeLoop confidence score, and iteration history. The decision output is structured (`decision: accept | send_back | suspend`, `reasoning: string`, `refined_instructions: string?`).

### 1.4 Termination → Dreaming Transition

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
- New task submitted via HTTP/CLI (`AutopilotService.submit_task`)
- User sends `wake` signal via HTTP/CLI
- Scheduled task becomes due

> **Implementation Reference**: Dreaming mode semantics are defined at the user-facing level in this section. Runtime implementation details — including multi-loop dreaming coordination, LLM-driven memory distillation, and proactive DAG restructuring — are specified in RFC-625 §5 (AutopilotMonitor Dreaming Submodule). Full semantics for cross-workspace dreaming, RAG integration, and topic-based scoping are deferred to a future RFC.

## 2. Goal Management Extensions

### 2.1 Goal Creation Sources

**File-Discovered**:
- `SOOTHE_HOME/autopilot/GOAL.md` — Single goal
- `SOOTHE_HOME/autopilot/GOALS.md` — Multiple goals
- `SOOTHE_HOME/autopilot/goals/*/GOAL.md` — Per-goal subdirectories

**Autopilot-Created**:
- StrangeLoop proposals via `suggest_goal()`
- Autopilot reflection findings
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
| validated | Autopilot accepted completion | active → accepted |
| completed | Finished successfully | validated → reported |
| failed | Unrecoverable error | active → error |
| suspended | Budget exhausted, needs context | active → exhausted |
| blocked | External input needed | active → blocked |

**State Transitions**:

```
pending → active           (ready_goals() activates)
active → validated         (Autopilot accepts completion)
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
- Auto-detection by Autopilot during execution

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

> **Removed (2026-05-30)**: The file-based inbox/outbox transport described in earlier drafts of this section is no longer implemented. User communication for autopilot uses HTTP REST endpoints (§5.3) and daemon platform channels (RFC-620). The message type taxonomy below remains useful for event payloads and future adapters.

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

**Current implementation**: HTTP REST via daemon-owned `AutopilotService` (`POST /api/v1/autopilot/submit`, `POST /api/v1/autopilot/wake`, etc.). Platform messaging adapters (RFC-620) are separate from autopilot task submission.

**API Specifications**:
- **HTTP REST endpoints**: See `docs/specs/rest-api-spec.md` for thread management, configuration, and file operation endpoints. Autopilot-specific HTTP endpoints (`/api/v1/autopilot/*`) are defined in RFC-228 (Autopilot Job IPC Commands) §3.3.
- **WebSocket protocol**: See `docs/specs/asyncapi.yaml` for the full WebSocket message schema, including job creation/status/cancel commands and autopilot event subscriptions.
- **IPC commands**: RFC-228 defines WebSocket IPC commands for desktop client integration (`job_create`, `job_status`, `job_pause`, `job_resume`, `job_cancel`, `job_dag`, `job_guidance`, `autopilot_subscribe`).

**Removed**: File-based inbox/outbox directories (`autopilot/inbox/`, `autopilot/outbox/`).

## 4. Scheduler Service

> **Extension**: RFC-229 (Cron Service for Autopilot) extends this scheduler with natural language job submission, database persistence, and TUI command `/cron` (plus CLI commands `soothe cron list/show/cancel`). The CronService wraps SchedulerService for schedule math and dispatches due jobs through the same AutopilotService goal workflow.

### 4.1 Location

`packages/soothe/src/soothe/core/goal_engine/scheduled_tasks.py` (`SchedulerService`) — persisted task scheduling feeding GoalEngine.

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
| `soothe.autopilot.goal_validated` | `goal_id`, `confidence` | Autopilot accepted |
| `soothe.autopilot.goal_suspended` | `goal_id`, `reason` | Budget exhausted |
| `soothe.autopilot.send_back` | `goal_id`, `remaining_budget`, `feedback` | Sent back to StrangeLoop |
| `soothe.autopilot.relationship_detected` | `from_goal`, `to_goal`, `type`, `confidence` | Auto-detected relationship |
| `soothe.autopilot.checkpoint.saved` | `thread_id`, `trigger` | Checkpoint persisted |

## 10. Constraints

- StrangeLoop remains black-box—no mid-execution intervention
- Proposals queued, not applied immediately
- Send-back budget per goal, not global
- TUI is read-only—all control via CLI
- Channel protocol generic for future transport extensions

## 11. Implementation Phases

### Phase 1: Core Execution
- StrangeLoop ↔ Autopilot tool interface
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
- HTTP REST autopilot control surface
- Webhook notifications
- Dreaming mode

## 12. Gap Analysis & Implementation Plan

After initial Phases 1-4 implementation, 12 gaps remain. These are organized into implementation groups:

### Gap Inventory

| # | Gap | Severity | Group | Phase | Status (2026-06-07) |
|---|-----|----------|-------|-------|---------------------|
| 1 | `_send_autopilot_webhook()` called but undefined | Bug | A | 4 | — |
| 2 | `get_world_info()` tool missing | Missing | B | 1 | — |
| 3 | `search_memory()` tool missing | Missing | B | 1 | — |
| 4 | `add_finding()` and `suggest_goal()` tools missing | Missing | B | 1 | See Group C |
| 5 | ProposalQueue not wired to GoalEngine | Missing | C | 1 | See Group C |
| 5a | GoalCompletionChunk.goal_directives field missing | Missing | C | 1 | See Group C |
| 5b | GoalEngine.apply_directives() not implemented | Missing | C | 1 | See Group C |
| 6 | LLM-judged criticality is placeholder only | Partial | D | 2 | — |
| 7 | MUST confirmation not wired into execution loop | Missing | D | 2 | — |
| 8 | Relationship auto-detection entirely missing | Missing | D | 2 | — |
| 9 | File-based progress tracking incomplete | Partial | E | 2 | — |
| 10 | WebSocket events not emitted | Missing | F | 3 | — |
| 11 | Dreaming "goal anticipation" activity missing | Missing | F | 4 | — |
| 12 | Autopilot config schema missing from SootheConfig | Missing | F | 4 | — |

### Group A: Broken Code

**Gap 1 — `_send_autopilot_webhook()` not defined**

- **Location**: `_runner_autonomous.py:653` calls `await self._send_autopilot_webhook(...)` but method doesn't exist on `AutonomousMixin`
- **Fix**: Add `_send_autopilot_webhook(self, event_type: str, payload: dict)` method that instantiates `WebhookService` from config and calls `send_webhook`. Wire additional call sites on `goal_failed`, `dreaming_entered`, `dreaming_exited`.
- **Dependency**: Requires Gap 12 (config schema) for webhook URL resolution.

### Group B: Missing StrangeLoop Tools

**Gap 2 — `get_world_info()` tool**

- New `GetWorldInfoTool` in `tools/goals/implementation.py`
- Returns: current goal ID, iteration count, available subagents, workspace path, active goals count
- Read-only, no external dependencies

**Gap 3 — `search_memory()` tool**

- New `SearchMemoryTool` in `tools/goals/implementation.py`
- Delegates to memory protocol's `recall(query, limit=5)` — already available
- Returns list of recalled memory snippets

**Gap 4 — StrangeLoop proposal tools**

- `add_finding()` and `suggest_goal()` tools in `tools/proposal/` (see Group C for full specification)
- Both write to `ProposalQueue` attached to `LoopRuntimeContext`
- Signature: `add_finding(summary, relevance_score?, tags?)`, `suggest_goal(description, priority?, depends_on?, rationale?)`

All StrangeLoop proposal tools added to `create_strangeloop_tools()` return confirmation string.

### Group C: Proposal Queuing (Updated 2026-06-07)

**Gap 5 — ProposalQueue exists but not wired**

**Status (2026-06-07):**
| Component | Status |
|-----------|--------|
| `ProposalQueue` class | ✅ Implemented (`proposal_queue.py`) |
| Unit tests | ✅ Passing (`test_proposal_queue.py`) |
| StrangeLoop tools (`suggest_goal`, `add_finding`) | ❌ Not implemented |
| Runner drains proposals | ❌ Not connected |
| GoalDirective application | ❌ Not connected |

**Implementation design (RFC-229 integration):**

The proposal queue provides **proactive path** for StrangeLoop → Autopilot communication. A **reactive path** via `GoalDirective` is also required. Both paths unify at `GoalCompletionChunk.goal_directives`.

#### Proactive Path: StrangeLoop Tools → ProposalQueue → GoalDirective

**New tools in `tools/proposal/`:**

| Tool | Proposal Type | Purpose |
|------|---------------|---------|
| `suggest_goal` | `suggest_goal` | Proactively request a subgoal mid-execution |
| `add_finding` | `add_finding` | Record discoverable insight for context projection |

```python
@tool
def suggest_goal(
    description: str,
    priority: int = 50,
    depends_on: list[str] = [],
    rationale: str = "",
) -> str:
    """Suggest a new subgoal for the current goal's DAG.

    Use when you identify a prerequisite or subtask that should be
    handled separately before continuing the current goal.

    Args:
        description: What the suggested goal should accomplish.
        priority: 0-100, higher = more urgent. Default 50.
        depends_on: Goal IDs this suggestion depends on (optional).
        rationale: Why this goal is needed.

    Returns:
        Confirmation string that suggestion was queued.
    """
```

```python
@tool
def add_finding(
    summary: str,
    relevance_score: float = 0.7,
    tags: list[str] = [],
) -> str:
    """Record a finding for context projection to child goals.

    Args:
        summary: Brief description of the finding (max 2000 chars).
        relevance_score: 0.0-1.0, how relevant to the overall goal.
        tags: Optional categorization tags.

    Returns:
        Confirmation string that finding was queued.
    """
```

**ProposalQueue access pattern:**
- Runner creates `ProposalQueue` per `_run_single_autopilot_goal` dispatch
- Queue injected into `LoopRuntimeContext.proposal_queue`
- Tools access via CoreAgent execution context

**Runner wiring (`_runner_autopilot_worker.py`):**

```python
async def _run_single_autopilot_goal(...):
    proposal_queue = ProposalQueue()

    async for event in strange_loop.run_with_progress(..., proposal_queue=proposal_queue):
        # ... handle events ...

    # Drain and convert proposals after StrangeLoop completes
    proposals = proposal_queue.drain()
    proposal_directives = _proposals_to_directives(proposals, source_goal_id=job.goal_id)

    # Merge with reflection directives (see reactive path below)
    all_directives = reflection_directives + proposal_directives

    yield _goal_completion_chunk(..., directives=all_directives)
```

#### Reactive Path: Reflection → GoalCompletionChunk → GoalEngine.apply_directives()

**Gap 5a — GoalCompletionChunk extension**

Current `GoalCompletionChunk` (RFC-222 §"Stream Contract"):
```python
class GoalCompletionChunk(BaseModel):
    type: Literal["soothe.internal.autopilot.goal_completion"] = ...
    goal_id: str
    outcome: Literal["completed", "failed", "needs_replan"]
    goal_result: GoalResult
    context_contribution: GoalDispatchContextContribution
    evidence: EvidenceBundle | None
```

**Extension:**
```python
payload = {
    "type": "soothe.internal.autopilot.goal_completion",
    "goal_id": job.goal_id,
    "outcome": outcome,
    "attempt": job.attempt,
    "context_contribution": contribution.model_dump(mode="json"),
    "goal_directives": [d.model_dump(mode="json") for d in directives],  # NEW
}
```

**Gap 5b — GoalEngine.apply_directives()**

Location: `engine.py:1243` (TODO comment)

```python
async def apply_directives(
    self,
    directives: list[GoalDirective],
    source_goal_id: str,
) -> list[str]:
    """Apply goal directives from GoalCompletionChunk.

    Args:
        directives: List of GoalDirective to apply.
        source_goal_id: Goal that emitted these directives (for parent_id default).

    Returns:
        List of newly created goal IDs.
    """
```

**Action handlers:**

| Action | Implementation |
|--------|----------------|
| `create` | `create_goal(description, priority, parent_id=parent_id or source_goal_id, depends_on)` |
| `decompose` | Log warning + skip (future work) |
| `adjust_priority` | `goal.priority = d.priority` (clamp to 0-100) |
| `add_dependency` | `goal.depends_on.extend(d.depends_on)` (dedupe) |
| `fail` | `fail_goal(d.goal_id, evidence=d.rationale)` |
| `complete` | `complete_goal(d.goal_id)` |

**Parent_id defaulting:**
- If `GoalDirective.parent_id` is None, `create_goal` receives `source_goal_id`
- Creates natural subgoal hierarchy without explicit parent_id required

#### Unified Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AGENTLOOP WORKER (Subprocess)                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Mid-iteration (Proactive Path):                                    │
│    suggest_goal tool ──► ProposalQueue.enqueue()                    │
│    add_finding tool ──► ProposalQueue.enqueue()                     │
│                                                                     │
│  End-of-goal (Reactive Path):                                       │
│    Planner.reflect() ──► Reflection.goal_directives                 │
│                                                                     │
│  Runner merges both:                                                │
│    proposals = ProposalQueue.drain()                                │
│    proposal_directives = _proposals_to_directives(proposals)        │
│    all_directives = reflection_directives + proposal_directives     │
│                                                                     │
│  Emit:                                                              │
│    GoalCompletionChunk(goal_directives=all_directives)              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    DAEMON AUTOPILOTSERVICE                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  _route_chunk(GoalCompletionChunk):                                 │
│    goal_engine.apply_directives(chunk.goal_directives)              │
│      ──► create_goal() for "create" actions                         │
│      ──► DAG now has subgoals → scheduling loop picks them up       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Deferred tools:**
- `report_progress`: Lower priority, observability use case
- `flag_blocker`: Lower priority, maps to existing backoff mechanism

**Implementation phases for Group C:**

| Phase | Scope | Files |
|-------|-------|-------|
| C.1 | GoalCompletionChunk extension + apply_directives | `engine.py`, `_runner_autopilot_worker.py`, `daemon/autopilot/service.py` |
| C.2 | Reflection directive extraction | `_runner_autopilot_worker.py` |
| C.3 | StrangeLoop tools + ProposalQueue wiring | `tools/proposal/`, `core/loop/__init__.py`, `core/loop/state/schemas.py` |

### Group D: Goal Management

**Gap 6 — LLM-judged criticality**

- In `criticality.py`, replace the LLM placeholder with actual LLM call
- Add `_evaluate_with_llm(description, priority, model)` async function:
  - Prompt LLM with risk criteria: external systems, security, cost, data modification, irreversibility, dependency breadth
  - Structured output: `{"risk_level": "high|medium|low", "reasons": [...]}`
  - High risk → elevate to "must"; medium → "should"
- `evaluate_criticality()` gains optional `model` parameter when `use_llm=True`

**Gap 7 — MUST confirmation wired into execution loop**

- When `suggest_goal` proposals are dequeued in runner:
  - Call `evaluate_criticality(description, priority, use_llm=True, model=self._model)`
  - If "must": store in pending confirmations file, send `must_goal_confirmation` via channel outbox
  - If "should"/"nice": create goal immediately via `goal_engine.create_goal()`
- Pending confirmations stored as JSON at `SOOTHE_HOME/autopilot/pending_confirmations.json`
- CLI `approve/reject` commands read/write this file directly
- Runner polls the file during execution loop to pick up user decisions

**Gap 8 — Relationship auto-detection**

- New module `packages/soothe/src/soothe/core/goal_engine/relationship_detector.py`
- `detect_relationships(completed_goal, all_goals)` function:
  - **`informs`**: Text overlap between completed goal's findings/description and other goals' descriptions. Shared tags increase confidence.
  - **`conflicts_with`**: Both goals reference same resource paths (file patterns, tool names) with write intent. High confidence auto-apply.
  - **`depends_on`**: If goal B's description references goal A's output artifacts.
- Emits `relationship_detected` event with `from_goal`, `to_goal`, `type`, `confidence`
- Called after goal completion, before marking complete
- Confidence threshold: >=0.8 auto-apply, 0.5-0.8 flag for review

### Group E: Progress Tracking

**Gap 9 — File-based progress tracking**

- In `goal_engine.py`, extend `update_goal_file_status()` to also maintain a `## Progress` section
- Add `_append_goal_progress(goal_id, entry: str)`:
  - Opens goal's GOAL.md, finds `## Progress` section (creates if missing)
  - Appends `[{timestamp}] {entry}` line
- Called when `ReportProgressTool` is used and when proposals are processed
- Ensure `runs/{thread_id}/goals/{goal_id}/` directory created on goal execution start

### Group F: Integration

**Gap 10 — WebSocket events**

- Add 6 event types to daemon's WebSocket broadcast:
  - `autopilot.status_changed`, `autopilot.goal_created`, `autopilot.goal_progress`, `autopilot.goal_completed`, `autopilot.dreaming_entered`, `autopilot.dreaming_exited`
- Map existing `soothe.autopilot.*` custom events from runner to WebSocket format
- Wire `_custom()` calls in runner to emit the missing events
- Daemon event filter already supports custom events — just need to add autopilot types to the whitelist

**Gap 11 — Dreaming goal anticipation**

- In `dreaming.py`, add `_anticipate_goals()` method
- Analyzes memory patterns and recently completed goals
- Drafts candidate future tasks as markdown files to `SOOTHE_HOME/autopilot/draft_goals/`
- Not auto-created — user reviews and submits via CLI/inbox
- Lightweight: pattern matching + LLM generation if model available, text template fallback

**Gap 12 — Autopilot config schema**

- Add `AutopilotConfig` Pydantic model to `config.py`:
  ```python
  class AutopilotConfig(BaseModel):
      max_iterations: int = 50
      max_send_backs: int = 3
      max_parallel_goals: int = 3
      dreaming_enabled: bool = True
      dreaming_consolidation_interval: int = 300
      dreaming_health_check_interval: int = 60
      checkpoint_interval: int = 10
      scheduler_enabled: bool = True
      max_scheduled_tasks: int = 100
      webhooks: dict[str, str | None] = {}
  ```
- Add to `SootheConfig` as `autopilot: AutopilotConfig = Field(default_factory=AutopilotConfig)`
- Replace hardcoded values in runner, dreaming, scheduler with config-driven values
- Wire webhook URL resolution from `config.autopilot.webhooks`

### Implementation Order

1. **Fix bugs first**: Gap 1 (webhook method) + Gap 12 (config schema) — unblocks webhook wiring
2. **Wire up existing pieces**: Gap 5 (proposal queue), Gap 10 (WebSocket events)
3. **Add missing tools**: Gaps 2, 3, 4 (new tools)
4. **Add missing logic**: Gap 6 (LLM criticality), Gap 7 (MUST confirmation), Gap 9 (progress tracking)
5. **Add new features**: Gap 8 (relationship detection), Gap 11 (goal anticipation)

---

## 13. Design Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Resource limits for dreaming? | No limits | Consolidation/indexing are lightweight; user monitors via health checks |
| Same-cron conflicts? | Sequential execution | Order by creation/priority; guarantees no overlap |
| Inbox formats? | Markdown only | Simple parsing, aligns with goal format; scripts generate markdown |
| Message acknowledgment? | Required for critical only | `requires_ack` field; retry with backoff for blockers/MUST goals |

## Related Documents

- [RFC-200](./RFC-200-autonomous-goal-management.md) — Goal Management Foundation
- [RFC-201](./RFC-201-strangeloop-plan-execute-loop.md) — StrangeLoop Execution
- [RFC-450](./RFC-450-daemon-communication-protocol.md) — Daemon Protocol
- [RFC-500](./RFC-500-cli-tui-architecture.md) — CLI/TUI Architecture

## Changelog

### 2026-06-07
- **Major update to Group C (Proposal Queuing):** Expanded Gap 5 with full integration design for ProposalQueue → GoalDirective → GoalEngine pathway.
- Added **Gap 5a** (GoalCompletionChunk.goal_directives) and **Gap 5b** (GoalEngine.apply_directives) to gap inventory.
- Defined **dual-path architecture:** proactive (StrangeLoop tools → ProposalQueue) and reactive (Reflection → goal_directives), unified at GoalCompletionChunk.
- Specified `suggest_goal` and `add_finding` tool implementations with full signatures.
- Added Runner wiring for ProposalQueue lifecycle, StrangeLoop injection, and daemon-side `_route_chunk` consumer.
- Defined implementation phases C.1, C.2, C.3 for Group C.
- Related design draft: `docs/drafts/2026-06-07-goal-directive-proposal-integration-design.md`

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
- Status changed from Draft to Active
- Added gap analysis identifying 12 implementation gaps across all 4 phases
- Added implementation plan with 5 groups (A-F) and ordered execution plan

---

*Autopilot Mode extends autonomous goal management with continuous operation, consensus validation, and comprehensive user control surfaces.*
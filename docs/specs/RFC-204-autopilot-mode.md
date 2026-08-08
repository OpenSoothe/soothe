# RFC-204: Autopilot Mode

**RFC**: 204
**Title**: Autopilot Mode
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-04-03
**Updated**: 2026-08-08
**Dependencies**: RFC-200, RFC-201, RFC-203, RFC-222, RFC-450, RFC-500
**Related**: RFC-229 (Cron Service for Autopilot),
RFC-230 (job maturity; host probes ≠ per-goal report-commit judgment),
[RFC-231](RFC-231-looprail-rail-exec.md) (LoopRail + Rail Exec),
[RFC-232](RFC-232-waveplan-flat-semistructured-ingest.md) (flat WavePlan wire),
[RFC-625](RFC-625-autopilot-monitor-context-engine-unification.md) (CE `GoalNode.report` / Monitor),
design draft [2026-08-08-autopilot-report-commit-judgment-design.md](../archive/drafts/2026-08-08-autopilot-report-commit-judgment-design.md),
[IG-725](../impl/IG-725-remove-evidence-turns-trust-sloop.md)
(no evidence-follow-up turns),
[IG-693](../impl/IG-693-rail-subgoal-consensus-exhaustion-recovery.md)
(rail-bound send-back exhaustion → fail + maker replant)

> **Scope**: This RFC owns Autopilot’s **user-facing surface** — `SOOTHE_HOME/autopilot/` layout, CLI (`soothe autopilot …`), HTTP (`/api/v1/autopilot/*`), report-commit judgment (§1.3), and dreaming semantics. Daemon runtime (`AutopilotService`, WorkerPool, workspace reservation, CE integration) is specified in RFC-222 / RFC-625. Per-goal judgment is report-commit driven; LoopRail owns rail DAG structure; host MUST NOT re-collect workspace evidence for the per-goal gate.

## Abstract

This RFC defines Autopilot Mode, an autonomous extension that enables Soothe to operate as a long-running agent. Autopilot introduces: (1) **report-commit judgment** for validating StrangeLoop completions from the CE-stored goal report (no second evidence pass), (2) dreaming mode for continuous operation without termination, (3) a channel protocol for user communication, (4) a scheduler service for time-based task execution, and (5) comprehensive UX surfaces for monitoring and control. Autopilot treats StrangeLoop as a black-box ReAct engine; rail-bound DAG structure is owned by LoopRail (RFC-231); soft pending-plan / dep / priority revisions may accompany the report-commit judge (bounded ops). Mid-run proposal tools are out of scope.

## Position in Architecture

### Autonomous Goal Management Extension

Autopilot extends RFC-200 (Autonomous Goal Management) with additional capabilities:

```
Autonomous Goal Management (RFC-200)
  ├─ Core: Goal DAG orchestration, StrangeLoop delegation
  └─ Autopilot Extension (this RFC):
       ├─ Report-commit judgment (CE GoalReport projection) + send-back budget
       ├─ Bounded CE DAG revise on the same judge reaction
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
| Completion | StrangeLoop judges | Adds Autopilot report-commit judgment (CE report SoT) |
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

StrangeLoop can query Autopilot-owned state through read-only tools (when
implemented):

**Query Operations** (read-only):
- `get_related_goals()` — Goals that might inform current work
- `get_goal_progress(goal_id)` — Status of another goal
- `get_world_info()` — Current world state snapshot
- `search_memory(query)` — Cross-thread memory lookup

**DAG mutation (host-owned, not mid-run tools):**
- Reflection may attach `GoalDirective`s on the completion chunk; the daemon
  applies them via `ContextEngine.apply_directives`.
- Follow-up / decompose goals are created by LoopRail builtins (rail-bound jobs)
  or AutopilotMonitor health / post-completion verification (non-rail).
- Mid-run DAG mutation tools (`suggest_goal` / `ProposalQueue`) are out of scope
  ([IG-703](../impl/IG-703-remove-suggest-goal-proposal-queue.md)).

### 1.3 Report-Commit Judgment

Autopilot validates StrangeLoop completions **only after** the goal report is
committed to ContextEngine. The StrangeLoop ledger report is the evidence SoT;
the host **projects** `GoalNode.report` into the judge and MUST NOT re-collect
workspace evidence for this gate. Job-level structural acceptance remains
RFC-230 maturity, not this loop.

**Control-plane split**:

| Concern | Owner |
|---------|--------|
| Decompose / phase order / fan-out | LoopRail (RFC-231) — deterministic YAML builtins/guards |
| Schedule ready goals | Autopilot dispatch + WorkerPool (status/deps only) |
| Execution + ledger report | StrangeLoop (always write a report on any loop end) |
| Persist report + emit commit | ContextEngine `commit_goal_report` |
| Accept / send_back / fail + bounded DAG revise | AutopilotService on `goal_report_committed` |

**Process**:
1. StrangeLoop ends a loop (done / failed / cancelled / crash / max_iter) and
   persists a report in its ledger (minimal report required if work was thin).
2. Host upserts CE `GoalNode.report`, bumps `report_revision`, emits
   **`goal_report_committed`** (sole Autopilot judgment trigger).
3. AutopilotService handler (idempotent on `(goal_id, report_revision)`):
   - Project CE report + relevant CE DAG slice (no tools, no workspace open).
   - Optional deterministic gates from CE/rail state (e.g. WavePlan present).
   - Structured LLM judge → `accept` | `send_back` | `fail` + `reasoning`,
     plus optional **bounded DAG ops**.
4. Apply validated `dag_ops`, then apply verdict; notify LoopRail
   (`goal_completed` / `goal_send_back` / `goal_failed`). Rail builtins remain
   deterministic — the judge does **not** choose next rail verbs.

**Trigger rules**:
- Judgment fires on **report commit only**.
- Bare CE status transitions (`pending` / `active`) MUST NOT invoke the judge.
- Worker completion MUST ensure report commit and MUST NOT invent a second
  judgment path outside CE.
- If a report is still missing after loop end → **no Autopilot LLM**; engine
  recovery / retries only.

**Judge input**: projection of CE-stored goal report (ledger-backed) + goal
description + CE DAG slice needed for bounded ops. Fields such as
`evidence_summary` / `full_output` are judge inputs only when already present
inside that committed report.

**Bounded DAG ops** (same judge reaction; optional):

| Op | Allowed |
|----|---------|
| wire / unwire `depends_on` | yes |
| set priority | yes |
| update pending briefs / pending-plan fields | yes |
| spawn / cancel goal | only via existing rail/monitor allowlists |
| free-form decompose / merge / new topology | **no** (LoopRail owns structure) |

**Send-Back Mechanics**:
- Separate send-back budget per goal (default: 3 rounds).
- Rework brief = the **same judge call’s `reasoning`** (no second reactor LLM).
- Independent from StrangeLoop's Plan-and-Execute iteration budget.

**Budget Exhaustion**:
- Budget is **per subgoal** (`GoalNode.send_back_count` /
  `max_send_backs`), never the job root’s counter.
- Exhaustion MUST transition the subgoal to **`failed`** and emit
  `goal_failed` so host recovery can act (LoopRail / monitor backoff /
  engine health). Autopilot MUST NOT park goals in `suspended` awaiting
  an operator for judgment (IG-707).
- DAG health MUST NOT auto-reset send-back-exhausted *suspended* goals;
  failed workers use engine recovery (IG-697) when deps allow.
- Autopilot MUST NOT encode tool- or VCS-specific “done” gates (git commit,
  cargo, pytest hard-accept) as judgment overrides — those policies live in
  rails / host maturity probes (RFC-230), never in the per-goal report-commit
  path.

**Judge decision criteria**:

| Decision | Conditions | Outcome |
|----------|------------|---------|
| **Accept** | Goal text satisfied by CE report projection; no unresolved blockers | Goal → `completed`; rail `goal_completed`; apply `dag_ops` |
| **Send back** | Report incomplete vs goal; minor gaps; retry warranted | `send_back` with `reasoning` as brief; count toward budget; apply `dag_ops` |
| **Fail** | Unrecoverable blocker; send-back budget exhausted; judge LLM error | Goal → `failed`; host recovery (LoopRail / monitor / engine) |

**Failure / park triggers** (explicit conditions):

1. Send-back budget exhausted on any goal → **fail** (not suspend)
2. Judge reports fundamentally blocked / unrecoverable → **fail**
3. Judge chooses `send_back` (including thin/minimal report) → retry; fail on budget exhaust
4. Dependency on suspended/blocked goal → scheduler **blocked** (not judgment)
5. Explicit job pause (`pause_job`, rail `pause_for_user`) → **suspend** (job-level only)

> **Implementation Note**: The judge LLM is configured via `agentic.reflection_model` (separate from the StrangeLoop planner/executor model). Structured output: `decision: accept | send_back | fail`, `reasoning`, optional `dag_ops`. Prefer **accept** when StrangeLoop Plan-Execute-Eval completed and the CE report supports the goal; do **not** reject solely for missing git/file proof narrative outside the report, and do **not** re-dispatch a second proof mission on the same goal ([IG-725](../impl/IG-725-remove-evidence-turns-trust-sloop.md)). After accept, LoopRail advances on events; AutopilotMonitor may perform non-rail DAG health without inventing rail phases. Headless clarification / empty terminal MUST still produce a **minimal CE report** then map to `send_back` (or `fail` on budget), not operator-wait `suspend`. See design draft `docs/archive/drafts/2026-08-08-autopilot-report-commit-judgment-design.md` and [IG-707](../impl/IG-707-autopilot-automatic-consensus-no-operator-suspend.md).

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
- Reflection `GoalDirective`s on `GoalCompletionChunk` (applied by CE)
- LoopRail builtins / AutopilotMonitor decompose (non-rail)
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
| failed | Unrecoverable / budget exhausted | active → error / exhaust |
| suspended | Explicit job pause (operator / rail) | pause_job / pause_for_user |
| blocked | Waiting on deps / external gate | active → blocked |

**State Transitions**:

```
pending → active           (ready_goals() activates)
active → validated         (Autopilot accepts completion)
active → failed            (send-back budget exhausted / consensus fail / unrecoverable)
active → suspended         (explicit job pause only)
active → blocked           (dependency / external gate)
suspended → pending        (resume_job / deps resolved)
blocked → pending          (deps / gate cleared)
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
- **IPC commands**: RFC-228 defines WebSocket IPC commands for autopilot job control (`job_create`, `job_status`, `job_pause`, `job_resume`, `job_cancel`, `job_dag`, `job_guidance`, `autopilot_subscribe`).

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
soothe autopilot jobs               # List root jobs
soothe autopilot goals              # List goals
soothe autopilot goal <id>          # Goal details
soothe autopilot stop <id>          # Stop goal
soothe autopilot stop --all         # Stop all open goals
soothe autopilot stop --job <id>    # Stop job and descendants
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
agent:
  loop:
    # Shared StrangeLoop iteration budget (interactive + Autopilot)
    max_iterations: 99

  autopilot:
    # Lifecycle / scheduling (not StrangeLoop knobs)
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
| `soothe.autopilot.goal_suspended` | `goal_id`, `reason` | Explicit job pause |
| `soothe.autopilot.send_back` | `goal_id`, `remaining_budget`, `feedback` | Sent back after report-commit judge |
| `goal_report_committed` (CE/Autopilot) | `goal_id`, `report_revision` | Canonical judgment trigger (RFC-625) |
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
| 4 | ~~`add_finding()` / `suggest_goal()` tools~~ | Retired | C | — | Removed (IG-703); use host spawners |
| 5 | ~~ProposalQueue → GoalEngine~~ | Retired | C | — | Removed (IG-703) |
| 5a | GoalCompletionChunk.goal_directives field | Done | C | 1 | Reflection path retained |
| 5b | GoalEngine / CE.apply_directives() | Done | C | 1 | Reflection path retained |
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

~~Retired.~~ Mid-run `suggest_goal` / `add_finding` / `ProposalQueue` tools were
never shipped as agent tools and are removed from the architecture
([IG-703](../impl/IG-703-remove-suggest-goal-proposal-queue.md)). Dynamic goals
are created by LoopRail, AutopilotMonitor, intake, or reflection directives.

### Group C: Goal Directives (Updated 2026-08-06)

**Errata (2026-08-06):** The proactive path (StrangeLoop tools → `ProposalQueue`
→ `_proposals_to_directives`) is **removed**. Only the reactive path remains:

`Reflection.goal_directives` → `GoalCompletionChunk.goal_directives` →
`ContextEngine.apply_directives()`.

**Gap 5 / ProposalQueue** — ~~Obsolete~~ (deleted with IG-703).

#### Reactive Path: Reflection → GoalCompletionChunk → CE.apply_directives()

**Gap 5a — GoalCompletionChunk extension** — Implemented.

```python
payload = {
    "type": "soothe.internal.autopilot.goal_completion",
    "goal_id": job.goal_id,
    "outcome": outcome,
    "attempt": job.attempt,
    "context_contribution": contribution.model_dump(mode="json"),
    "goal_directives": [d.model_dump(mode="json") for d in directives],
}
```

**Gap 5b — ContextEngine.apply_directives()** — Implemented.

```python
async def apply_directives(
    self,
    directives: list[GoalDirective],
    source_goal_id: str,
) -> list[str]:
    """Apply goal directives from GoalCompletionChunk."""
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
│  End-of-goal:                                                       │
│    Planner.reflect() ──► Reflection.goal_directives                 │
│    Emit GoalCompletionChunk(goal_directives=…)                      │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    DAEMON AUTOPILOTSERVICE                          │
├─────────────────────────────────────────────────────────────────────┤
│  On goal_completion:                                                │
│    ce.apply_directives(chunk.goal_directives, source_goal_id)       │
│      ──► create_goal() for "create" actions                         │
│      ──► DAG now has subgoals → scheduling loop picks them up       │
│  Host spawners (independent of directives):                         │
│    LoopRail builtins / AutopilotMonitor decompose (non-rail)        │
└─────────────────────────────────────────────────────────────────────┘
```

**Implementation phases for Group C:**

| Phase | Scope | Status |
|-------|-------|--------|
| C.1 | GoalCompletionChunk + apply_directives | Done |
| C.2 | Reflection directive extraction | Done (worker) |
| C.3 | StrangeLoop proposal tools + ProposalQueue | **Cancelled** (IG-703) |

### Group D: Goal Management

**Gap 6 — LLM-judged criticality**

- In `criticality.py`, replace the LLM placeholder with actual LLM call
- Add `_evaluate_with_llm(description, priority, model)` async function:
  - Prompt LLM with risk criteria: external systems, security, cost, data modification, irreversibility, dependency breadth
  - Structured output: `{"risk_level": "high|medium|low", "reasons": [...]}`
  - High risk → elevate to "must"; medium → "should"
- `evaluate_criticality()` gains optional `model` parameter when `use_llm=True`

**Gap 7 — MUST confirmation wired into execution loop**

- When host-side goal creation would add a high-criticality goal
  (intake / directive `create` / scheduled submit):
  - Call `evaluate_criticality(description, priority, use_llm=True, model=…)`
  - If "must": store in pending confirmations file, send `must_goal_confirmation` via channel outbox
  - If "should"/"nice": create goal immediately via `ce.create_goal()`
- Pending confirmations stored as JSON at `SOOTHE_HOME/autopilot/pending_confirmations.json`
- CLI `approve/reject` commands read/write this file directly
- Scheduling loop / monitor picks up user decisions (not mid-run proposal drain)

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
- Called when goal progress is recorded (operator / monitor) and when directives are applied
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
2. **Wire up existing pieces**: Gap 5a/5b (goal_directives + apply_directives — done), Gap 10 (WebSocket events)
3. **Add missing query tools**: Gaps 2, 3 (read-only StrangeLoop tools; Gap 4 cancelled)
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

### 2026-08-08
- **Report-commit judgment** is the normative per-goal completion gate (§1.3):
  StrangeLoop ledger → CE `GoalNode.report` → `goal_report_committed` →
  Autopilot LLM judge (accept / send_back / fail) + bounded CE DAG revise;
  LoopRail stays deterministic for structure/phases. See design draft
  `docs/archive/drafts/2026-08-08-autopilot-report-commit-judgment-design.md`.
- Pure report-commit trigger; always write a minimal report on loop end;
  send_back brief = same judge `reasoning`.
- Removed user-facing compatibility / dual-path / “formerly consensus” hedges
  from the normative body (changelog retains prior history).

### 2026-08-06
- **Retire proactive ProposalQueue path** ([IG-703](../impl/IG-703-remove-suggest-goal-proposal-queue.md)):
  remove `suggest_goal` / `add_finding` / `ProposalQueue` from the architecture.
- Group C is now reflection `GoalDirective`s + host spawners (LoopRail / monitor) only.
- Gap inventory: Gaps 4–5 marked retired; 5a/5b retained as done.

### 2026-06-07
- **Major update to Group C (Proposal Queuing):** Expanded Gap 5 with full integration design for ProposalQueue → GoalDirective → GoalEngine pathway.
- Added **Gap 5a** (GoalCompletionChunk.goal_directives) and **Gap 5b** (GoalEngine.apply_directives) to gap inventory.
- Defined **dual-path architecture:** proactive (StrangeLoop tools → ProposalQueue) and reactive (Reflection → goal_directives), unified at GoalCompletionChunk.
- Specified `suggest_goal` and `add_finding` tool implementations with full signatures.
- Added Runner wiring for ProposalQueue lifecycle, StrangeLoop injection, and daemon-side `_route_chunk` consumer.
- Defined implementation phases C.1, C.2, C.3 for Group C.
- Related design draft: `docs/archive/drafts/2026-06-07-goal-directive-proposal-integration-design.md`

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

*Autopilot Mode extends autonomous goal management with continuous operation, report-commit judgment, and comprehensive user control surfaces.*
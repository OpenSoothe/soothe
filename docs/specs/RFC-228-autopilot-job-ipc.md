# RFC-228: Autopilot Job IPC Commands

**RFC**: 228
**Title**: Autopilot Job IPC Commands for Desktop Integration
**Status**: Proposed
**Kind**: Protocol Specification
**Created**: 2026-06-04
**Updated**: 2026-08-04
**Dependencies**: RFC-222 (Autopilot and Goal Engine Architecture), RFC-450 (Daemon Communication Protocol)
**Related**: RFC-625 (AutopilotMonitor and ContextEngine Unification), RFC-626 (Entity Model and State Management Consolidation — LoopState Elimination), RFC-229 (Cron Service for Autopilot — cron IPC commands), IG-677 (Job↔Loop Index), IG-613 (protocol-1 `autopilot_*` RPCs)

## Abstract

This RFC defines WebSocket IPC commands for desktop client interaction with the daemon's AutopilotService. Commands cover job lifecycle (create, status, pause, resume, cancel), DAG visualization data retrieval, user guidance absorption, and autopilot worker event subscription. These commands enable the Desktop app (RFC-700) to monitor and influence autopilot sessions through the singleton AutopilotService.

It also defines the protocol-1 aggregate snapshot RPC `autopilot_top` for the CLI live dashboard (`soothe autopilot top`): active-only jobs → goal DAG → JobLoopIndex loops in one round-trip.

## Overview

### Problem Statement

RFC-700 (Desktop App Product Redesign) requires IPC commands to:
1. Create and manage autopilot jobs (root goals submitted to AutopilotService)
2. Query job status and DAG structure for visualization
3. Send user guidance comments to ContextEngine
4. Subscribe to autopilot worker events (bypassing `autopilot__*` filter from RFC-222 §467-468)

Current RFC-450 IPC commands support loop-centric interactions (`input`, `command`, `subscribe_thread`) but lack autopilot-specific operations.

### Solution

Extend the daemon IPC protocol with a new command category: **Autopilot Job Commands**. These commands:
- Operate on the singleton AutopilotService (RFC-222 §86-89)
- Target root Goals (jobs) managed by ContextEngine
- Support desktop DAG visualization and Loop Observation Room (LOR)

### Scope

| In Scope | Out of Scope |
|----------|--------------|
| Job creation/status/cancel IPC | Job persistence (SQLite in desktop app) |
| DAG snapshot for visualization | Real-time DAG diff streaming (push) |
| Active-only aggregate top snapshot (`autopilot_top`) | Interactive CLI keybindings / `--all` history |
| User guidance absorption | Guidance result feedback |
| Worker event subscription | Worker pool management |

## Terminology

| Term | Definition | Source |
|------|------------|--------|
| **Job** | Root GoalNode submitted to AutopilotService (parent_id=None) | RFC-626 §44 |
| **GoalNode** | CE entity model for goals; root GoalNode = Job | RFC-626 §40-44 |
| **AutopilotService** | Daemon-owned singleton managing ContextEngine and WorkerPool | RFC-222 §86-89, RFC-625 §1 |
| **ContextEngine** | Unified goal/step DAG management (supersedes GoalEngine) | RFC-624, RFC-625 |
| **Worker** | StrangeLoop executor bound to one goal assignment | RFC-222 / IG-677 |
| **Worker loop_id** | Assignment id `autopilot__{job_id}__{uuid}` under `data/loops/{loop_id}/` | IG-677 |
| **Pool slot** | Reusable capacity key `autopilot__slot_NNN` (sticky affinity); not a filesystem key | IG-677 |
| **JobLoopIndex** | Durable job↔loop membership (`autopilot:job_loops:{job_id}`) | IG-677 |

> **Job Abstraction Clarification (RFC-626)**: The Job concept originally referenced "root Goal" from GoalEngine's flat goal dict (RFC-222). RFC-626 eliminated GoalEngine and consolidated entity models under ContextEngine. A **Job** is now defined as a **root GoalNode** (GoalNode with `parent_id=None`) managed by ContextEngine. No intermediate `Goal` wrapper model exists — Job IPC commands query ContextEngine directly for root goals. This unification ensures:
> - Job state = GoalNode state (no dual-source-of-truth)
> - Job lifecycle transitions = GoalNode status transitions
> - Job cancellation operates on GoalNode and descendant StepNodes via CE DAG traversal
>
> **IG-677**: Live mapping of active goals to workers remains `GoalNode.assigned_loop_id`.
> Historical / multi-assignment membership is `JobLoopIndex` (not CE). One job may have
> many assignment `loop_id`s over its lifetime; `job_status.workers` lists only **active** ones.

## Protocol Specification

### Message Format

Follows RFC-450 JSON message format with required `type` field.

#### `request_id` Semantics

All client → server commands accept an optional `request_id` field (string). The following rules govern its use:

| Rule | Description |
|------|-------------|
| **Generation** | Client-generated. Recommended format: UUIDv4 or `<client-prefix>-<seq>`. |
| **Uniqueness scope** | Unique within a single client session (WebSocket connection). Two different clients may reuse the same `request_id`. |
| **Echo requirement** | If `request_id` is present in the request, the server MUST echo it verbatim in the corresponding response message. |
| **Absence handling** | If `request_id` is omitted, the server processes normally but omits it from the response. Clients that do not need request correlation may omit it. |
| **Event correlation** | `request_id` does NOT appear on async events (`soothe.goal.*`, `soothe.worker.*`). Events are correlated to jobs via `goal_id`/`job_id`, not `request_id`. |
| **Error responses** | `error` messages echo `request_id` if the failing request carried one. |

### Client → Server Messages

| Type | Fields | Description |
|------|--------|-------------|
| `job_create` | `goal` (req, string), `verification_rules` (opt, string), `user_id` (opt, string), `request_id` (opt) | Submit root goal to AutopilotService, returns job_id (goal.id). `user_id` is session-derived; see §Authentication Model. |
| `job_status` | `job_id` (req, string), `request_id` (opt) | Query job state: goal status, counts, assigned workers |
| `job_pause` | `job_id` (req, string), `request_id` (opt) | Pause goal execution (suspends scheduling) |
| `job_resume` | `job_id` (req, string), `request_id` (opt) | Resume paused goal execution |
| `job_cancel` | `job_id` (req, string), `request_id` (opt) | Cancel root goal and all descendants |
| `job_dag` | `job_id` (req, string), `request_id` (opt) | Get ContextEngine DAG snapshot for visualization |
| `job_guidance` | `job_id` (req, string), `goal_id` (opt, string), `text` (req, string), `request_id` (opt) | Send user guidance to ContextEngine (absorbed as BackoffDecision) |
| `autopilot_subscribe` | `request_id` (opt) | Subscribe to all autopilot worker events (bypasses `autopilot__*` filter) |
| `autopilot_unsubscribe` | `request_id` (opt) | Release autopilot worker subscription |
| `autopilot_top` | `request_id` (opt) | Protocol-1 aggregate: active jobs → filtered DAG → active loops (CLI `top`) |

> **Protocol-1 note**: Desktop job envelopes use `type: "job_*"`. CLI / `AsyncCommandClient` use protocol-1 `type: "request"` with `method: "autopilot_*"` (IG-613). `autopilot_top` is defined as a protocol-1 method; the response body shape below is the `result` payload.

### Server → Client Messages

| Type | Fields | Description |
|------|--------|-------------|
| `job_create_response` | `job_id` (req, string), `status` (req, string), `request_id` (opt) | Job created, job_id = goal.id (8-char hex) |
| `job_status_response` | `job_id` (req), `status` (req), `active_goals` (req, int), `completed_goals` (req, int), `total_goals` (req, int), `workers` (opt, array), `last_error` (opt), `request_id` (opt) | Job state snapshot |
| `job_pause_response` | `job_id` (req), `status` (req, string: "paused"), `request_id` (opt) | Pause confirmed |
| `job_resume_response` | `job_id` (req), `status` (req, string: "running"), `request_id` (opt) | Resume confirmed |
| `job_cancel_response` | `job_id` (req), `status` (req, string: "cancelled"), `request_id` (opt) | Cancel confirmed |
| `job_dag_response` | `job_id` (req), `dag` (req, object), `request_id` (opt) | DAG snapshot for visualization |
| `job_guidance_response` | `job_id` (req), `goal_id` (opt), `absorbed` (req, bool), `request_id` (opt) | Guidance received by ContextEngine |
| `autopilot_subscribe_response` | `client_id` (req), `subscribed` (req, bool), `request_id` (opt) | Subscription confirmed |
| `autopilot_unsubscribe_response` | `client_id` (req), `subscribed` (req, bool: false), `request_id` (opt) | Unsubscription confirmed |
| `autopilot_top` result | See §autopilot_top | Active-only forest snapshot for CLI live dashboard |
| `error` | `code` (req), `message` (req), `details` (opt) | Protocol error (see error codes below) |

### Error Codes

| Code | Description |
|------|-------------|
| `JOB_NOT_FOUND` | job_id does not match any root goal in ContextEngine |
| `GOAL_NOT_FOUND` | goal_id does not match any goal in DAG |
| `AUTOPILOT_NOT_READY` | AutopilotService not initialized or in degraded state |
| `JOB_ALREADY_PAUSED` | Pause requested on already paused job |
| `JOB_ALREADY_RUNNING` | Resume requested on already running job |
| `JOB_COMPLETED` | Operation not valid on completed job |
| `JOB_FAILED` | Operation not valid on failed job |
| `GUIDANCE_REJECTED` | ContextEngine rejected guidance (invalid directive) |
| `JOB_NOT_AUTHORIZED` | user_id does not match job owner; only the job owner may perform this action |

---

## RFC-626 Entity Model Alignment

> **Note**: RFC-626 (Entity Model and State Management Consolidation) unifies entity identity under ContextEngine. This section describes how IPC commands operate on the refined entity model.

### Unified Entity Identity

Per RFC-626, the IPC protocol operates on CE entities directly:

| IPC Term | RFC-626 Entity | Notes |
|----------|---------------|-------|
| `job_id` | `GoalNode.id` | Root goal identifier, 8-char hex |
| `goal_id` | `GoalNode.id` | Any goal in DAG, same entity type |
| `status` | `GoalNode.status` | CE GoalStatus enum value |
| `workers` | `GoalNode.assigned_loop_id` | CE field (singular per goal). The IPC `workers` array aggregates one entry per **active** goal: `[{goal_id, loop_id: goal.assigned_loop_id}]`. Each GoalNode has at most one worker; the array is multi-element because multiple goals may be active simultaneously. |
| `dag` | `GoalStepDAGSnapshot` | CE `get_dag_snapshot()` result |

### Command Changes (RFC-626 Refined)

**job_create**:
- AutopilotMonitor calls `ce.create_goal()` (no GoalEngine)
- Returns `GoalNode.id` as `job_id`
- Placement analysis queries CE DAG via `ce.get_all_goals()`

**job_status**:
- Queries CE via `ce.get_goal(job_id)`
- `active_goals` = count of `ce.get_goals_by_status("active")`
- `workers` = array of `{goal_id, loop_id}` for each active goal; `loop_id` = `goal.assigned_loop_id` (singular per GoalNode). Multiple active goals → multiple array entries.
- No separate worker registry lookup

**job_dag**:
- Calls `ce.get_dag_snapshot()`
- Returns `GoalStepDAGSnapshot` serialized as JSON
- No GoalEngine DAG aggregation

**job_guidance**:
- Guidance stored in `GoalNode.guidance_accumulated` list
- Backoff reasoner reads from CE GoalNode
- No separate guidance store

### Event Stream Changes (RFC-626 Refined)

Event emission unified through CE callbacks:

| Event | CE Callback Trigger | Fields |
|-------|---------------------|--------|
| `soothe.goal.status` | `ce.on("goal_activated", ...)` | `goal_id`, `status` from GoalNode |
| `soothe.goal.progress` | `ce.on("step_completed", ...)` | `goal_id`, `steps_completed` from StepDAG |
| `soothe.goal.created` | `ce.on("goal_created", ...)` | `goal_id`, `description` from GoalNode |
| `soothe.goal.completed` | `ce.on("goal_completed", ...)` | `goal_id`, `summary` from GoalNode.report |

**Implementation**: AutopilotService subscribes to CE callbacks and emits IPC events to subscribed desktop clients.

### Data Flow (RFC-626 Unified)

```
Desktop app → WebSocket IPC → AutopilotService
  → AutopilotMonitor → ContextEngine API calls
  → CE callbacks → InternalEventBus → IPC event stream
  → Desktop app receives goal/status/progress events
```

No intermediate GoalEngine, no dual state containers, no checkpoint fallbacks.

### Event Types (Server → Client)

When subscribed via `autopilot_subscribe`, client receives these events:

| Event Namespace | Fields | Description |
|-----------------|--------|-------------|
| `soothe.goal.status` | `goal_id` (req), `status` (req), `previous_status` (opt), `reason` (opt) | Goal status transition (pending → active → completed → failed, etc.) |
| `soothe.goal.progress` | `goal_id` (req), `steps_completed` (req), `steps_total` (req), `tool_calls` (req) | Step completion and tool count update |
| `soothe.goal.created` | `goal_id` (req), `parent_id` (opt), `description` (req) | New goal added to DAG |
| `soothe.goal.completed` | `goal_id` (req), `summary` (opt), `findings` (opt) | Goal completed with result summary |
| `soothe.worker.assigned` | `goal_id` (req), `loop_id` (req) | Worker assigned to goal |
| `soothe.worker.unassigned` | `goal_id` (req), `loop_id` (opt) | Worker released from goal |

> **Note**: Internal events like `soothe.internal.backoff` are filtered from client streams (RFC-222 §308-315). Desktop receives goal-level status events only.

## Command Details

### job_create

Creates a new autopilot job by submitting a root goal to AutopilotService.

**Request**:
```json
{
  "type": "job_create",
  "goal": "Refactor the authentication module to support OAuth2.0 with proper error handling and logging.",
  "verification_rules": "All existing tests pass. No type errors. API endpoints return correct status codes.",
  "request_id": "req-001"
}
```

> **`user_id` Derivation**: The `user_id` associated with a job is **session-derived**, not passed in the request body. The daemon resolves `user_id` from the authenticated WebSocket session (RFC-450 §30-38). For authenticated sessions this is the real user identity; for unauthenticated CLI sessions in development mode, it defaults to the `http_api` pseudo-user. The resolved `user_id` is recorded on the root GoalNode at creation time and used for subsequent ownership checks (see §Authorization Rules). Clients MUST NOT send a `user_id` field in the request body; if present, it is silently ignored in favor of the session-derived value. This ensures ownership cannot be spoofed by client-supplied data.

**Response**:
```json
{
  "type": "job_create_response",
  "job_id": "a1b2c3d4",
  "status": "pending",
  "request_id": "req-001"
}
```

**Processing**:
1. AutopilotService receives goal submission
2. Daemon resolves `user_id` from the authenticated session and attaches it to the goal submission
3. AutopilotMonitor calls `ce.create_goal()` to create root GoalNode with status `pending` and `user_id` recorded on the node
4. Scheduler begins planning and worker assignment
5. Return GoalNode.id as job_id

#### `verification_rules` Lifecycle

The optional `verification_rules` field on `job_create` provides natural-language success criteria for the job. Its lifecycle is as follows:

| Phase | Behavior |
|-------|---------|
| **Submission** | Client provides `verification_rules` as a free-text string in `job_create`. Stored on the root GoalNode (e.g., `GoalNode.verification_rules` field). |
| **Planning** | Scheduler/BackoffDecision reasoner reads `verification_rules` to derive acceptance criteria for subgoal decomposition. Influences which StepNodes are generated. |
| **Execution** | Workers (StrangeLoop instances) read `verification_rules` from their assigned GoalNode to self-check completion before reporting `completed`. |
| **Completion** | AutopilotService evaluates `verification_rules` before transitioning root GoalNode to `completed`. If rules are not satisfied, goal transitions to `failed` with `last_error` indicating the unsatisfied rule. |
| **Observation** | `job_status_response.last_error` reflects verification failures. `job_status` does NOT echo `verification_rules` back (it is write-once at creation). `job_dag_response` nodes expose `summary`/`findings` for completed goals (see §Node Fields). |
| **Absence** | If omitted, the job completes when all subgoals reach `completed` (no explicit verification gate). Default behavior. |

> **Note**: `verification_rules` is stored as opaque text. Structured rule evaluation (parsing into executable checks) is a future enhancement; current implementation uses LLM-based assessment during the completion phase.

### job_status

Queries current state of a job.

**Request**:
```json
{
  "type": "job_status",
  "job_id": "a1b2c3d4",
  "request_id": "req-002"
}
```

**Response**:
```json
{
  "type": "job_status_response",
  "job_id": "a1b2c3d4",
  "status": "running",
  "active_goals": 3,
  "completed_goals": 5,
  "total_goals": 12,
  "workers": [
    {"goal_id": "e5f6g7h8", "loop_id": "autopilot__a1b2c3d4__f47ac10b58cc4372a5670e02b2c3d479"},
    {"goal_id": "i9j0k1l2", "loop_id": "autopilot__a1b2c3d4__0c9f8e7d6b5a4932a1b0c9d8e7f6a543"}
  ],
  "last_error": null,
  "request_id": "req-002"
}
```

**Processing**:
1. Query ContextEngine via `ce.get_goal(job_id)` for root goal status
2. Traverse CE DAG to count active/completed/total goals
3. Collect workers currently assigned to active goals (from `GoalNode.assigned_loop_id`)
4. Return snapshot

> **`workers` Array Format**: Each element is `{goal_id, loop_id}`. Since RFC-626 assigns at most one worker per GoalNode (`assigned_loop_id`), the array contains one entry per active goal — not multiple workers per goal. An empty array indicates no goals are currently active (e.g., all suspended or completed).

### job_pause / job_resume

Controls job execution state.

**Pause Request**:
```json
{
  "type": "job_pause",
  "job_id": "a1b2c3d4"
}
```

**Pause Response**:
```json
{
  "type": "job_pause_response",
  "job_id": "a1b2c3d4",
  "status": "paused"
}
```

**Processing**:
1. Set root goal status to `suspended`
2. Scheduler stops assigning new workers
3. Active workers continue until current step completes, then pause
4. Return confirmation

**Worker Pause Semantics**:

The pause operation is **cooperative, not preemptive**. The following rules govern in-flight worker behavior:

| Aspect | Behavior |
|--------|---------|
| **Mid-tool-call handling** | A worker currently executing a tool call (e.g., file write, shell command) is **not interrupted mid-call**. The tool call runs to completion, the worker processes the result, and then pauses before initiating the next step. Pausing mid-tool-call would leave external state in an inconsistent state (partial file writes, half-run shell commands). |
| **LLM inference in progress** | If the worker is awaiting an LLM response, the inference completes normally. The worker processes the response and then pauses before the next tool call or step transition. |
| **Forced-pause timeout** | A grace period of **60 seconds** (configurable via `AutopilotConfig.pause_grace_seconds`, default 60) is granted for the current step to complete. If the step does not complete within the grace period, the daemon logs a WARNING (`autopilot.pause_grace_exceeded`) and transitions the worker to `suspended` state. The worker's current step result, if it arrives after the timeout, is **discarded** (not applied to the GoalNode). |
| **Resource handling** | Paused workers **hold their resources** — the StrangeLoop instance, LLM context, and tool handles remain allocated. This allows rapid resumption without re-initialization. Workers are NOT released back to the pool during pause; only cancel releases workers. |
| **Step completion signal** | A worker signals step completion via its normal `step_completed` callback. The daemon intercepts this when the root goal is `suspended` and parks the worker instead of scheduling the next step. |
| **New subgoal creation** | While paused, the scheduler does not decompose new subgoals. If a worker was mid-decomposition when pause was requested, the decomposition completes (it is a single planning step) but the resulting subgoals are created in `pending` state and not assigned workers. |

**Resume** reverses suspension:
1. Set root goal status to `active`
2. Scheduler resumes worker assignment
3. Paused workers resume execution from their next pending step (LLM context preserved)
4. Any subgoals created during pause transition to `active` and become eligible for worker assignment

> **Note**: Resume is idempotent — resuming an already-active job returns `JOB_ALREADY_RUNNING`. The `pause_grace_seconds` timeout is per-pause-operation; it does not accumulate across multiple pause cycles.

### job_cancel

Cancels job and all descendant goals.

**Request**:
```json
{
  "type": "job_cancel",
  "job_id": "a1b2c3d4"
}
```

**Response**:
```json
{
  "type": "job_cancel_response",
  "job_id": "a1b2c3d4",
  "status": "cancelled"
}
```

**Processing**:
1. Set root goal status to `failed` with reason "cancelled"
2. Traverse DAG, set all descendant goals to `failed`
3. Release all assigned workers
4. Workers terminate their StrangeLoop execution
5. Return confirmation

**Worker Termination Semantics**:

The cancel operation follows a **graceful-then-forced** termination protocol. The following rules govern worker shutdown:

| Aspect | Behavior |
|--------|---------|
| **Termination mode** | Workers are first asked to terminate **gracefully** (cooperative shutdown). The daemon sends a `terminate` signal to each worker's StrangeLoop, allowing it to finish the current tool call, write a partial-progress checkpoint, and exit cleanly. If the worker does not terminate within the shutdown timeout, the daemon performs **forced termination** (abrupt loop cancellation). |
| **Graceful shutdown timeout** | A grace period of **30 seconds** (configurable via `AutopilotConfig.cancel_grace_seconds`, default 30) is granted per worker. If the worker has not exited by then, forced termination is applied. |
| **Stuck-worker handling** | A worker that is unresponsive (e.g., blocked on a hung subprocess, infinite LLM token stream, or deadlocked tool) is force-terminated after the grace period. The daemon logs a WARNING (`autopilot.cancel_forced_termination`) with the worker's `loop_id`, `goal_id`, and the last known step. Forced termination cancels the underlying asyncio task or thread backing the StrangeLoop. |
| **Tool-call in progress** | During graceful shutdown, a worker mid-tool-call is allowed to complete the call, but only if it finishes within the remaining grace period. If the tool call exceeds the timeout, it is abandoned — the underlying subprocess (if any) is sent SIGTERM, then SIGKILL after 5 additional seconds. |
| **Partial side-effect cleanup** | Cancel does **not** automatically roll back side effects (written files, created branches, modified state). Workers are instructed during graceful shutdown to record a `partial_progress` note on their GoalNode describing uncommitted work. The DAG snapshot retains all partial `summary`/`findings` for forensic inspection. Cleanup of side effects is the **client's responsibility** — the daemon does not perform git reverts, file deletion, or state rollback. |
| **Worker release** | After termination (graceful or forced), the worker's `loop_id` is removed from `GoalNode.assigned_loop_id`, the worker is released back to the pool, and a `soothe.worker.unassigned` event is emitted. |
| **Idempotency** | Cancel is idempotent — cancelling an already-cancelled or completed job returns `JOB_COMPLETED` or `JOB_FAILED` without re-issuing termination signals. |
| **Concurrent cancel** | If multiple clients issue `job_cancel` for the same job concurrently, the first request processes normally; subsequent requests receive the idempotent response. Only one set of termination signals is sent. |

> **Note**: The `cancel_grace_seconds` timeout is per-worker, not per-job. Jobs with many concurrent workers may take up to `cancel_grace_seconds` to fully terminate even after the cancel response is returned (the response confirms goal status change, not worker shutdown completion). Clients should poll `job_status` to confirm workers have been released (`workers` array empty).

### job_dag

Retrieves DAG structure for visualization.

**Request**:
```json
{
  "type": "job_dag",
  "job_id": "a1b2c3d4"
}
```

**Response**:
```json
{
  "type": "job_dag_response",
  "job_id": "a1b2c3d4",
  "dag": {
    "nodes": [
      {
        "id": "a1b2c3d4",
        "description": "Refactor authentication module...",
        "status": "active",
        "priority": 100,
        "depends_on": [],
        "assigned_loop_id": null,
        "steps_completed": 0,
        "steps_total": 3,
        "tool_calls": 0
      },
      {
        "id": "e5f6g7h8",
        "description": "Add OAuth2.0 provider support",
        "status": "active",
        "priority": 80,
        "depends_on": ["a1b2c3d4"],
        "assigned_loop_id": "autopilot__a1b2c3d4__f47ac10b58cc4372a5670e02b2c3d479",
        "steps_completed": 2,
        "steps_total": 5,
        "tool_calls": 8
      },
      {
        "id": "m3n4o5p6",
        "description": "Audit existing auth endpoints for error handling gaps",
        "status": "completed",
        "priority": 90,
        "depends_on": ["a1b2c3d4"],
        "assigned_loop_id": null,
        "steps_completed": 4,
        "steps_total": 4,
        "tool_calls": 12,
        "summary": "Identified 3 endpoints (/login, /refresh, /logout) missing structured error responses. Token refresh endpoint lacks retry-on-429 logic.",
        "findings": [
          "/login returns 500 on malformed OAuth state param — needs validation middleware",
          "/refresh does not handle rate-limit (429) responses from upstream IdP",
          "/logout has no CSRF token verification on POST"
        ]
      }
    ],
    "edges": [
      {"source": "a1b2c3d4", "target": "e5f6g7h8"},
      {"source": "a1b2c3d4", "target": "i9j0k1l2"},
      {"source": "a1b2c3d4", "target": "m3n4o5p6"}
    ]
  }
}
```

**Processing**:
1. Query ContextEngine via `ce.get_dag_snapshot()` for all goals in DAG
2. Build node list with visualization-relevant fields
3. Build edge list from `depends_on` relationships
4. Return structured DAG snapshot

**Node Fields** (for React Flow visualization):
| Field | Type | Purpose |
|-------|------|---------|
| `id` | string | Goal ID (8-char hex), node key |
| `description` | string | Short description for display |
| `status` | string | Status badge coloring |
| `priority` | int | Sorting/ordering |
| `depends_on` | array | Dependency references |
| `assigned_loop_id` | string | Worker loop for navigation |
| `steps_completed` | int | Progress bar numerator |
| `steps_total` | int | Progress bar denominator |
| `tool_calls` | int | Tool count badge |
| `summary` | string | Completion summary (if completed) |
| `findings` | array | Key findings (if completed) |

### job_guidance

Sends user guidance to ContextEngine for absorption.

**Request**:
```json
{
  "type": "job_guidance",
  "job_id": "a1b2c3d4",
  "goal_id": "e5f6g7h8",
  "text": "Focus on error handling for the token refresh flow. The current approach is missing edge cases.",
  "request_id": "req-003"
}
```

**Response**:
```json
{
  "type": "job_guidance_response",
  "job_id": "a1b2c3d4",
  "goal_id": "e5f6g7h8",
  "absorbed": true,
  "request_id": "req-003"
}
```

**Processing**:
1. AutopilotService receives guidance message
2. Routes to ContextEngine (AutopilotMonitor → `ce.get_goal(goal_id)`)
3. Guidance stored in `GoalNode.guidance_accumulated` list; BackoffDecision reasoner reads from CE GoalNode (RFC-200 §208-425)
4. Guidance influences:
   - Goal priority adjustments
   - Constraint additions
   - Subgoal creation modifications
   - Execution behavior changes
5. Return absorption confirmation

**Guidance Scope**:
| `goal_id` Provided | Guidance Target |
|--------------------|-----------------|
| Yes | Specific goal and its descendants |
| No | Root goal (entire job) |

### autopilot_subscribe

Subscribes to autopilot worker events, bypassing the `autopilot__*` namespace filter.

**Request**:
```json
{
  "type": "autopilot_subscribe",
  "request_id": "req-004"
}
```

**Response**:
```json
{
  "type": "autopilot_subscribe_response",
  "client_id": "client-abc123",
  "subscribed": true,
  "request_id": "req-004"
}
```

**Processing**:
1. Register client for autopilot event namespace
2. Client receives `soothe.goal.*` and `soothe.worker.*` events
3. Events routed through EventBus (RFC-450 §62-72)
4. Worker `autopilot__*` loop events now visible to this client

> **Note**: Without this subscription, client's `subscribe_thread` requests for
> assignment loop ids (`autopilot__{job_id}__{uuid}`, or legacy `autopilot__wNNN`)
> are rejected (`autopilot__*` filter; RFC-222 / IG-677).

### autopilot_unsubscribe

Releases autopilot worker subscription.

**Request**:
```json
{
  "type": "autopilot_unsubscribe",
  "request_id": "req-005"
}
```

**Response**:
```json
{
  "type": "autopilot_unsubscribe_response",
  "client_id": "client-abc123",
  "subscribed": false,
  "request_id": "req-005"
}
```

### autopilot_top

Protocol-1 aggregate snapshot for the CLI live dashboard (`soothe autopilot top`).
One round-trip returns header pool stats plus an **active-only** forest of
jobs → filtered goal DAG → active JobLoopIndex entries (IG-677).

This is **not** push/diff streaming (still out of scope). Clients poll on an
interval (CLI default 1.0s) and redraw. Existing `job_status` / `job_dag` /
`autopilot_get_job` commands remain unchanged.

**Request** (protocol-1):
```json
{
  "type": "request",
  "method": "autopilot_top",
  "params": {},
  "request_id": "req-top-001"
}
```

**Result payload**:
```json
{
  "running": true,
  "dreaming": false,
  "loop_pool": {
    "active": 1,
    "idle": 0,
    "total": 1,
    "max": 4
  },
  "generated_at": "2026-08-04T01:00:00+00:00",
  "jobs": [
    {
      "id": "a1b2c3d4",
      "status": "active",
      "priority": 50,
      "description": "Implement auth",
      "workspace": "/path/to/ws",
      "created_at": "2026-08-04T00:50:00+00:00",
      "dag": {
        "root_id": "a1b2c3d4",
        "nodes": [
          {
            "id": "a1b2c3d4",
            "description": "Implement auth",
            "status": "active",
            "priority": 50,
            "depends_on": [],
            "assigned_loop_id": "autopilot__a1b2c3d4__f47ac10b58cc4372a5670e02b2c3d479",
            "created_at": "2026-08-04T00:50:00+00:00",
            "steps_completed": 1,
            "steps_total": 2,
            "tool_calls": 3,
            "steps": {
              "nodes": [
                {
                  "id": "UZH-01",
                  "description": "Scaffold routes",
                  "status": "completed",
                  "dependencies": []
                },
                {
                  "id": "UZH-02",
                  "description": "Add JWT",
                  "status": "pending",
                  "dependencies": ["UZH-01"]
                }
              ],
              "edges": [{"source": "UZH-01", "target": "UZH-02"}]
            }
          }
        ],
        "edges": []
      },
      "loops": [
        {
          "seq": 3,
          "loop_id": "autopilot__a1b2c3d4__f47ac10b58cc4372a5670e02b2c3d479",
          "goal_id": "a1b2c3d4",
          "status": "active",
          "attempt": 1,
          "started_at": "2026-08-04T00:59:00+00:00"
        }
      ]
    }
  ]
}
```

**Processing** (`AutopilotService.top_snapshot()`):

1. Build header from `status()` (`running`, `dreaming`, `loop_pool`) and set
   `generated_at` (UTC ISO).
2. Enumerate root goals (jobs).
3. For each job, build `dag` via existing `dag_snapshot(job_id)` (includes
   planned `GoalNode.steps` StepDAG + live counts) and load
   `loops` via `list_job_loops(job_id)`. Include root `created_at`.
   `dag_snapshot` membership is the **`parent_id` subtree** (same as cancel /
   rail descendants). Tree `edges` are `parent → child`. Per-node
   `depends_on` is scheduling metadata only — do not invert it into tree
   edges (rails often make the root depend on a child planner).
4. Apply **active filters** (server SoT):
   - Goal / job visibility uses CE `TERMINAL_STATES`
     (`completed`, `failed`, `cancelled`). Non-terminal includes
     `pending`, `active`, `blocked`, `suspended`, `awaiting_clarification`, etc.
   - Include a job if the root ∉ `TERMINAL_STATES` **or** any descendant ∉
     `TERMINAL_STATES`.
   - Keep only goal nodes with status ∉ `TERMINAL_STATES`; keep edges only when
     both endpoints remain. Nested `steps` ride along with kept goal nodes
     (step statuses use step vocab — not goal `TERMINAL_STATES`).
   - Keep only loops with `JobLoopEntry.status == "active"`.
   - Drop jobs that have no remaining visible goals after filtering.
5. Return the payload as the protocol-1 `result`.

**CLI consumer** (`soothe autopilot top`):

- Rich `Live` with alternate screen (`screen=True`) — full terminal like linux
  `top`; quit restores prior buffer (Ctrl+C).
- Flag `--interval` / `-n` (default `1.0`).
- Render ASCII tree: job → goal DAG → nested planned step DAG → loops under
  `JobLoopEntry.goal_id`. Show execution elapsed as `HH:MM:SS` from job
  `created_at` and loop `started_at`.
- Empty `jobs` → header + “No active jobs”.
- Daemon not live / mid-session RPC failure → error + non-zero exit (same as
  other autopilot CLI commands).

See also IG-686 (job artifact dir `data/jobs/{job_id}/` vs assignment loops).

**Authz**: read-only; same as `job_status` / `job_dag` (any authenticated client).

## Security and Authorization

### Authentication Model

All IPC commands require an authenticated WebSocket session (RFC-450 §30-38). The daemon associates each session with a `client_id` and a `user_id` (or `http_api` for unauthenticated CLI sessions in development mode).

### Authorization Rules

| Command | Authorization Requirement |
|---------|---------------------------|
| `job_create` | Any authenticated client may create jobs. No per-user quota in current scope. The session-derived `user_id` is recorded on the root GoalNode at creation time and serves as the job owner for subsequent ownership checks. |
| `job_status` | Any authenticated client may query any job's status (read-only, no ownership check). |
| `job_dag` | Same as `job_status` — read-only, no ownership check. |
| `autopilot_top` | Same as `job_status` — read-only aggregate snapshot, no ownership check. |
| `job_pause` / `job_resume` | **Job owner only.** The `user_id` of the requesting session must match the `user_id` recorded on the job's root GoalNode at creation time. Mismatch → `error` with code `JOB_NOT_AUTHORIZED`. |
| `job_cancel` | **Job owner only.** Same ownership check as pause/resume. Cancellation is destructive — terminates all descendant goals and releases workers. |
| `job_guidance` | Any authenticated client may submit guidance to any job (guidance is advisory, non-destructive). |
| `autopilot_subscribe` | Any authenticated client may subscribe. Subscription scope is per-session. |
| `autopilot_unsubscribe` | Session-scoped — only the session that created the subscription may unsubscribe. |

> **New Error Code**: `JOB_NOT_AUTHORIZED` — "user_id does not match job owner; only the job owner may perform this action."

### Multi-Client Contention

Multiple desktop clients may be connected simultaneously and issue conflicting lifecycle commands. The daemon resolves contention using **last-writer-wins** semantics with optimistic concurrency:

| Scenario | Resolution |
|----------|-----------|
| Client A pauses, Client B resumes simultaneously | Commands are serialized by the daemon's single-threaded IPC handler. The last command to execute wins. Both clients receive their respective response. The losing client learns of the state change via the `soothe.goal.status` event stream. |
| Client A cancels while Client B pauses | Cancel takes precedence — once a goal is `cancelled` (`failed` with reason "cancelled"), subsequent `pause`/`resume` commands return `JOB_FAILED` error. |
| Client A pauses already-paused job | Returns `JOB_ALREADY_PAUSED` error (idempotent rejection, no state change). |
| Two clients create jobs concurrently | Both succeed — each gets a distinct `job_id`. No contention. |
| Client A subscribes, Client B unsubscribes | `autopilot_unsubscribe` is session-scoped (see authz table). Client B cannot unsubscribe Client A's subscription. |

> **Optimistic Concurrency Note**: Clients should treat `job_status` as the source of truth and reconcile local state with `soothe.goal.status` events. If a client's `job_pause` succeeds but a subsequent `job_resume` from another client changes state, the first client's next `job_status` query will reflect the actual state.

### Subscription Scoping

`autopilot_subscribe` grants access to **all** autopilot worker events for the daemon's AutopilotService instance. There is no per-job or per-worker filter at the subscription level — clients receive all `soothe.goal.*` and `soothe.worker.*` events. Clients are expected to filter client-side by `goal_id`/`job_id` if they only care about specific jobs.

Future enhancement: scoped subscriptions (`autopilot_subscribe` with optional `job_id` filter) may be added if event volume becomes a concern.

## Integration with Existing Protocol

### Relationship to RFC-450 Commands

| RFC-450 Command | RFC-228 Relationship |
|-----------------|----------------------|
| `subscribe_thread` | For ordinary loops. Autopilot workers require `autopilot_subscribe` first |
| `input` | For ordinary loops. Autopilot workers use `job_guidance` for user input |
| `command` | `/detach` works for autopilot workers. Other commands filtered |

### Command Sequences

**Job Creation + Monitoring**:
```
1. autopilot_subscribe → autopilot_subscribe_response
2. job_create → job_create_response
3. (events: soothe.goal.status, soothe.worker.assigned)
4. job_dag → job_dag_response (periodic refresh)
5. job_status → job_status_response (periodic polling)
```

**Loop Observation Room**:
```
1. autopilot_subscribe (already subscribed from job view)
2. job_dag → get goal's assigned_loop_id
3. subscribe_thread(loop_id: "autopilot__a1b2c3d4__f47ac10b…") → subscription_confirmed
4. (events: soothe.loop.* for worker messages)
5. job_guidance → send comment to goal
```

**Job Control**:
```
1. job_pause → job_pause_response
2. (events: soothe.goal.status → "suspended")
3. job_resume → job_resume_response
4. (events: soothe.goal.status → "active")
```

**CLI live top** (`soothe autopilot top`):
```
1. autopilot_top → result (header + active forest)
2. (poll interval; redraw Rich Live)
3. Ctrl+C → exit
```

## Implementation Checklist

### Daemon Side

- [ ] `job_create` handler in WebSocket protocol handler
- [ ] `job_status` handler querying ContextEngine
- [ ] `job_pause` / `job_resume` handlers controlling scheduler
- [ ] `job_cancel` handler with DAG traversal
- [ ] `job_dag` handler returning snapshot structure
- [ ] `job_guidance` handler routing to ContextEngine
- [ ] `autopilot_subscribe` handler bypassing namespace filter
- [ ] `autopilot_unsubscribe` handler releasing subscription
- [ ] `autopilot_top` protocol-1 handler → `AutopilotService.top_snapshot()`
- [ ] Event emission for `soothe.goal.*` and `soothe.worker.*`

### ContextEngine Side

- [ ] Guidance absorption mechanism (BackoffDecision integration via `GoalNode.guidance_accumulated`)
- [ ] DAG snapshot export method (`ce.get_dag_snapshot()`)
- [ ] Status transition event emission (CE callbacks → InternalEventBus)
- [ ] Progress update event emission (CE `step_completed` callbacks)

### Host / CLI Side

- [ ] `AutopilotService.top_snapshot()` with `TERMINAL_STATES` + active-loop filters
- [ ] Client stubs: `autopilot_top` in soothe-client / sdk params registry
- [ ] `soothe autopilot top` Rich Live renderer

### Desktop Client Side (RFC-700)

- [ ] IPC bridge extension for job commands
- [ ] Event handler for goal/worker events
- [ ] DAG data transformation for React Flow

## Changelog

### 2026-08-04
- Added protocol-1 `autopilot_top` aggregate snapshot (active jobs → DAG → loops)
  for CLI live dashboard; documented filters via CE `TERMINAL_STATES` + IG-677
- Aligned worker `loop_id` examples with IG-677 assignment-scoped format
  (`autopilot__{job_id}__{uuid}`); documented pool slots vs loop dirs and JobLoopIndex

### 2026-07-03
- Reconciled all GoalEngine references with RFC-626 ContextEngine alignment (Command Details, Error Codes, Implementation Checklist)
- Added `request_id` semantics subsection under Message Format
- Added `verification_rules` lifecycle documentation
- Added completed node example to `job_dag` response (demonstrates `summary`/`findings` fields)
- Clarified `workers` array format vs RFC-626 singular `assigned_loop_id`
- Added `request_id` to `autopilot_unsubscribe` request/response examples
- Added Security and Authorization section (job ownership authz, multi-client contention, subscription scoping)
- Added `JOB_NOT_AUTHORIZED` error code
- Added concurrent command conflict resolution semantics
- Added RFC-624, RFC-625, RFC-626 to References

### 2026-06-04
- Initial RFC proposal
- Defined job lifecycle commands
- Defined DAG visualization command
- Defined guidance absorption command
- Defined autopilot worker subscription

## References

- RFC-200: Autonomous Goal Management
- RFC-222: Autopilot and Goal Engine Architecture
- RFC-450: Daemon Communication Protocol
- RFC-624: ContextEngine (AutopilotMonitor Unification)
- RFC-625: AutopilotMonitor and ContextEngine Unification
- RFC-626: Entity Model and State Management Consolidation — LoopState Elimination
- RFC-700: Desktop App Product Redesign
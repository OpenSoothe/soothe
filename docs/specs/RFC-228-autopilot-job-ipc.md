# RFC-228: Autopilot Job IPC Commands

**RFC**: 228
**Title**: Autopilot Job IPC Commands for Desktop Integration
**Status**: Proposed
**Kind**: Protocol Specification
**Created**: 2026-06-04
**Updated**: 2026-06-04
**Dependencies**: RFC-222 (Autopilot and Goal Engine Architecture), RFC-450 (Daemon Communication Protocol)

## Abstract

This RFC defines WebSocket IPC commands for desktop client interaction with the daemon's AutopilotService. Commands cover job lifecycle (create, status, pause, resume, cancel), DAG visualization data retrieval, user guidance absorption, and autopilot worker event subscription. These commands enable the Desktop app (RFC-700) to monitor and influence autopilot sessions through the singleton AutopilotService.

## Overview

### Problem Statement

RFC-700 (Desktop App Product Redesign) requires IPC commands to:
1. Create and manage autopilot jobs (root goals submitted to AutopilotService)
2. Query job status and DAG structure for visualization
3. Send user guidance comments to GoalEngine
4. Subscribe to autopilot worker events (bypassing `autopilot__*` filter from RFC-222 §467-468)

Current RFC-450 IPC commands support loop-centric interactions (`input`, `command`, `subscribe_thread`) but lack autopilot-specific operations.

### Solution

Extend the daemon IPC protocol with a new command category: **Autopilot Job Commands**. These commands:
- Operate on the singleton AutopilotService (RFC-222 §86-89)
- Target root Goals (jobs) managed by GoalEngine
- Support desktop DAG visualization and Loop Observation Room (LOR)

### Scope

| In Scope | Out of Scope |
|----------|--------------|
| Job creation/status/cancel IPC | Job persistence (SQLite in desktop app) |
| DAG snapshot for visualization | Real-time DAG diff streaming |
| User guidance absorption | Guidance result feedback |
| Worker event subscription | Worker pool management |

## Terminology

| Term | Definition | Source |
|------|------------|--------|
| **Job** | Root Goal submitted to AutopilotService | RFC-700 §2.2 |
| **AutopilotService** | Daemon-owned singleton managing GoalEngine and WorkerPool | RFC-222 §86-89 |
| **GoalEngine** | DAG-based goal management within AutopilotService | RFC-222 §75-89, RFC-200 |
| **Worker** | StrangeLoop subprocess assigned to execute a goal | RFC-222 §95-104 |
| **Worker loop_id** | Namespaced `autopilot__w001`, `autopilot__w002`, etc. | RFC-222 §467-468 |

## Protocol Specification

### Message Format

Follows RFC-450 JSON message format with required `type` field.

### Client → Server Messages

| Type | Fields | Description |
|------|--------|-------------|
| `job_create` | `goal` (req, string), `verification_rules` (opt, string), `request_id` (opt) | Submit root goal to AutopilotService, returns job_id (goal.id) |
| `job_status` | `job_id` (req, string), `request_id` (opt) | Query job state: goal status, counts, assigned workers |
| `job_pause` | `job_id` (req, string), `request_id` (opt) | Pause goal execution (suspends scheduling) |
| `job_resume` | `job_id` (req, string), `request_id` (opt) | Resume paused goal execution |
| `job_cancel` | `job_id` (req, string), `request_id` (opt) | Cancel root goal and all descendants |
| `job_dag` | `job_id` (req, string), `request_id` (opt) | Get GoalEngine DAG snapshot for visualization |
| `job_guidance` | `job_id` (req, string), `goal_id` (opt, string), `text` (req, string), `request_id` (opt) | Send user guidance to GoalEngine (absorbed as BackoffDecision) |
| `autopilot_subscribe` | `request_id` (opt) | Subscribe to all autopilot worker events (bypasses `autopilot__*` filter) |
| `autopilot_unsubscribe` | `request_id` (opt) | Release autopilot worker subscription |

### Server → Client Messages

| Type | Fields | Description |
|------|--------|-------------|
| `job_create_response` | `job_id` (req, string), `status` (req, string), `request_id` (opt) | Job created, job_id = goal.id (8-char hex) |
| `job_status_response` | `job_id` (req), `status` (req), `active_goals` (req, int), `completed_goals` (req, int), `total_goals` (req, int), `workers` (opt, array), `last_error` (opt), `request_id` (opt) | Job state snapshot |
| `job_pause_response` | `job_id` (req), `status` (req, string: "paused"), `request_id` (opt) | Pause confirmed |
| `job_resume_response` | `job_id` (req), `status` (req, string: "running"), `request_id` (opt) | Resume confirmed |
| `job_cancel_response` | `job_id` (req), `status` (req, string: "cancelled"), `request_id` (opt) | Cancel confirmed |
| `job_dag_response` | `job_id` (req), `dag` (req, object), `request_id` (opt) | DAG snapshot for visualization |
| `job_guidance_response` | `job_id` (req), `goal_id` (opt), `absorbed` (req, bool), `request_id` (opt) | Guidance received by GoalEngine |
| `autopilot_subscribe_response` | `client_id` (req), `subscribed` (req, bool), `request_id` (opt) | Subscription confirmed |
| `autopilot_unsubscribe_response` | `client_id` (req), `subscribed` (req, bool: false), `request_id` (opt) | Unsubscription confirmed |
| `error` | `code` (req), `message` (req), `details` (opt) | Protocol error (see error codes below) |

### Error Codes

| Code | Description |
|------|-------------|
| `JOB_NOT_FOUND` | job_id does not match any root goal in GoalEngine |
| `GOAL_NOT_FOUND` | goal_id does not match any goal in DAG |
| `AUTOPLOT_NOT_READY` | AutopilotService not initialized or in degraded state |
| `JOB_ALREADY_PAUSED` | Pause requested on already paused job |
| `JOB_ALREADY_RUNNING` | Resume requested on already running job |
| `JOB_COMPLETED` | Operation not valid on completed job |
| `JOB_FAILED` | Operation not valid on failed job |
| `GUIDANCE_REJECTED` | GoalEngine rejected guidance (invalid directive) |

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
2. GoalEngine creates root Goal with status `pending`
3. Scheduler begins planning and worker assignment
4. Return goal.id as job_id

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
    {"goal_id": "e5f6g7h8", "loop_id": "autopilot__w001"},
    {"goal_id": "i9j0k1l2", "loop_id": "autopilot__w002"}
  ],
  "last_error": null,
  "request_id": "req-002"
}
```

**Processing**:
1. Query GoalEngine.get_goal(job_id) for root goal status
2. Traverse DAG to count active/completed/total goals
3. Collect workers currently assigned to active goals
4. Return snapshot

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

**Resume** reverses suspension:
1. Set root goal status to `active`
2. Scheduler resumes worker assignment
3. Paused workers resume execution

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
        "assigned_loop_id": "autopilot__w001",
        "steps_completed": 2,
        "steps_total": 5,
        "tool_calls": 8
      }
    ],
    "edges": [
      {"source": "a1b2c3d4", "target": "e5f6g7h8"},
      {"source": "a1b2c3d4", "target": "i9j0k1l2"}
    ]
  }
}
```

**Processing**:
1. Query GoalEngine for all goals in DAG
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

Sends user guidance to GoalEngine for absorption.

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
2. Routes to GoalEngine
3. GoalEngine absorbs as BackoffDecision directive (RFC-200 §208-425)
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

> **Note**: Without this subscription, client's `subscribe_thread` requests for `autopilot__w001` etc. are rejected (RFC-222 §467-468 filter).

### autopilot_unsubscribe

Releases autopilot worker subscription.

**Request**:
```json
{
  "type": "autopilot_unsubscribe"
}
```

**Response**:
```json
{
  "type": "autopilot_unsubscribe_response",
  "client_id": "client-abc123",
  "subscribed": false
}
```

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
3. subscribe_thread(loop_id: "autopilot__w001") → subscription_confirmed
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

## Implementation Checklist

### Daemon Side

- [ ] `job_create` handler in WebSocket protocol handler
- [ ] `job_status` handler querying GoalEngine
- [ ] `job_pause` / `job_resume` handlers controlling scheduler
- [ ] `job_cancel` handler with DAG traversal
- [ ] `job_dag` handler returning snapshot structure
- [ ] `job_guidance` handler routing to GoalEngine
- [ ] `autopilot_subscribe` handler bypassing namespace filter
- [ ] `autopilot_unsubscribe` handler releasing subscription
- [ ] Event emission for `soothe.goal.*` and `soothe.worker.*`

### GoalEngine Side

- [ ] Guidance absorption mechanism (BackoffDecision integration)
- [ ] DAG snapshot export method
- [ ] Status transition event emission
- [ ] Progress update event emission

### Desktop Client Side (RFC-700)

- [ ] IPC bridge extension for job commands
- [ ] Event handler for goal/worker events
- [ ] DAG data transformation for React Flow

## Changelog

### 2026-06-04
- Initial RFC proposal
- Defined job lifecycle commands
- Defined DAG visualization command
- Defined guidance absorption command
- Defined autopilot worker subscription

## References

- RFC-222: Autopilot and Goal Engine Architecture
- RFC-450: Daemon Communication Protocol
- RFC-200: Autonomous Goal Management
- RFC-700: Desktop App Product Redesign
# RFC-229: Cron Service for Autopilot

**RFC**: 229
**Title**: Cron Service for Autopilot — Natural Language Scheduled Jobs
**Status**: Proposed
**Kind**: Architecture Design
**Created**: 2026-06-24
**Updated**: 2026-07-03
**Dependencies**: RFC-204 (Autopilot Mode), RFC-222 (Autopilot and Goal Engine Architecture), RFC-802 (Persistence Architecture)
**Related**: RFC-450 (Daemon Communication Protocol)

## Abstract

This RFC defines a cron service for Soothe's autopilot mode that enables natural language scheduled job submission. Users describe jobs in plain language (e.g., "remind me tomorrow at 9am to check the deploy"); the daemon extracts structured schedule information via LLM, persists jobs to database, monitors for due jobs, and executes them through the existing AutopilotService goal workflow. The service integrates cleanly with existing infrastructure without modifying core StrangeLoop execution semantics.

## Overview

### Problem Statement

Autopilot mode (RFC-204) enables continuous autonomous operation but lacks user-initiated scheduled task submission. Users cannot:

1. Submit jobs using natural language descriptions with embedded timing
2. Have jobs persist across daemon restarts
3. Monitor job status, history, and upcoming executions
4. Cancel or modify pending jobs

The existing SchedulerService (RFC-204 §3.4) handles daemon-internal scheduled tasks but:
- Uses JSON file persistence (not database-backed)
- Has no natural language extraction capability
- Lacks multi-user job isolation
- Provides no TUI/CLI user interface

### Solution

Introduce **CronService**, a standalone module that:
- Extracts schedule semantics from natural language via LLM
- Persists jobs to the metadata database (RFC-802)
- Monitors for due jobs and dispatches to AutopilotService
- Provides TUI command `/cron` for natural language job submission
- Provides CLI commands (`soothe cron list/show/cancel`) for job management via HTTP REST
- Supports recurring jobs with automatic rescheduling

### Scope

| In Scope | Out of Scope |
|----------|--------------|
| Natural language schedule extraction | Calendar integration ("remind me before my meeting") |
| Database persistence for jobs | System monitoring triggers ("when disk is 80% full") |
| TUI commands for job management | Client-side NL extraction (requires TUI LLM) |
| Execution via AutopilotService | Direct StrangeLoop spawn (bypassing AutopilotService) |
| Recurring job rescheduling | Job modification after submission |

## Position in Architecture

### Module Location

```
packages/soothe/src/soothe/cron/
├── __init__.py           # Public exports
├── service.py            # CronService orchestrator
├── extraction.py         # CronExtractionService (LLM-based)
├── models.py             # CronJob, ExtractionResult dataclasses
└── store.py              # CronJobStore (DB persistence adapter)
```

This placement follows the foundation module pattern (RFC-001), keeping cron as an independent service with clear boundaries.

### Relationship to Existing Services

| Service | Relationship |
|---------|-------------|
| **AutopilotService** (RFC-222) | CronService dispatches due jobs as goals via `submit_task()` |
| **SchedulerService** (RFC-204) | CronService wraps SchedulerService for schedule math; enhances with DB persistence |
| **GoalEngine** (RFC-222, RFC-625) | Jobs become goals in ContextEngine; execution via StrangeLoop |
| **Metadata Database** (RFC-802) | CronJobStore persists jobs in `cron_jobs` table |

### AutopilotService Integration Contract

CronService dispatches due jobs by calling `AutopilotService.submit_task()`. The canonical signature (defined in RFC-222 revised, RFC-625) is:

```python
async def submit_task(
    self,
    description: str,
    *,
    priority: int = 50,
    parent_id: str | None = None,
    max_retries: int | None = None,
    max_send_backs: int | None = None,
    depends_on: list[str] | None = None,
    informs: list[str] | None = None,
    source_file: str | None = None,
    workspace: str | None = None,
    cron_job_id: str | None = None,  # RFC-229: Cron job tracking for recurring rescheduling
) -> GoalNode
```

**CronService call site**: CronService passes `description`, `priority`, and `cron_job_id` (the CronJob.id) on every dispatch. All other parameters use defaults. The `cron_job_id` parameter allows `AutopilotService` to correlate the resulting goal with its originating cron job, enabling completion-callback routing for recurring rescheduling.

```python
goal = await self._autopilot.submit_task(
    description=job.description,
    priority=job.priority,
    cron_job_id=job.id,
)
```

The `priority` parameter is always passed from `CronJob.priority` (default `50` from `CronConfig.default_priority`). There is no separate `submit_task(description)` overload — `priority` is keyword-only with a default value.

### Data Flow

```
User: "/cron remind me tomorrow 9am to check deploy"
  │
  ▼ TUI RPC
CronService.add_job()
  │
  ├─► CronExtractionService.extract() → LLM
  │     └─► ExtractionResult { description, schedule_kind, schedule_value }
  │
  ├─► SchedulerService.add_task() → ScheduleSpec, next_run
  │
  ├─► CronJobStore.persist() → INSERT cron_jobs
  │
  ▼
Return CronJob to user

Periodic tick (every poll_interval):
  │
  ▼ CronService._tick()
  ├─► SchedulerService.get_due_tasks() → SELECT due jobs
  │
  ├─► For each due task:
  │     ├─► update_status(job.id, RUNNING)
  │     ├─► AutopilotService.submit_task(description, priority=job.priority, cron_job_id=job.id)
  │     └─► On completion: reschedule or update_status(job.id, COMPLETED)
  │
  ▼
Continue monitoring
```

## Specification

### 1. CronService

Orchestrating service that coordinates NL extraction, persistence, and job monitoring.

**Location**: `packages/soothe/src/soothe/cron/service.py`

**Responsibilities**:
- Accept natural language job submissions from TUI/CLI
- Call CronExtractionService to parse schedule semantics
- Persist jobs via CronJobStore
- Periodic tick to check due jobs and dispatch to AutopilotService
- Handle completion callbacks for recurring job rescheduling

**Public Interface**:

```python
class CronService:
    async def add_job(
        self,
        natural_language: str,
        user_id: str,
        priority: int = 50,
    ) -> CronJob:
        """Submit job via natural language, return persisted job."""

    async def list_jobs(
        self,
        user_id: str,
        status: str | None = None,
    ) -> list[CronJob]:
        """List jobs for user, optionally filtered by status."""

    async def cancel_job(self, job_id: str, user_id: str) -> bool:
        """Cancel a pending job. Returns True if cancelled."""

    async def show_job(self, job_id: str, user_id: str) -> CronJob | None:
        """Get job details. Returns None if not found or not owned."""

    async def _tick(self) -> None:
        """Periodic check: find due jobs, dispatch to AutopilotService."""

    async def _on_goal_completed(self, event: dict) -> None:
        """Handle goal_completed event: reschedule recurring or mark one-time completed."""

    async def _on_goal_failed(self, event: dict) -> None:
        """Handle goal_failed event: increment failures, apply backoff or circuit-break."""

    async def _on_goal_cancelled(self, event: dict) -> None:
        """Handle goal_cancelled event: mark cron job cancelled, no reschedule."""

    async def _reschedule_with_backoff(self, job: CronJob) -> None:
        """Reschedule a failed recurring job with exponential backoff.

        If consecutive_failures >= max_consecutive_failures, trip the circuit-breaker
        (set status to 'failed', emit cron_job_circuit_broken, do NOT reschedule).
        Otherwise, compute next_run = now + failure_backoff_base * (2 ** consecutive_failures),
        capped at max_backoff_delay. Keep status 'pending' for retry.
        """
```

**Integration Points**:
- `CronExtractionService` for NL parsing
- `SchedulerService` for schedule calculation (wrapped, not replaced)
- `AutopilotService` for goal submission
- `CronJobStore` for database persistence
- `InternalEventBus` for goal-completion callback subscription (RFC-450)

#### Goal-Completion Callback Routing

CronService does **not** poll AutopilotService for goal status. Instead, it subscribes to the daemon `InternalEventBus` (RFC-450) for goal lifecycle events and routes them to the originating cron job via the `cron_job_id` correlation key.

**Mechanism**: EventBus subscription (not CE callbacks, not direct method calls).

When `AutopilotService.submit_task(cron_job_id=...)` creates a goal, the `cron_job_id` is stored on the root `GoalNode` (RFC-626). As the goal progresses through the StrangeLoop lifecycle, AutopilotService emits goal-lifecycle events to `InternalEventBus`. CronService subscribes to these events, filters by `cron_job_id`, and performs rescheduling or status updates.

**Subscription setup**: CronService registers its handler during daemon startup:

```python
# CronService.start() — called on daemon startup
self._bus.subscribe("goal_completed", self._on_goal_completed)
self._bus.subscribe("goal_failed", self._on_goal_failed)
self._bus.subscribe("goal_cancelled", self._on_goal_cancelled)
```

**Handler implementations**:

```python
async def _on_goal_completed(self, event: GoalCompletedEvent) -> None:
    """Handle goal completion: reschedule recurring jobs or mark one-time jobs done."""
    cron_job_id = event.metadata.get("cron_job_id")
    if not cron_job_id:
        return  # Not a cron-dispatched goal
    await self._handle_goal_completion(cron_job_id, success=True, error=None)

async def _on_goal_failed(self, event: GoalFailedEvent) -> None:
    """Handle goal failure: increment retry counter, apply backoff or circuit-break."""
    cron_job_id = event.metadata.get("cron_job_id")
    if not cron_job_id:
        return
    await self._handle_goal_completion(cron_job_id, success=False, error=event.error)

async def _on_goal_cancelled(self, event: GoalCancelledEvent) -> None:
    """Handle goal cancellation: mark cron job as cancelled (no reschedule)."""
    cron_job_id = event.metadata.get("cron_job_id")
    if not cron_job_id:
        return
    await self._store.update_status(cron_job_id, "cancelled", last_run=datetime.now())
    await self._emit_event("cron_job_cancelled", cron_job_id)
```

**Core completion handler** (shared logic for completed/failed):

```python
async def _handle_goal_completion(self, cron_job_id: str, success: bool, error: str | None) -> None:
    job = await self._store.get(cron_job_id)
    if job is None:
        return  # Job was deleted

    now = datetime.now()
    run_count = job.run_count + 1

    if success:
        await self._store.update_status(cron_job_id, "completed", last_run=now, run_count=run_count)
        await self._emit_event("cron_job_completed", cron_job_id, run_count=run_count)
    else:
        await self._store.update_status(cron_job_id, "failed", last_run=now, run_count=run_count, last_error=error)
        await self._emit_event("cron_job_failed", cron_job_id, run_count=run_count, error=error)

    # End-condition check before reschedule
    if self._is_job_expired(job, now):
        await self._store.update_status(cron_job_id, "completed", last_run=now)
        await self._emit_event("cron_job_expired", cron_job_id, run_count=run_count)
        return

    # Reschedule recurring jobs (with circuit-breaker check on failure)
    if job.schedule_kind in ("every", "cron"):
        if success:
            await self._reschedule(job, now)
        else:
            await self._reschedule_with_backoff(job, now, run_count)
    # One-time jobs: no reschedule (status already set above)
```

**Receiving-side event types** (CronService subscribes to these from `InternalEventBus`):

| Event | Source | Payload Fields Used | CronService Action |
|-------|--------|---------------------|--------------------|
| `goal_completed` | AutopilotService | `metadata.cron_job_id`, `goal_id` | Reschedule recurring or mark one-time as completed |
| `goal_failed` | AutopilotService | `metadata.cron_job_id`, `goal_id`, `error` | Increment failure count, apply backoff or circuit-break |
| `goal_cancelled` | AutopilotService | `metadata.cron_job_id`, `goal_id` | Mark cron job as cancelled, no reschedule |

> **Design note**: The EventBus approach was chosen over direct method calls or CE callbacks because: (1) it decouples CronService from AutopilotService's internal lifecycle — CronService doesn't need to know when or how a goal completes, only that it did; (2) it survives daemon restarts — if the daemon restarts after goal submission but before completion, the event is queued and delivered on reconnection (eventual consistency); (3) it allows multiple consumers — future services (e.g., notification service) can subscribe to the same events without coupling to CronService.

> **Filtering**: CronService ignores all goal events where `metadata.cron_job_id` is absent or `None`. This means manually submitted goals (non-cron) do not trigger any cron-side processing. The filter is the first check in every handler.

### 2. CronExtractionService

LLM-based natural language to structured schedule extraction.

**Location**: `packages/soothe/src/soothe/cron/extraction.py`

**Supported Patterns**:

| Pattern | Example Input | schedule_kind | schedule_value |
|---------|---------------|---------------|----------------|
| Relative delay | "in 2 hours" | `delay` | `"2h"` |
| One-time at specific time | "tomorrow morning" | `once` | ISO datetime |
| One-time at specific time | "at 9am" | `at` | ISO datetime |
| Recurring interval | "every hour" | `every` | `"1h"` |
| Recurring day | "every Monday" | `every` | `"1w:Monday"` |
| Daily | "daily at 3pm" | `cron` | `"0 15 * * *"` |
| Cron-like | "every morning at 9" | `cron` | `"0 9 * * *"` |

> **`once` vs `at` semantics**: Both produce an ISO datetime `schedule_value` and both execute exactly once. The distinction is semantic:
> - **`once`**: Used when the user gives a *natural relative* expression (e.g., "tomorrow morning", "next Wednesday"). The LLM resolves the relative reference to an absolute ISO datetime using the current date. No recurrence is implied.
> - **`at`**: Used when the user gives an *explicit time* or *absolute datetime* (e.g., "at 9am", "at 2026-06-25T09:00"). The value is already (near-)absolute and needs minimal resolution.
>
> Both are one-shot: after execution, the job is marked `completed` and is never rescheduled. The `once`/`at` distinction exists to help downstream tooling and debugging understand the user's original intent (relative vs absolute phrasing).

**End Conditions** (optional):
- `"until 2026-06-30"` — stop after specific date
- `"for 2 weeks"` — stop after duration

**Extraction Schema**:

```python
@dataclass
class ExtractionResult:
    description: str          # Extracted task description (imperative form)
    schedule_kind: str        # "once" | "delay" | "at" | "every" | "cron"
    schedule_value: str       # Parsed schedule value
    end_condition: str | None # Optional: "until <date>" or "for <duration>"
    confidence: float         # Extraction confidence (0.0-1.0)
```

**LLM Prompt Strategy**:
- Use `fast` model role by default (configurable)
- Include current date/time in prompt for relative time resolution
- Request structured JSON output matching ExtractionResult schema
- Timeout configurable (default 30s)

**Extraction Prompt Template**:

```
Extract schedule information from the user's natural language request.

Input: "{natural_language}"

Extract:
1. task_description: What the user wants to do (clean, imperative form)
2. schedule_kind: one of "once", "delay", "at", "every", "cron"
3. schedule_value:
   - for "once": ISO datetime if specific time mentioned
   - for "delay": duration string like "2h", "30m"
   - for "at": ISO datetime
   - for "every": duration string like "1h", "1d"
   - for "cron": 5-field cron expression
4. end_condition: Optional limit (e.g., "until 2026-06-30", "for 2 weeks")

Current date: {current_date}
Current time: {current_time}

Return JSON matching the ExtractionResult schema.
```

### 3. SchedulerService Enhancement

Minimal changes to existing SchedulerService (RFC-204 §3.4) for database persistence.

**Changes**:

| Aspect | Current | Enhanced |
|--------|---------|----------|
| Persistence | JSON file (`_persist_path`) | `CronJobStore` adapter |
| User isolation | None | `user_id` field on ScheduledTask |
| Execution history | None | `last_run`, `run_count` fields |
| Persistence methods | `_load_persisted()`, `_save_persisted()` | Store CRUD methods |

**Enhanced ScheduledTask Dataclass**:

The existing `ScheduledTask` dataclass (RFC-204 §3.4) is extended with two new fields for cron-service support:

```python
@dataclass
class ScheduledTask:
    # --- Existing fields (RFC-204) ---
    id: str                           # UUID
    description: str                  # Task description
    schedule_spec: str                # Cron expression or duration string
    status: str                       # "pending" | "running" | "completed" | "failed" | "cancelled"
    next_run: datetime                # Next execution time
    created_at: datetime              # Creation timestamp

    # --- New fields (RFC-229) ---
    user_id: str = "default"          # Owner identity for multi-user isolation
    last_run: datetime | None = None  # Last execution timestamp (None if never run)
    run_count: int = 0                # Total execution count
```

**Backward compatibility**: The new fields have defaults, so existing `ScheduledTask` construction sites that omit them continue to work. When `CronJobStore` is wired as the persistence adapter, all three fields are populated from the `cron_jobs` table. When the legacy JSON-file adapter is used (non-cron scheduled tasks), the defaults apply and multi-user isolation is disabled (`user_id = "default"`).

**Preserved Logic** (no changes):
- `ScheduleSpec` parsing (cron expressions, durations)
- `next_after()` next_run calculation
- `get_due_tasks()` filtering by status and time
- Status transitions: pending → running → completed/failed/cancelled

### 4. CronJobStore

Database persistence adapter for cron jobs.

**Location**: `packages/soothe/src/soothe/cron/store.py`

**Implementation**:
- Uses existing metadata database connection pool (RFC-802)
- Maps ScheduledTask to/from `cron_jobs` table
- Async CRUD operations with proper error handling

**Public Interface**:

```python
class CronJobStore:
    async def create(self, job: CronJob) -> CronJob:
        """Insert new job, return with generated ID."""

    async def get(self, job_id: str) -> CronJob | None:
        """Get job by ID."""

    async def list_by_user(
        self,
        user_id: str,
        status: str | None = None,
    ) -> list[CronJob]:
        """List jobs for user, optionally filtered."""

    async def update_status(
        self,
        job_id: str,
        status: str,
        last_run: datetime | None = None,
    ) -> bool:
        """Update job status. Returns True if updated."""

    async def update_next_run(
        self,
        job_id: str,
        next_run: datetime,
        run_count: int,
    ) -> bool:
        """Update next_run for recurring jobs. Returns True if updated."""

    async def get_due_jobs(self, now: datetime) -> list[CronJob]:
        """Get pending jobs where next_run <= now."""
```

**Status Transition Helpers**: The flow diagrams reference `mark_running()` and `mark_completed()` for readability. These are not separate store methods — they are convenience calls that map to `update_status()`:

| Flow Diagram Reference | Actual Store Call |
|------------------------|-------------------|
| `mark_running(job_id)` | `update_status(job_id, "running")` |
| `mark_completed(job_id)` | `update_status(job_id, "completed", last_run=now)` |
| `mark_failed(job_id)` | `update_status(job_id, "failed", last_run=now)` |
| `mark_cancelled(job_id)` | `update_status(job_id, "cancelled")` |

`CronService` may define thin private wrappers (e.g., `self._mark_running(job_id)` → `self._store.update_status(job_id, JobStatus.RUNNING)`) to keep flow logic readable, but the store interface itself uses only `update_status`.

### 5. CronJob Model

**Location**: `packages/soothe/src/soothe/cron/models.py`

```python
@dataclass
class CronJob:
    id: str                      # UUID, generated on creation
    user_id: str                 # Owner identity
    description: str             # Task description (imperative form)
    natural_language: str | None # Original user input (null if submitted programmatically)
    schedule_kind: str           # "once" | "delay" | "at" | "every" | "cron"
    schedule_value: str          # Parsed schedule value
    end_condition: str | None    # Optional end condition
    priority: int                # Goal priority (1-100, default 50)
    status: str                  # "pending" | "running" | "completed" | "failed" | "cancelled"
    next_run: datetime           # Computed next execution time
    last_run: datetime | None    # Last execution time (null if never run)
    run_count: int               # Number of executions (0 initially)
    consecutive_failures: int = 0  # Consecutive failure count (resets on success; triggers circuit-breaker at threshold)
    created_at: datetime         # Creation timestamp
    updated_at: datetime         # Last modification timestamp
    last_error: str | None = None  # Last failure error message (for retry/circuit-breaker tracking)

    def __post_init__(self) -> None:
        """Validate field constraints after dataclass initialization."""
        if not (1 <= self.priority <= 100):
            raise ValueError(
                f"CronJob priority must be in range 1-100, got {self.priority}"
            )
        if self.run_count < 0:
            raise ValueError(f"CronJob run_count must be >= 0, got {self.run_count}")
        if self.consecutive_failures < 0:
            raise ValueError(f"CronJob consecutive_failures must be >= 0, got {self.consecutive_failures}")
```

**Priority validation enforcement points**:

| Enforcement Point | Mechanism | Rationale |
|-------------------|-----------|-----------|
| **`CronJob.__post_init__`** | `ValueError` if `priority` is outside 1-100 | Catches invalid values at construction time — any code path that creates a `CronJob` with an out-of-range priority fails immediately |
| **`CronExtractionService.extract()`** | LLM prompt instructs: `"priority": integer 1-100 (default 50)`. If extracted `priority` is `None`, use `CronConfig.default_priority`. If extracted value is outside 1-100, clamp to nearest valid value and log a WARNING. | The LLM may produce out-of-range values; clamping is safer than rejection because the user's intent is clear (high/low priority), just the magnitude is off |
| **`CronService.add_job()`** | If `priority` parameter is explicitly passed (from `cron_add_request`), validate 1-100 before passing to `CronJob` construction. If invalid, raise `ValueError` — do NOT silently clamp user-provided values (only LLM-extracted values are clamped). | User-provided values should be explicit; silent clamping of user input masks bugs. LLM-extracted values are best-effort and clamping is appropriate. |

```python
# CronService.add_job() — priority validation
async def add_job(self, natural_language: str, user_id: str, priority: int = 50) -> CronJob:
    if not (1 <= priority <= 100):
        raise ValueError(f"Priority must be 1-100, got {priority}")

    result = await self._extraction.extract(natural_language)
    # Extraction may produce a priority; clamp if out of range
    extracted_priority = result.priority or self._config.default_priority
    if not (1 <= extracted_priority <= 100):
        logger.warning(
            "Extracted priority %d out of range, clamping to %d",
            extracted_priority, max(1, min(100, extracted_priority))
        )
        extracted_priority = max(1, min(100, extracted_priority))

    # User-provided priority takes precedence over LLM-extracted priority
    final_priority = priority if priority != 50 else extracted_priority
    # ... rest of add_job
```

#### CronJob vs ScheduledTask: Direction of Truth

The RFC defines two dataclasses with overlapping fields: `CronJob` (§5 above) and `ScheduledTask` (§3, enhanced from RFC-204). This section clarifies their relationship to avoid implementation ambiguity.

**`CronJob` is the direction of truth for cron-service operations.** `CronService` operates exclusively on `CronJob` objects — `add_job()`, `list_jobs()`, `cancel_job()`, `show_job()`, and all internal methods (`_tick()`, `_handle_goal_completion()`, `_is_job_expired()`) read and write `CronJob` instances. The `CronJobStore` is the canonical persistence layer; `CronJob` is its native object model.

**`ScheduledTask` is the internal representation used by `SchedulerService`** (RFC-204) for schedule math — `ScheduleSpec` parsing, `next_after()` calculation, and `get_due_tasks()` filtering. It is a lower-level scheduling primitive that predates cron-service and is shared with non-cron scheduled tasks.

**Interop boundary**: The translation between the two models happens **at the `SchedulerService` call boundary inside `CronService._tick()`** — not inside the store, not inside `SchedulerService`:

```python
async def _tick(self) -> None:
    now = datetime.now()

    # Step 1: SchedulerService returns ScheduledTask objects (its native model)
    due_tasks: list[ScheduledTask] = await self._scheduler.get_due_tasks(now)

    for task in due_tasks:
        # Step 2: Translate ScheduledTask → CronJob at the boundary
        #   CronJobStore is the source of truth; the ScheduledTask from
        #   get_due_tasks() is used only for its next_run filtering.
        #   We re-load the full CronJob from the store to get all fields
        #   (end_condition, priority, user_id, run_count, etc.) that
        #   ScheduledTask does not carry.
        job: CronJob = await self._store.get(task.id)
        if job is None or job.status != "pending":
            continue  # Deleted or no longer pending since the query

        # Step 3: Operate on CronJob (direction of truth)
        if self._is_job_expired(job, now):
            await self._store.update_status(job.id, "completed", last_run=now)
            await self._emit_event("cron_job_expired", job.id)
            continue

        await self._store.update_status(job.id, "running")
        await self._emit_event("cron_job_dispatched", job.id)

        goal = await self._autopilot.submit_task(
            description=job.description,
            priority=job.priority,
            cron_job_id=job.id,
        )
        # Completion is handled asynchronously via EventBus callback
        # (see §1 Goal-Completion Callback Routing) — _tick() does NOT
        # block on goal completion.
```

**Mapping rules** (ScheduledTask ↔ CronJob):

| Direction | When | Mechanism |
|-----------|------|-----------|
| `CronJob` → `ScheduledTask` | When `CronService.add_job()` calls `SchedulerService.add_task()` | `SchedulerService.add_task()` accepts `description`, `schedule_spec`, `next_run`; CronService passes these from the `CronJob` fields. The resulting `ScheduledTask` is transient — used only to compute `next_run`. |
| `ScheduledTask` → `CronJob` | At the top of `_tick()` after `get_due_tasks()` | `CronService` uses `task.id` to load the full `CronJob` from `CronJobStore`. The `ScheduledTask`'s `next_run` is used only for due-filtering; all subsequent logic uses `CronJob` fields. |

**Why not unify?** `ScheduledTask` is not replaced by `CronJob` because: (1) `SchedulerService` is a shared RFC-204 component used by non-cron features (e.g., delayed tasks, simple timers); (2) `CronJob` carries cron-specific fields (`end_condition`, `natural_language`, `run_count`, `last_error`) that `ScheduledTask` should not carry; (3) the store layer (`CronJobStore`) is cron-specific, while `SchedulerService`'s persistence adapter is swappable (JSON file for legacy, `CronJobStore` for cron).

> **Implementation note**: `CronJobStore` is wired as the persistence adapter for `SchedulerService` when cron-service is enabled (see §3 SchedulerService Enhancement). This means `SchedulerService.get_due_tasks()` ultimately reads from the `cron_jobs` table via `CronJobStore`, but returns `ScheduledTask` objects (its API contract). The `ScheduledTask` objects are lightweight projections — they carry only scheduling fields, not cron-specific metadata. CronService always re-loads the full `CronJob` from the store after receiving a `ScheduledTask` from the scheduler.

### 6. Database Schema

**Table**: `cron_jobs` (in metadata database per RFC-802)

```sql
CREATE TABLE IF NOT EXISTS cron_jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    description TEXT NOT NULL,
    natural_language TEXT,          -- Original user input (for audit/re-extraction)
    schedule_kind TEXT NOT NULL,
    schedule_value TEXT NOT NULL,
    end_condition TEXT,
    priority INTEGER DEFAULT 50,
    status TEXT DEFAULT 'pending',
    next_run TEXT NOT NULL,         -- ISO datetime
    last_run TEXT,                  -- ISO datetime
    run_count INTEGER DEFAULT 0,
    consecutive_failures INTEGER DEFAULT 0,  -- Consecutive failure count (circuit-breaker tracking)
    last_error TEXT,               -- Last failure error message (for retry/circuit-breaker tracking)
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cron_jobs_user_status
    ON cron_jobs(user_id, status);

CREATE INDEX IF NOT EXISTS idx_cron_jobs_next_run
    ON cron_jobs(next_run) WHERE status = 'pending';
```

**Column: `natural_language`**: Stores the original user-submitted natural language text verbatim. This enables:
- Re-extraction if the LLM model or prompt is improved and a job needs re-parsing
- Auditing and debugging failed extractions
- Display in TUI/CLI `show_job` output for user context

The column is nullable (`TEXT` without `NOT NULL`) to allow pre-existing rows or programmatic submissions that bypass NL extraction.

### Schema Migration Strategy

The `cron_jobs` table is created via `CREATE TABLE IF NOT EXISTS` on daemon startup. This handles initial provisioning but does not handle column additions for existing deployments.

**Migration approach**: Soothe does not currently use Alembic-style versioned migrations (RFC-802 §5). Schema evolution for `cron_jobs` follows a lightweight additive strategy:

1. **Additive-only columns**: New columns are always added with a `DEFAULT` or `NULL` constraint so existing rows remain valid. The `natural_language` column follows this pattern (nullable).
2. **Startup `ALTER TABLE`**: On daemon startup, `CronJobStore._ensure_schema()` executes idempotent `ALTER TABLE ... ADD COLUMN` statements wrapped in `try/except` (SQLite does not support `IF NOT EXISTS` on `ADD COLUMN`). Columns that already exist raise `duplicate column name` which is caught and ignored.
3. **No destructive migrations**: Renamed or dropped columns are not supported. If a column becomes obsolete, it is left in place (unused).
4. **Version tracking (future)**: When RFC-802 adds Alembic-style migrations, `cron_jobs` will register a migration script. Until then, the additive `ALTER TABLE` approach is sufficient.

```python
# CronJobStore._ensure_schema() — called on daemon startup
SCHEMA_EXTENSIONS = [
    "ALTER TABLE cron_jobs ADD COLUMN natural_language TEXT",
    "ALTER TABLE cron_jobs ADD COLUMN last_error TEXT",
    "ALTER TABLE cron_jobs ADD COLUMN consecutive_failures INTEGER DEFAULT 0",
]

def _ensure_schema_sync(self):
    for stmt in SCHEMA_EXTENSIONS:
        try:
            self._conn.execute(stmt)
        except Exception as e:
            if "duplicate column" not in str(e).lower():
                raise
```

### 7. Configuration

**Location**: `config/config.template.yml` and `config/develop/nano.yml`

```yaml
agent:
  # ... existing sections ...

  # === CRON SERVICE ===
  cron:
    enabled: true              # Enable cron service (default: true)
    max_jobs: 100              # Maximum scheduled jobs per user
    poll_interval: 60          # Seconds between due-job monitoring ticks
    extraction_model: fast     # LLM role for NL extraction (fast|think)
    extraction_timeout: 30     # Timeout for LLM extraction calls
    extraction_max_retries: 3  # Max LLM retry attempts on failure
    extraction_retry_backoff: 2.0  # Exponential backoff base (seconds)
    min_confidence: 0.5        # Minimum extraction confidence (0.0-1.0)
    default_priority: 50       # Default job priority when not specified
    # --- Recurring failure handling ---
    max_consecutive_failures: 5   # Circuit-breaker threshold: consecutive failures before halting reschedule
    failure_backoff_base: 60      # Base backoff delay (seconds) for failing recurring jobs
    max_backoff_delay: 3600       # Maximum backoff delay cap (seconds, 1 hour default)
```

**Pydantic Model**:

```python
from typing import Literal

class CronConfig(BaseModel):
    enabled: bool = Field(default=True, description="Enable cron service")
    max_jobs: int = Field(default=100, ge=1, le=1000, description="Max jobs per user")
    poll_interval: int = Field(default=60, ge=10, le=3600, description="Monitoring tick interval")
    extraction_model: Literal["fast", "think"] = Field(default="fast", description="LLM role for NL extraction")
    extraction_timeout: int = Field(default=30, ge=5, le=120, description="Extraction timeout (seconds)")
    extraction_max_retries: int = Field(default=3, ge=0, le=10, description="Max LLM retry attempts on failure")
    extraction_retry_backoff: float = Field(default=2.0, ge=0.0, le=60.0, description="Exponential backoff base (seconds)")
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Minimum extraction confidence threshold")
    default_priority: int = Field(default=50, ge=1, le=100, description="Default job priority")
    max_consecutive_failures: int = Field(default=5, ge=1, le=50, description="Circuit-breaker threshold: consecutive failures before halting reschedule")
    failure_backoff_base: float = Field(default=60.0, ge=1.0, le=3600.0, description="Base backoff delay (seconds) for failing recurring jobs")
    max_backoff_delay: float = Field(default=3600.0, ge=60.0, le=86400.0, description="Maximum backoff delay cap (seconds)")
```

**Field validation notes**:
- `extraction_model`: Constrained to `Literal["fast", "think"]` — invalid values raise `ValidationError` at config load time rather than failing at first extraction call.
- `min_confidence`: Replaces the hardcoded `0.5` threshold in the error-handling table. Extraction results with `confidence < min_confidence` are rejected and an error is returned to the user suggesting rephrasing.
- `extraction_max_retries` / `extraction_retry_backoff`: Configurable retry parameters for LLM extraction calls. Retries use exponential backoff: `delay = backoff * (2 ** attempt)` seconds. Set `extraction_max_retries: 0` to disable retries.

### 8. TUI Commands (Job Submission Only)

**Location**: `packages/soothe-cli/src/soothe_cli/tui/command_registry.py`

The TUI provides a single `/cron` command for natural language job submission during active sessions.

| Command | Description | Bypass Tier |
|---------|-------------|-------------|
| `/cron <text>` | Add scheduled job | `QUEUED` |

**Hidden Keywords**: `schedule`, `timer`, `reminder` (for discoverability)

### 9. CLI Subcommands (Job Management)

**Location**: `packages/soothe-cli/src/soothe_cli/cli/commands/cron_cmd.py`

Job management (list, show, cancel) is available via CLI subcommands using HTTP REST:

| Command | Description |
|---------|-------------|
| `soothe cron list [--status <s>]` | List scheduled jobs |
| `soothe cron show <job_id>` | Show job details |
| `soothe cron cancel <job_id>` | Cancel a scheduled job |

These commands communicate with the daemon via HTTP REST (`/api/v1/cron/*` endpoints).

### 10. Daemon RPC Handlers (TUI Submission)

**Location**: IPC handlers in daemon (RFC-450)

Follows RFC-450 JSON message format with required `type` field.

**Client → Server Message**:

| Type | Fields | Description |
|------|--------|-------------|
| `cron_add_request` | `natural_language` (req, string), `user_id` (opt, string), `priority` (opt, int), `request_id` (opt, string) | Submit natural language cron job. Daemon routes to `CronService.add_job()`. See User Identity Precedence below. |

**User Identity Precedence** (`cron_add_request.user_id` field):

The optional `user_id` field in the request body is **secondary** to the session-derived identity. The resolution order is:

1. **Session-derived `user_id`** (authoritative): For TUI sessions, `session.user_id` is set during authentication. For HTTP REST, the `X-User-Id` header value. This is the identity used for ownership validation.
2. **Request-body `user_id`** (override, restricted): If present AND the session-derived identity has admin privileges (future capability), the request-body value may override. In the current architecture (no admin roles), the request-body `user_id` is **ignored** when it differs from the session-derived identity, and a WARNING is logged: `"cron_add_request user_id mismatch: session=%s request=%s, using session identity"`. If the request-body `user_id` matches the session identity, it is accepted (redundant but harmless).
3. **Fallback**: If no session identity exists (e.g., unauthenticated local TUI), the request-body `user_id` is used. If neither is present, defaults to `"default"`.

This ensures a client cannot escalate privileges by sending an arbitrary `user_id` in the request body — the session identity always wins for authenticated sessions.

**Server → Client Messages**:

| Type | Fields | Description |
|------|--------|-------------|
| `cron_add_response` | `job_id` (req, string), `description` (req, string), `schedule_kind` (req, string), `next_run` (req, string, ISO datetime), `request_id` (opt, string) | Job created and persisted. |
| `cron_add_error` | `code` (req, string), `message` (req, string), `details` (opt, object), `request_id` (opt, string) | Extraction failed, confidence too low, or persistence error. |

**Request Example**:

```json
{
  "type": "cron_add_request",
  "natural_language": "remind me tomorrow at 9am to check the deploy",
  "user_id": "alice",
  "priority": 50,
  "request_id": "cron-001"
}
```

**Success Response Example**:

```json
{
  "type": "cron_add_response",
  "job_id": "a3f1b2c4",
  "description": "Check the deploy",
  "schedule_kind": "at",
  "next_run": "2026-06-25T09:00:00+08:00",
  "request_id": "cron-001"
}
```

**Error Response Example** (low confidence):

```json
{
  "type": "cron_add_error",
  "code": "EXTRACTION_LOW_CONFIDENCE",
  "message": "Could not confidently parse schedule from input. Please rephrase.",
  "details": {
    "confidence": 0.3,
    "min_confidence": 0.5,
    "input": "remind me to check the deploy"
  },
  "request_id": "cron-001"
}
```

**Error Codes**:

| Code | Trigger | User Action |
|------|---------|-------------|
| `EXTRACTION_LOW_CONFIDENCE` | LLM confidence < `min_confidence` | Rephrase with clearer timing |
| `EXTRACTION_FAILED` | LLM returned unparseable output | Try structured syntax |
| `EXTRACTION_TIMEOUT` | LLM timed out after all retries | Retry later |
| `MAX_JOBS_EXCEEDED` | User has `max_jobs` pending jobs | Cancel existing jobs first |
| `CRON_DISABLED` | `cron.enabled` is `false` | Enable cron in config |

**Handler**: `_cmd_cron_add` in daemon IPC handler registry. Calls `CronService.add_job(natural_language, user_id, priority)`.

### 11. HTTP REST Endpoints (CLI Management)

**Location**: `packages/soothe-daemon/src/soothe_daemon/channels/http_rest.py`

All endpoints follow JSON request/response convention. `user_id` is derived per channel (see User Identity Derivation below).

#### GET `/api/v1/cron/jobs` — List Scheduled Jobs

**Query Parameters**:

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | string | no | Filter by status: `pending`, `running`, `completed`, `failed`, `cancelled` |

**Response** `200 OK`:

```json
{
  "jobs": [
    {
      "id": "a3f1b2c4",
      "description": "Check the deploy",
      "schedule_kind": "at",
      "schedule_value": "2026-06-25T09:00:00+08:00",
      "end_condition": null,
      "priority": 50,
      "status": "pending",
      "next_run": "2026-06-25T09:00:00+08:00",
      "last_run": null,
      "run_count": 0,
      "created_at": "2026-06-24T15:30:00+08:00"
    }
  ],
  "count": 1
}
```

**Error** `403 Forbidden`:

```json
{
  "error": "CRON_DISABLED",
  "message": "Cron service is not enabled"
}
```

#### GET `/api/v1/cron/jobs/{job_id}` — Show Job Details

**Path Parameters**: `job_id` (string, required) — 8-char hex job ID

**Response** `200 OK`:

```json
{
  "id": "a3f1b2c4",
  "user_id": "http_api",
  "description": "Check the deploy",
  "natural_language": "remind me tomorrow at 9am to check the deploy",
  "schedule_kind": "at",
  "schedule_value": "2026-06-25T09:00:00+08:00",
  "end_condition": null,
  "priority": 50,
  "status": "pending",
  "next_run": "2026-06-25T09:00:00+08:00",
  "last_run": null,
  "run_count": 0,
  "created_at": "2026-06-24T15:30:00+08:00",
  "updated_at": "2026-06-24T15:30:00+08:00"
}
```

**Error** `404 Not Found`:

```json
{
  "error": "JOB_NOT_FOUND",
  "message": "No cron job with id 'xyz123' found for this user"
}
```

#### DELETE `/api/v1/cron/jobs/{job_id}` — Cancel Scheduled Job

**Path Parameters**: `job_id` (string, required)

**Response** `200 OK`:

```json
{
  "id": "a3f1b2c4",
  "status": "cancelled",
  "cancelled_at": "2026-06-24T16:00:00+08:00"
}
```

**Error** `404 Not Found`: Same as GET show (job not found or not owned by caller)

**Error** `409 Conflict`:

```json
{
  "error": "JOB_ALREADY_COMPLETED",
  "message": "Cannot cancel job that is already completed"
}
```

#### User Identity Derivation

The `user_id` used for ownership validation is derived differently per channel:

| Channel | `user_id` Source | Notes |
|---------|------------------|-------|
| **TUI** (WebSocket RPC) | `session.user_id` from daemon session | Set during TUI session authentication; defaults to `"tui_user"` for unauthenticated local sessions. The optional `user_id` field in `cron_add_request` is ignored if it differs from session identity (see User Identity Precedence above). |
| **CLI** (HTTP REST) | `"http_api"` (constant) | CLI commands do not carry per-user identity in the current architecture. All CLI-managed jobs are scoped to the `"http_api"` pseudo-user. Multi-user CLI identity is deferred to a future auth RFC. |
| **HTTP REST** (programmatic) | `X-User-Id` header, fallback `"http_api"` | Programmatic clients may pass `X-User-Id` header for user-scoped operations. If absent, defaults to `"http_api"`. |

> **Cross-channel note**: A job created via TUI (user `"alice"`) cannot be cancelled via CLI (user `"http_api"`) — the ownership check will reject it. This is intentional: TUI-created jobs must be managed through the TUI or by a REST client that provides the matching `X-User-Id` header.

## Execution Flow

### Job Submission

1. User sends `/cron remind me tomorrow at 9am to check deploy`
2. TUI sends `cron_add_request` RPC to daemon
3. `CronService.add_job()` receives request
4. `CronExtractionService.extract()` calls LLM with prompt
5. LLM returns `ExtractionResult`:
   - `description: "Check the deploy"`
   - `schedule_kind: "at"`
   - `schedule_value: "2026-06-25T09:00:00"`
   - `confidence: 0.95`
6. Service validates confidence >= `min_confidence` threshold
7. `SchedulerService.add_task()` computes `next_run`
8. `CronJobStore.create()` persists to database
9. Response sent to TUI with job ID and next_run

### Monitoring Tick

1. Daemon periodic task `_periodic_cron_tick` fires (every `poll_interval`)
2. `CronService._tick()` calls `SchedulerService.get_due_tasks(now)`
3. For each due job:
   - **End-condition check** (before dispatch): If `job.end_condition` is set and evaluates to expired (see End-Condition Evaluation below), call `update_status(job.id, "completed", last_run=now)` and skip dispatch. Log at INFO: `"Cron job expired: id=%s end_condition=%s"`.
   - `update_status(job.id, "running")` marks the job as running (the store has no separate `mark_running()` method — all status transitions go through `update_status`)
   - `AutopilotService.submit_task(description, priority=job.priority, cron_job_id=job.id)` creates goal
   - Goal executes via StrangeLoop (RFC-222)
4. On goal completion event:
   - **End-condition check** (before reschedule): If `job.end_condition` is set and expired, call `update_status(job.id, "completed", last_run=now)` and do NOT reschedule. Log at INFO.
   - If recurring (`every` or `cron`) and not expired:
     - **On success**: Reset `consecutive_failures` to 0. Compute next `next_run` via `SchedulerService.next_after()`. `update_next_run()` with incremented `run_count`. `update_status(job.id, "pending")` to requeue for next tick.
     - **On failure**: Call `_reschedule_with_backoff(job)`. If `consecutive_failures < max_consecutive_failures`: compute `next_run = now + failure_backoff_base * (2 ** consecutive_failures)` (capped at `max_backoff_delay`), keep status `pending` for retry. If `consecutive_failures >= max_consecutive_failures`: set status to `failed` (terminal), emit `cron_job_circuit_broken`, do NOT reschedule.
   - If one-time (`once`, `delay`, `at`):
     - **On success**: `update_status(job.id, "completed", last_run=now)`
     - **On failure**: `update_status(job.id, "failed", last_run=now, last_error=error)` — no reschedule for one-time jobs

#### End-Condition Evaluation

`CronService._is_job_expired(job, now)` evaluates `end_condition` before any dispatch or rescheduling:

| Format | Example | Evaluation |
|--------|---------|------------|
| `until <ISO date>` | `"until 2026-06-30"` | `now >= parsed_date` → expired |
| `for <N> <unit>` | `"for 2 weeks"` | `now >= job.created_at + N units` → expired |
| `None` / empty | — | Never expires (always `False`) |

- If `end_condition` is unparseable, log a WARNING and return `False` (treat as no end condition — safer to continue than to silently drop a recurring job).
- `until` dates without timezone are assumed UTC.
- `for` durations support `day(s)` and `week(s)` units.

> **Note on store interface**: `CronJobStore` does not expose separate `mark_running()` or `mark_completed()` methods. All status transitions are performed via `update_status(job_id, status, last_run=None)`. The method names `mark_running` and `mark_completed` in earlier flow diagrams refer to `update_status(job_id, "running")` and `update_status(job_id, "completed", last_run=now)` respectively.

### Job Query/Cancel (CLI via HTTP REST)

1. User sends `soothe cron list` or `soothe cron cancel <id>`
2. CLI sends HTTP GET/DELETE to daemon REST endpoint
3. Service validates `user_id` ownership (derived per channel — see User Identity Derivation in §11)
4. Operation executes via `CronJobStore`
5. Response returned as JSON to CLI

## Error Handling

### Extraction Failures

| Scenario | Handling |
|----------|----------|
| Low confidence (< `min_confidence`) | Return error to user, suggest rephrasing |
| Unparseable schedule | Return error with example syntax |
| LLM timeout | Retry with exponential backoff, max `extraction_max_retries` attempts (backoff base: `extraction_retry_backoff` seconds) |
| LLM unavailable | Return error, suggest structured syntax |

### Execution Failures

| Scenario | Handling |
|----------|----------|
| Goal execution fails | Mark job `failed`, increment `run_count`, store `last_error`, log error. Increment `consecutive_failures` counter. |
| Recurring job fails (< `max_consecutive_failures`) | Reschedule for next run with exponential backoff: `next_run = now + base_delay * (2 ** consecutive_failures)`, capped at `max_backoff_delay`. Do NOT block future executions — the job remains `pending` and will be retried at the backoff-adjusted time. |
| Recurring job fails (>= `max_consecutive_failures`) | **Circuit-breaker trips**: job status set to `failed` (terminal), `cron_job_circuit_broken` event emitted. The job is NOT rescheduled. User must explicitly cancel and re-create the job, or an admin resets `consecutive_failures` via a future maintenance command. |
| Recurring job succeeds after failures | Reset `consecutive_failures` counter to 0. Reschedule normally (no backoff). |
| AutopilotService unavailable | Skip tick, retry next interval |

### Persistence Failures

| Scenario | Handling |
|----------|----------|
| DB write fails | Log error, retry write, keep in-memory state as backup |
| DB read fails | Use in-memory cache if available, log warning |

### Job-Completion Notifications

Users need to know when a cron job has executed (succeeded, failed, or expired). The notification mechanism uses the existing daemon event bus (RFC-450) rather than introducing a new channel.

**Event Types**: CronService interacts with the daemon `InternalEventBus` (RFC-450) in two directions — it **receives** goal-lifecycle events from AutopilotService (for completion callback routing) and **emits** cron-job events to the bus (for notification delivery).

**Receiving-side events** (CronService subscribes to these — see §1 Goal-Completion Callback Routing):

| Event | Source | Payload Fields Used | CronService Action |
|-------|--------|---------------------|--------------------|
| `goal_completed` | AutopilotService | `metadata.cron_job_id`, `goal_id` | Reschedule recurring or mark one-time as completed |
| `goal_failed` | AutopilotService | `metadata.cron_job_id`, `goal_id`, `error` | Increment failure count, apply backoff or circuit-break |
| `goal_cancelled` | AutopilotService | `metadata.cron_job_id`, `goal_id` | Mark cron job as cancelled, no reschedule |

**Emitting-side events** (CronService emits these on every job state transition):

| Event | Trigger | Payload Fields |
|-------|---------|----------------|
| `cron_job_dispatched` | Job transitioned to `running` (dispatched to AutopilotService) | `job_id`, `user_id`, `description`, `goal_id` |
| `cron_job_completed` | One-time job finished successfully or recurring job completed a run | `job_id`, `user_id`, `description`, `status`, `run_count`, `last_run` |
| `cron_job_failed` | Goal execution failed | `job_id`, `user_id`, `description`, `error`, `run_count` |
| `cron_job_expired` | End condition reached; job will not reschedule | `job_id`, `user_id`, `description`, `end_condition`, `run_count` |
| `cron_job_cancelled` | User cancelled the job | `job_id`, `user_id`, `description` |
| `cron_job_circuit_broken` | Recurring job exceeded `max_consecutive_failures` — circuit-breaker tripped, job will not reschedule | `job_id`, `user_id`, `description`, `consecutive_failures`, `last_error` |

**Notification Delivery**:

| Channel | Mechanism |
|---------|-----------|
| **TUI** | If the originating user has an active TUI WebSocket session, the daemon pushes a `cron_job_event` message over the session. The TUI displays a transient notification toast. |
| **CLI** | No push mechanism. Users poll via `soothe cron show <job_id>` or `soothe cron list --status completed`. The CLI output includes `last_run`, `run_count`, and `status` fields. |
| **HTTP REST** | No push mechanism. Clients poll `GET /api/v1/cron/jobs/{job_id}`. Future RFCs may add SSE or webhook callbacks. |

**TUI Notification Message Format**:

```json
{
  "type": "cron_job_event",
  "event": "cron_job_completed",
  "job_id": "a3f1b2c4",
  "description": "Check the deploy",
  "status": "completed",
  "run_count": 1,
  "last_run": "2026-06-25T09:00:15+08:00"
}
```

> **Note**: TUI notifications are best-effort. If no active session exists for `user_id`, the event is logged but not delivered. The persisted job state (queryable via CLI/REST) is the source of truth.

## Security Considerations

### User Isolation

- All jobs scoped to `user_id`
- `cancel_job`, `show_job` validate ownership before operation
- `list_jobs` filters by user, never exposes cross-user data

### Input Validation

- Natural language input length bounded
- Extraction confidence threshold prevents ambiguous interpretations
- Schedule values validated against reasonable ranges

### Rate Limiting

- `max_jobs` per user prevents unbounded job creation
- Extraction timeout prevents LLM hanging

## Testing Requirements

### Unit Tests

| Component | Test Coverage |
|-----------|---------------|
| `CronExtractionService` | Mock LLM responses, test extraction parsing |
| `SchedulerService` | Cron parsing, next_run calculation, edge cases |
| `CronJobStore` | Mock DB, test CRUD operations |
| `CronService` | Mock dependencies, test orchestration flows |

### Integration Tests

| Flow | Test Coverage |
|------|---------------|
| End-to-end submission | TUI → daemon → DB → verify persisted |
| Execution flow | Due job → AutopilotService → verify goal created |
| Rescheduling | Recurring job completes → verify next_run updated |
| Daemon restart | Jobs persist across restart, due jobs picked up |

## Implementation Phases

| Phase | Scope |
|-------|-------|
| **Phase 1**: Core Infrastructure | CronConfig, models, CronJobStore, SchedulerService enhancement |
| **Phase 2**: NL Extraction | CronExtractionService, extraction confidence validation |
| **Phase 3**: CronService Orchestrator | CronService methods, periodic tick, AutopilotService integration |
| **Phase 4**: TUI Integration | Command registry, daemon RPC handlers |
| **Phase 5**: Testing & Polish | Unit tests, integration tests, config sync |

## Implementation Checklist

Track per-component completion. All items must be checked before the RFC moves from Proposed to Accepted.

### CronConfig & Models

- [ ] `CronConfig` Pydantic model with `Literal["fast", "think"]` validation on `extraction_model`
- [ ] `CronConfig` includes `min_confidence`, `extraction_max_retries`, `extraction_retry_backoff` fields
- [ ] `CronConfig` includes `max_consecutive_failures`, `failure_backoff_base`, `max_backoff_delay` fields
- [ ] `CronJob` dataclass includes `natural_language` field
- [ ] `CronJob` dataclass includes `consecutive_failures` and `last_error` fields
- [ ] `CronJob.__post_init__` validates priority range (1-100), non-negative run_count and consecutive_failures
- [ ] `ExtractionResult` dataclass includes `confidence` field
- [ ] Config template (`config/config.template.yml`) updated with all new cron fields
- [ ] Develop config (`config/develop/nano.yml`) synced with template

### CronExtractionService

- [ ] LLM prompt template implemented with current date/time injection
- [ ] `extract()` returns `ExtractionResult` with confidence score
- [ ] Low-confidence rejection (< `min_confidence`) returns error with rephrasing suggestion
- [ ] LLM timeout retry with exponential backoff (`extraction_max_retries` attempts, `extraction_retry_backoff` base)
- [ ] LLM unavailable fallback returns structured error
- [ ] Unit tests with mocked LLM responses

### CronJobStore

- [ ] `create()`, `get()`, `list_by_user()`, `update_status()`, `update_next_run()`, `get_due_jobs()` implemented
- [ ] `cron_jobs` table DDL includes `natural_language` column
- [ ] `cron_jobs` table DDL includes `consecutive_failures` and `last_error` columns
- [ ] Migration strategy documented and implemented (ALTER TABLE for schema evolution, including `consecutive_failures` and `last_error` columns)
- [ ] Indexes on `(user_id, status)` and `next_run WHERE status='pending'` created
- [ ] Unit tests with mocked DB

### SchedulerService Enhancement

- [ ] `ScheduledTask` dataclass extended with `user_id`, `last_run`, `run_count` fields
- [ ] Backward compatibility: existing construction sites with default values still work
- [ ] `CronJobStore` wired as persistence adapter (replaces JSON file for cron tasks)
- [ ] Schedule math (`next_after()`, `get_due_tasks()`) preserved unchanged

### CronService Orchestrator

- [ ] `add_job()` orchestrates extraction → scheduling → persistence
- [ ] `list_jobs()`, `cancel_job()`, `show_job()` implement ownership validation
- [ ] `_tick()` calls `get_due_tasks()` and dispatches to `AutopilotService.submit_task()`
- [ ] `_on_goal_completed()`, `_on_goal_failed()`, `_on_goal_cancelled()` event handlers subscribe to InternalEventBus and route by `cron_job_id` metadata
- [ ] `_reschedule_with_backoff()` implements exponential backoff and circuit-breaker (>= `max_consecutive_failures`)
- [ ] `_to_cron_job()` / `_to_scheduled_task()` conversion methods defined at CronService↔SchedulerService interop boundary
- [ ] `_is_job_expired()` evaluates `end_condition` before dispatch and before reschedule
- [ ] Recurring rescheduling: `update_next_run()` + `update_status("pending")`
- [ ] One-time completion: `update_status("completed", last_run=now)`
- [ ] Goal-completion events emitted to `InternalEventBus` (`cron_job_dispatched`, `cron_job_completed`, `cron_job_failed`, `cron_job_expired`, `cron_job_cancelled`, `cron_job_circuit_broken`)
- [ ] Unit tests with mocked dependencies

### TUI Integration

- [ ] `/cron <text>` command registered in TUI command registry
- [ ] `cron_add_request` RPC handler implemented in daemon (`_cmd_cron_add`)
- [ ] `cron_add_response` sent back to TUI with job details
- [ ] `cron_job_event` push notifications to active TUI sessions
- [ ] Hidden keywords (`schedule`, `timer`, `reminder`) registered for discoverability

### CLI Subcommands

- [ ] `soothe cron list [--status <s>]` implemented (GET `/api/v1/cron/jobs`)
- [ ] `soothe cron show <job_id>` implemented (GET `/api/v1/cron/jobs/{job_id}`)
- [ ] `soothe cron cancel <job_id>` implemented (DELETE `/api/v1/cron/jobs/{job_id}`)
- [ ] HTTP REST endpoints return JSON with documented status codes (200, 403, 404, 409)
- [ ] `user_id` derivation: TUI session, CLI `"http_api"`, HTTP `X-User-Id` header
- [ ] `user_id` precedence: session-derived identity authoritative, request-body `user_id` ignored on mismatch (WARNING logged)

### Integration Test Checklist

- [ ] End-to-end submission: TUI → daemon → DB → verify persisted
- [ ] Execution flow: due job → AutopilotService → verify goal created
- [ ] Rescheduling: recurring job completes → verify `next_run` updated
- [ ] Failure backoff: recurring job fails → verify `consecutive_failures` incremented and `next_run` delayed by backoff
- [ ] Circuit-breaker: recurring job fails `max_consecutive_failures` times → verify status `failed` (terminal), `cron_job_circuit_broken` emitted, no reschedule
- [ ] Failure recovery: recurring job succeeds after failures → verify `consecutive_failures` reset to 0
- [ ] Goal-completion callback: AutopilotService emits `goal_completed` → verify CronService reschedules (recurring) or marks completed (one-time)
- [ ] Priority validation: `CronJob(priority=0)` and `CronJob(priority=101)` raise `ValueError`
- [ ] End-condition expiry: job with `end_condition` → verify `completed` and no reschedule
- [ ] Daemon restart: jobs persist across restart, due jobs picked up
- [ ] Ownership isolation: cross-user access rejected

## References

- RFC-204: Autopilot Mode (scheduler service foundation)
- RFC-222: Autopilot and Goal Engine Architecture (AutopilotService integration, `submit_task` contract)
- RFC-450: Daemon Communication Protocol (IPC message format, event bus)
- RFC-624: Context Engine (unified context management for goals)
- RFC-625: ContextEngine as goal state source of truth (AutopilotMonitor unification)
- RFC-626: Entity Model and State Management Consolidation (GoalNode entity model, `cron_job_id` parameter)
- RFC-802: Persistence Architecture (metadata database, migration framework)

## Changelog

### 2026-06-24
- Initial RFC proposal
- Defined CronService architecture, CronExtractionService, CronJobStore
- Defined database schema, configuration, TUI/CLI interface
- Defined execution flow and error handling

### 2026-07-03
- Added `AutopilotService.submit_task()` formal contract with `cron_job_id` parameter
- Added `cron_add_request` / `cron_add_response` RPC message schemas
- Added HTTP REST request/response JSON schemas with status codes (200, 403, 404, 409)
- Added user identity derivation per channel (TUI, CLI, HTTP REST)
- Added `natural_language` column to `cron_jobs` schema and `CronJob` model
- Constrained `extraction_model` with `Literal["fast", "think"]` validation
- Added `min_confidence`, `extraction_max_retries`, `extraction_retry_backoff` to `CronConfig`
- Added end-condition evaluation logic (`_is_job_expired`) to Monitoring Tick flow
- Added job-completion notification mechanism (event bus + TUI push)
- Reconciled `mark_running`/`mark_completed` as `update_status` convenience wrappers
- Added enhanced `ScheduledTask` dataclass with `user_id`, `last_run`, `run_count`
- Clarified `once` vs `at` schedule_kind semantics
- Added implementation checklist (per-component)
- Added RFC-624 and RFC-626 to References
- Added database migration strategy for `cron_jobs` table

### 2026-07-03 (revision 2)
- **G10**: Added goal-completion callback routing mechanism — CronService subscribes to `goal_completed`/`goal_failed`/`goal_cancelled` EventBus events from AutopilotService via `cron_job_id` metadata correlation; added receiving-side event types to events table
- **G9**: Clarified CronJob vs ScheduledTask dual-model — CronJob is the domain model (direction of truth), ScheduledTask is the scheduler-persistence adapter; defined interop boundary in `_tick()` via explicit `_to_cron_job()` / `_to_scheduled_task()` conversions
- **G5**: Added `__post_init__` validation to CronJob dataclass enforcing priority range 1-100 and non-negative run_count/consecutive_failures
- **G8**: Added max-retry/backoff/circuit-breaker for failing recurring jobs — `max_consecutive_failures` threshold, exponential backoff with `failure_backoff_base`/`max_backoff_delay`, `cron_job_circuit_broken` event, `consecutive_failures`/`last_error` fields
- **G1**: Clarified user_id precedence in `cron_add_request` — session-derived identity is authoritative, request-body `user_id` is ignored on mismatch (anti-privilege-escalation)
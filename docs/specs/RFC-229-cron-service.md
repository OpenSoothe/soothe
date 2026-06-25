# RFC-229: Cron Service for Autopilot

**RFC**: 229
**Title**: Cron Service for Autopilot — Natural Language Scheduled Jobs
**Status**: Proposed
**Kind**: Architecture Design
**Created**: 2026-06-24
**Updated**: 2026-06-24
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
packages/soothe/src/soothe/foundation/cron/
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
  │     ├─► mark_running()
  │     ├─► AutopilotService.submit_task(description)
  │     └─► On completion: reschedule or mark_completed
  │
  ▼
Continue monitoring
```

## Specification

### 1. CronService

Orchestrating service that coordinates NL extraction, persistence, and job monitoring.

**Location**: `packages/soothe/src/soothe/foundation/cron/service.py`

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
```

**Integration Points**:
- `CronExtractionService` for NL parsing
- `SchedulerService` for schedule calculation (wrapped, not replaced)
- `AutopilotService` for goal submission
- `CronJobStore` for database persistence

### 2. CronExtractionService

LLM-based natural language to structured schedule extraction.

**Location**: `packages/soothe/src/soothe/foundation/cron/extraction.py`

**Supported Patterns**:

| Pattern | Example Input | schedule_kind | schedule_value |
|---------|---------------|---------------|----------------|
| Relative delay | "in 2 hours" | `delay` | `"2h"` |
| Relative date | "tomorrow morning" | `at` | ISO datetime |
| Specific time | "at 9am" | `at` | ISO datetime |
| Recurring interval | "every hour" | `every` | `"1h"` |
| Recurring day | "every Monday" | `every` | `"1w:Monday"` |
| Daily | "daily at 3pm" | `cron` | `"0 15 * * *"` |
| Cron-like | "every morning at 9" | `cron` | `"0 9 * * *"` |

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

**Preserved Logic** (no changes):
- `ScheduleSpec` parsing (cron expressions, durations)
- `next_after()` next_run calculation
- `get_due_tasks()` filtering by status and time
- Status transitions: pending → running → completed/failed/cancelled

### 4. CronJobStore

Database persistence adapter for cron jobs.

**Location**: `packages/soothe/src/soothe/foundation/cron/store.py`

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

### 5. CronJob Model

**Location**: `packages/soothe/src/soothe/foundation/cron/models.py`

```python
@dataclass
class CronJob:
    id: str                      # UUID, generated on creation
    user_id: str                 # Owner identity
    description: str             # Task description (imperative form)
    schedule_kind: str           # "once" | "delay" | "at" | "every" | "cron"
    schedule_value: str          # Parsed schedule value
    end_condition: str | None    # Optional end condition
    priority: int                # Goal priority (1-100, default 50)
    status: str                  # "pending" | "running" | "completed" | "failed" | "cancelled"
    next_run: datetime           # Computed next execution time
    last_run: datetime | None    # Last execution time (null if never run)
    run_count: int               # Number of executions (0 initially)
    created_at: datetime         # Creation timestamp
    updated_at: datetime         # Last modification timestamp
```

### 6. Database Schema

**Table**: `cron_jobs` (in metadata database per RFC-802)

```sql
CREATE TABLE IF NOT EXISTS cron_jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    description TEXT NOT NULL,
    schedule_kind TEXT NOT NULL,
    schedule_value TEXT NOT NULL,
    end_condition TEXT,
    priority INTEGER DEFAULT 50,
    status TEXT DEFAULT 'pending',
    next_run TEXT NOT NULL,       -- ISO datetime
    last_run TEXT,                -- ISO datetime
    run_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cron_jobs_user_status
    ON cron_jobs(user_id, status);

CREATE INDEX IF NOT EXISTS idx_cron_jobs_next_run
    ON cron_jobs(next_run) WHERE status = 'pending';
```

### 7. Configuration

**Location**: `config/config.template.yml` and `config/develop/config.yml`

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
    default_priority: 50       # Default job priority when not specified
```

**Pydantic Model**:

```python
class CronConfig(BaseModel):
    enabled: bool = Field(default=True, description="Enable cron service")
    max_jobs: int = Field(default=100, ge=1, le=1000, description="Max jobs per user")
    poll_interval: int = Field(default=60, ge=10, le=3600, description="Monitoring tick interval")
    extraction_model: str = Field(default="fast", description="LLM role for NL extraction")
    extraction_timeout: int = Field(default=30, ge=5, le=120, description="Extraction timeout")
    default_priority: int = Field(default=50, ge=1, le=100, description="Default job priority")
```

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

| RPC Type | Handler | Method |
|----------|---------|--------|
| `cron_add_request` | `_cmd_cron_add` | `CronService.add_job()` |

### 11. HTTP REST Endpoints (CLI Management)

**Location**: `packages/soothe-daemon/src/soothe_daemon/channels/http_rest.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/cron/jobs` | GET | List scheduled jobs (optional `?status=` filter) |
| `/api/v1/cron/jobs/{job_id}` | GET | Show job details |
| `/api/v1/cron/jobs/{job_id}` | DELETE | Cancel a scheduled job |

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
6. Service validates confidence > 0.5 threshold
7. `SchedulerService.add_task()` computes `next_run`
8. `CronJobStore.create()` persists to database
9. Response sent to TUI with job ID and next_run

### Monitoring Tick

1. Daemon periodic task `_periodic_cron_tick` fires (every `poll_interval`)
2. `CronService._tick()` calls `SchedulerService.get_due_tasks(now)`
3. For each due job:
   - `mark_running()` updates status to `"running"`
   - `AutopilotService.submit_task(description, priority)` creates goal
   - Goal executes via StrangeLoop (RFC-222)
4. On goal completion event:
   - If recurring (`every` or `cron`):
     - Compute next `next_run`
     - `update_next_run()` with incremented `run_count`
     - Status back to `"pending"`
   - If one-time (`once`, `delay`, `at`):
     - `update_status("completed")` with `last_run`

### Job Query/Cancel (CLI via HTTP REST)

1. User sends `soothe cron list` or `soothe cron cancel <id>`
2. CLI sends HTTP GET/DELETE to daemon REST endpoint
3. Service validates `user_id` ownership (defaults to "http_api" for CLI)
4. Operation executes via `CronJobStore`
5. Response returned as JSON to CLI

## Error Handling

### Extraction Failures

| Scenario | Handling |
|----------|----------|
| Low confidence (< 0.5) | Return error to user, suggest rephrasing |
| Unparseable schedule | Return error with example syntax |
| LLM timeout | Retry with exponential backoff, max 3 attempts |
| LLM unavailable | Return error, suggest structured syntax |

### Execution Failures

| Scenario | Handling |
|----------|----------|
| Goal execution fails | Mark job `failed`, increment `run_count`, log error |
| Recurring job fails | Still reschedule for next run (don't block future executions) |
| AutopilotService unavailable | Skip tick, retry next interval |

### Persistence Failures

| Scenario | Handling |
|----------|----------|
| DB write fails | Log error, retry write, keep in-memory state as backup |
| DB read fails | Use in-memory cache if available, log warning |

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

## References

- RFC-204: Autopilot Mode (scheduler service foundation)
- RFC-222: Autopilot and Goal Engine Architecture (AutopilotService integration)
- RFC-450: Daemon Communication Protocol (IPC message format)
- RFC-625: ContextEngine as goal state source of truth
- RFC-802: Persistence Architecture (metadata database)
# Cron Service Design for Soothe Autopilot

**Date**: 2026-06-21
**Status**: Draft for RFC formalization

---

## Overview

Add a cron service to Soothe's autopilot mode that allows users to submit scheduled jobs using natural language. The daemon extracts structured schedule information via LLM, persists jobs to database, monitors for due jobs, and executes them through the existing AutopilotService goal workflow.

---

## Goals

1. **Natural language job submission** - Users describe jobs in plain language, daemon extracts schedule semantics
2. **Database persistence** - Jobs survive daemon restarts, support multi-user scenarios
3. **TUI integration** - `/cron` commands for submit, list, cancel, inspect
4. **Autopilot execution** - Jobs run as goals through existing StrangeLoop infrastructure
5. **Standalone module** - Clean separation with independent configuration

---

## Non-Goals

- Calendar integration ("remind me before my meeting with Alice")
- System monitoring triggers ("when disk is 80% full")
- Client-side NL extraction (requires LLM in TUI)
- Bypassing AutopilotService (direct StrangeLoop spawn)

---

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         TUI / CLI                               │
│  /cron add "remind me tomorrow 9am to check deploy"             │
│  /cron list, /cron cancel <id>, /cron show <id>                 │
└────────────────────────────┬────────────────────────────────────┘
                             │ WebSocket/HTTP RPC
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Daemon (soothed)                          │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              CronService (new module)                    │   │
│  │                                                          │   │
│  │  Responsibilities:                                       │   │
│  │  - Natural language extraction via LLM                   │   │
│  │  - CRUD operations: add/list/cancel/show                 │   │
│  │  - Periodic monitoring tick                              │   │
│  │  - Job state management                                  │   │
│  │                                                          │   │
│  │  Components:                                              │   │
│  │  - CronExtractionService: NL → structured extraction     │   │
│  │  - Wraps SchedulerService for schedule math              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                             │                                   │
│                             ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │           SchedulerService (enhanced)                    │   │
│  │                                                          │   │
│  │  - ScheduleSpec: cron parsing, next_run calculation      │   │
│  │  - Job status: pending/running/completed/failed/cancelled│   │
│  │  - Database persistence (replaces JSON file)             │   │
│  │  - get_due_tasks() for monitoring tick                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                             │                                   │
│                             ▼ due jobs                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              AutopilotService                            │   │
│  │                                                          │   │
│  │  - submit_task() → goal in ContextEngine                 │   │
│  │  - StrangeLoop execution via LoopPool/WorkerPool         │   │
│  │  - Job completion triggers reschedule or completion      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Periodic Task: _periodic_cron_tick (every poll_interval)      │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Metadata Database                              │
│                                                                 │
│  Table: cron_jobs                                               │
│  - Job metadata, schedule spec, status, timestamps             │
│  - Indexed on: user_id, status, next_run                       │
└─────────────────────────────────────────────────────────────────┘
```

### Module Location

```
packages/soothe/src/soothe/foundation/cron/
├── __init__.py           # Public exports
├── service.py            # CronService orchestrator
├── extraction.py         # CronExtractionService (LLM-based)
├── models.py             # CronJob, ExtractionResult dataclasses
└── store.py              # CronJobStore (DB persistence adapter)
```

---

## Components

### 1. CronService

Orchestrating service that coordinates NL extraction, persistence, and job monitoring.

**Location**: `packages/soothe/src/soothe/foundation/cron/service.py`

**Responsibilities**:
- Accept natural language job submissions
- Call CronExtractionService to parse schedule
- Persist jobs via CronJobStore
- Periodic tick to check due jobs and dispatch to AutopilotService
- Handle completion callbacks for rescheduling

**Key Methods**:
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
        """Cancel a pending job."""

    async def show_job(self, job_id: str, user_id: str) -> CronJob | None:
        """Get job details."""

    async def _tick(self) -> None:
        """Periodic check: find due jobs, dispatch to AutopilotService."""
```

**Integration Points**:
- CronExtractionService for NL parsing
- SchedulerService for schedule calculation (wrapped, not modified)
- AutopilotService for goal submission
- CronJobStore for database persistence

### 2. CronExtractionService

LLM-based natural language to structured schedule extraction.

**Location**: `packages/soothe/src/soothe/foundation/cron/extraction.py`

**Supported Patterns** (Moderate Complexity):
- Relative times: "tomorrow morning", "in 2 hours", "next Monday"
- Specific times: "at 9am", "every day at 3pm"
- Recurring: "every hour", "daily", "every Monday", "weekly on Fridays"
- End conditions: "for the next 2 weeks", "until June 30th"
- Cron-like: "every morning at 9" → `0 9 * * *`

**Extraction Schema**:
```python
@dataclass
class ExtractionResult:
    description: str          # Extracted task description
    schedule_kind: str        # "once" | "delay" | "at" | "every" | "cron"
    schedule_value: str       # Parsed schedule value
    end_condition: str | None # Optional: "until <date>" or "for <duration>"
    confidence: float         # Extraction confidence (0.0-1.0)
```

**LLM Prompt Template**:
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

Minimal changes to existing SchedulerService to support database persistence.

**Changes**:
1. Replace `_persist_path` (JSON file) with `CronJobStore` adapter
2. Add `user_id` field to ScheduledTask
3. Add `last_run`, `run_count` fields for execution history
4. Replace `_load_persisted()` / `_save_persisted()` with store methods

**Preserved Logic**:
- `ScheduleSpec` parsing (cron expressions, durations)
- `next_after()` calculation
- `get_due_tasks()` filtering
- Status transitions: pending → running → completed/failed/cancelled

### 4. CronJobStore

Database persistence adapter for cron jobs.

**Location**: `packages/soothe/src/soothe/foundation/cron/store.py`

**Implementation**:
- Uses existing metadata database connection pool
- Maps ScheduledTask to/from `cron_jobs` table
- Async CRUD operations

### 5. TUI Commands (Job Submission Only)

**Location**: `packages/soothe-cli/src/soothe_cli/tui/command_registry.py`

The TUI provides a single `/cron` command for natural language job submission during active sessions.

```python
SlashCommand(
    name="/cron",
    description="Add scheduled job (usage: /cron <natural language>)",
    bypass_tier=BypassTier.QUEUED,
    hidden_keywords="schedule timer reminder",
),
```

Job management (list, show, cancel) is provided via CLI subcommands (`soothe cron list`, `soothe cron show`, `soothe cron cancel`) communicating with the daemon through HTTP REST.

### 6. CLI Subcommands (Job Management)

**Location**: `packages/soothe-cli/src/soothe_cli/cli/commands/cron_cmd.py`

Job management commands using HTTP REST:

| Command | Description |
|---------|-------------|
| `soothe cron list [--status <s>]` | List scheduled jobs |
| `soothe cron show <job_id>` | Show job details |
| `soothe cron cancel <job_id>` | Cancel a scheduled job |

### 7. HTTP REST Endpoints (CLI Management)

**Location**: `packages/soothe-daemon/src/soothe_daemon/channels/http_rest.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/cron/jobs` | GET | List scheduled jobs |
| `/api/v1/cron/jobs/{job_id}` | GET | Show job details |
| `/api/v1/cron/jobs/{job_id}` | DELETE | Cancel a scheduled job |

**Daemon RPC Handlers** (for TUI submission only):
- `cron_add_request` → CronService.add_job()

---

## Database Schema

**Table**: `cron_jobs` (in metadata database)

```sql
CREATE TABLE IF NOT EXISTS cron_jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    description TEXT NOT NULL,
    schedule_kind TEXT NOT NULL,    -- once|delay|at|every|cron
    schedule_value TEXT NOT NULL,   -- parsed schedule value
    end_condition TEXT,             -- optional: "until <date>" etc
    priority INTEGER DEFAULT 50,
    status TEXT DEFAULT 'pending',  -- pending|running|completed|failed|cancelled
    next_run TEXT,                  -- ISO datetime, computed
    last_run TEXT,                  -- ISO datetime, updated after execution
    run_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cron_jobs_user_status
    ON cron_jobs(user_id, status);

CREATE INDEX IF NOT EXISTS idx_cron_jobs_next_run
    ON cron_jobs(next_run) WHERE status = 'pending';
```

---

## Configuration

**Location**: `config/config.template.yml` and `config/develop/config.yml`

```yaml
agent:
  # ... existing sections ...

  # === CRON SERVICE ===
  # Natural language scheduled job submission and execution.
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

---

## Data Flows

### 1. Job Submission Flow

```
User: "/cron remind me tomorrow morning at 9am to check the deploy"
  │
  ▼
TUI sends RPC: cron_add_request { text: "...", user_id: "alice" }
  │
  ▼
Daemon CronService.add_job()
  │
  ├─► CronExtractionService.extract()
  │     └─► LLM call (fast model)
  │     └─► ExtractionResult:
  │           description: "Check the deploy"
  │           schedule_kind: "at"
  │           schedule_value: "2026-06-22T09:00:00"
  │           confidence: 0.95
  │
  ├─► Validate extraction confidence > threshold
  │
  ├─► SchedulerService.add_task()
  │     └─► ScheduleSpec parsing
  │     └─► Compute next_run
  │
  ├─► CronJobStore.persist()
  │     └─► INSERT into cron_jobs table
  │
  ▼
Return CronJob to TUI (id, next_run, status)
```

### 2. Monitoring & Execution Flow

```
Daemon periodic task: _periodic_cron_tick (every poll_interval seconds)
  │
  ▼
CronService._tick()
  │
  ├─► SchedulerService.get_due_tasks(now)
  │     └─► SELECT from cron_jobs WHERE status='pending' AND next_run <= now
  │
  ├─► For each due task:
  │     ├─► SchedulerService.mark_running(task_id)
  │     │     └─► UPDATE status='running'
  │     │
  │     ├─► AutopilotService.submit_task(task.description, priority)
  │     │     └─► Creates goal in ContextEngine
  │     │     └─► StrangeLoop execution via LoopPool/WorkerPool
  │     │
  │     └─► On goal completion event:
  │           ├─► If recurring (every|cron):
  │           │     └─► SchedulerService.schedule_next(task_id)
  │           │     └─► UPDATE next_run, status='pending', run_count++
  │           │
  │           └─► Else (once|delay|at):
  │           │     └─► SchedulerService.mark_completed(task_id)
  │           │     └─► UPDATE status='completed', last_run=now
  │
  ▼
Continue monitoring loop
```

### 3. CLI Query & Cancel Flow (via HTTP REST)

```
User: "soothe cron list"
  │
  ▼
CLI sends HTTP GET: /api/v1/cron/jobs
  │
  ▼
HttpRestChannel.cron_list_jobs()
  │
  ├─► CronService.list_jobs(user_id="http_api")
  │     └─► CronJobStore.list_by_user()
  │           └─► SELECT from cron_jobs WHERE user_id=?
  │
  ▼
Return list of CronJob (id, description, status, next_run, run_count)


User: "soothe cron cancel abc123"
  │
  ▼
CLI sends HTTP DELETE: /api/v1/cron/jobs/abc123
  │
  ▼
HttpRestChannel.cron_cancel_job(job_id)
  │
  ├─► CronService.cancel_job(job_id, user_id="http_api")
  │     ├─► Verify job exists
  │     └─► CronJobStore.update_status(job_id, "cancelled")
  │           └─► UPDATE status='cancelled'
  │
  ▼
Return {"cancelled": true, "job_id": "abc123"}
```

---

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

---

## Testing Strategy

### Unit Tests

1. **CronExtractionService** - Mock LLM responses, test extraction parsing
2. **SchedulerService** - Test cron parsing, next_run calculation, edge cases
3. **CronJobStore** - Mock DB, test CRUD operations
4. **CronService** - Mock dependencies, test orchestration flows

### Integration Tests

1. **End-to-end submission** - TUI → daemon → DB → verify persisted
2. **Execution flow** - Due job → AutopilotService → verify goal created
3. **Rescheduling** - Recurring job completes → verify next_run updated
4. **Daemon restart** - Jobs persist across restart, due jobs picked up

---

## Implementation Phases

### Phase 1: Core Infrastructure
- CronConfig Pydantic model
- CronJob dataclass and ExtractionResult schema
- CronJobStore with database adapter
- Enhanced SchedulerService with DB persistence

### Phase 2: NL Extraction
- CronExtractionService with LLM prompt template
- Extraction confidence validation
- Fallback for extraction failures

### Phase 3: CronService Orchestrator
- CronService with add/list/cancel/show methods
- Periodic tick integration
- AutopilotService goal submission

### Phase 4: TUI Integration
- Command registry entries
- Daemon RPC handlers
- CLI commands for non-TUI usage

### Phase 5: Testing & Polish
- Unit tests for each component
- Integration tests for flows
- Config sync (template + dev files)

---

## Open Questions

None. All design decisions finalized through brainstorming session.

---

## References

- RFC-204: Scheduled tasks feeding GoalEngine
- RFC-222: AutopilotService loop pool and scheduling
- RFC-625: ContextEngine as goal state source of truth
- RFC-802: Persistence architecture (SQLite/PostgreSQL)
- IG-434: Autonomous config consolidation
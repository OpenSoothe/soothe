# IG-502: Cron Service Implementation

**Guide**: IG-502
**Title**: Implement RFC-229 Cron Service for Autopilot
**Created**: 2026-06-24
**Related RFCs**: RFC-229 (Cron Service for Autopilot), RFC-204 (Autopilot Mode), RFC-222 (Autopilot and Goal Engine Architecture), RFC-802 (Persistence Architecture)
**Scope**: Full RFC-229 implementation in 5 phases as specified.

---

## Goal

Implement the Cron Service as defined in RFC-229, enabling natural language scheduled job submission for Autopilot. Users can submit jobs like `/cron remind me tomorrow at 9am to check the deploy`, with the daemon extracting schedule semantics via LLM, persisting to database, monitoring for due jobs, and executing through AutopilotService.

## Success Criteria

| Criterion | Verification |
|-----------|--------------|
| Natural language extraction works | Unit tests with mock LLM responses covering all schedule patterns |
| Jobs persist across daemon restarts | Integration test: add job → restart daemon → job still present |
| Due jobs dispatch to AutopilotService | Integration test: schedule job for immediate time → verify goal created |
| Recurring jobs reschedule correctly | Unit test: every-hour job completes → verify next_run computed |
| TUI `/cron` command functional | Manual test: `/cron remind me tomorrow at 9am to check deploy` works |
| CLI commands functional | Manual test: `soothe cron list`, `soothe cron show`, `soothe cron cancel` work |
| All tests pass | `./scripts/verify_finally.sh` passes |

---

## Architecture (from RFC-229)

```
packages/soothe/src/soothe/foundation/cron/
├── __init__.py           # Public exports
├── service.py            # CronService orchestrator
├── extraction.py         # CronExtractionService (LLM-based)
├── models.py             # CronJob, ExtractionResult dataclasses
└── store.py              # CronJobStore (DB persistence adapter)
```

**Integration points**:
- `CronExtractionService` → LLM via `init_chat_model()`
- `CronService` → `AutopilotService.submit_task()` for goal dispatch
- `CronService` → existing `SchedulerService` (wrapped) for schedule math
- `CronJobStore` → metadata database (RFC-802)

---

## Implementation Phases

### Phase 1: Core Infrastructure

**Estimated effort**: 1-2 sessions

#### Tasks

1. **Add CronConfig to settings**
   - Location: `packages/soothe/src/soothe/config/settings.py`
   - Add `CronConfig` Pydantic model per RFC-229 spec
   - Add `cron: CronConfig` field to main config class
   - Update `config/config.template.yml` and `config/develop/config.yml`

2. **Create models.py**
   - Location: `packages/soothe/src/soothe/foundation/cron/models.py`
   - Implement `CronJob` dataclass with all fields
   - Implement `ExtractionResult` dataclass
   - Implement `ScheduleKind` enum

3. **Create store.py**
   - Location: `packages/soothe/src/soothe/foundation/cron/store.py`
   - Implement `CronJobStore` with async CRUD methods
   - Use existing metadata database connection pool
   - Map `CronJob` to/from `cron_jobs` table

4. **Create database schema**
   - Location: `packages/soothe/src/soothe/foundation/persistence/schema.py` (or equivalent)
   - Add `cron_jobs` table creation SQL
   - Add indexes for `user_id, status` and `next_run`

5. **Enhance SchedulerService**
   - Location: `packages/soothe/src/soothe/core/goal_engine/scheduled_tasks.py`
   - Add `user_id` field to `ScheduledTask`
   - Add `last_run`, `run_count` fields
   - Replace JSON persistence with store adapter pattern
   - Preserve existing schedule calculation logic

#### Tests

- `packages/soothe/tests/unit/cron/test_models.py` — dataclass validation
- `packages/soothe/tests/unit/cron/test_store.py` — mock DB, test CRUD
- `packages/soothe/tests/unit/cron/test_config.py` — CronConfig validation

---

### Phase 2: NL Extraction

**Estimated effort**: 1 session

#### Tasks

1. **Create extraction.py**
   - Location: `packages/soothe/src/soothe/foundation/cron/extraction.py`
   - Implement `CronExtractionService` class
   - Build LLM prompt template per RFC-229 spec
   - Use `init_chat_model()` with configurable role (`fast` default)
   - Implement timeout handling with configurable timeout
   - Parse JSON response into `ExtractionResult`

2. **Supported patterns implementation**
   - Relative: `in 2 hours`, `tomorrow morning`, `next Monday`
   - Specific: `at 9am`, `every day at 3pm`
   - Recurring: `every hour`, `daily`, `every Monday`, `weekly on Fridays`
   - End conditions: `for the next 2 weeks`, `until June 30th`
   - Cron-like: `every morning at 9` → `0 9 * * *`

3. **Confidence validation**
   - Threshold: 0.5 (configurable via prompt tuning)
   - Low confidence → return error with rephrase suggestion

4. **Error handling**
   - LLM timeout → retry with exponential backoff (max 3)
   - LLM unavailable → return error, suggest structured syntax

#### Tests

- `packages/soothe/tests/unit/cron/test_extraction.py`
  - Mock LLM responses for each pattern
  - Test confidence threshold rejection
  - Test timeout handling
  - Test unparseable input

---

### Phase 3: CronService Orchestrator

**Estimated effort**: 1-2 sessions

#### Tasks

1. **Create service.py**
   - Location: `packages/soothe/src/soothe/foundation/cron/service.py`
   - Implement `CronService` class with:
     - `add_job(natural_language, user_id, priority)` → `CronJob`
     - `list_jobs(user_id, status)` → `list[CronJob]`
     - `cancel_job(job_id, user_id)` → `bool`
     - `show_job(job_id, user_id)` → `CronJob | None`
     - `_tick()` → periodic monitoring

2. **Integration wiring**
   - Inject `CronExtractionService` for NL parsing
   - Inject `SchedulerService` for schedule math
   - Inject `CronJobStore` for persistence
   - Inject `AutopilotService` for goal dispatch

3. **Periodic tick implementation**
   - `_tick()` method called every `poll_interval` seconds
   - Query `SchedulerService.get_due_tasks(now)`
   - For each due job:
     - Mark `running` in store
     - Call `AutopilotService.submit_task(description, priority)`
     - On completion: reschedule (recurring) or mark completed (one-time)

4. **Daemon integration**
   - Location: `packages/soothe/src/soothe/daemon/`
   - Construct `CronService` in daemon startup
   - Register periodic tick task
   - Wire completion event handler for rescheduling

5. **Event handling**
   - Listen for goal completion events from AutopilotService
   - Map goal outcome to job status update
   - Recurring: compute next_run, update status to pending
   - One-time: mark completed with last_run timestamp

#### Tests

- `packages/soothe/tests/unit/cron/test_service.py`
  - Mock all dependencies
  - Test add_job flow (extraction → schedule → persist)
  - Test tick with due jobs
  - Test rescheduling logic
- `packages/soothe/tests/integration/test_cron_flow.py`
  - End-to-end submission → persistence → execution

---

### Phase 4: TUI & CLI Integration

**Estimated effort**: 1 session

#### Tasks

1. **Add TUI command for job submission**
   - Location: `packages/soothe-cli/src/soothe_cli/tui/command_registry.py`
   - Add `/cron` command only (bypass_tier: QUEUED)
   - Hidden keywords: `schedule`, `timer`, `reminder`
   - Remove `/cron-list`, `/cron-cancel`, `/cron-show` from TUI (moved to CLI)

2. **Add CLI subcommands for job management**
   - Location: `packages/soothe-cli/src/soothe_cli/cli/commands/cron_cmd.py`
   - `soothe cron list [--status <s>]` — list jobs via HTTP REST
   - `soothe cron show <job_id>` — show details via HTTP REST
   - `soothe cron cancel <job_id>` — cancel job via HTTP REST

3. **Add daemon RPC handler for TUI submission**
   - Location: `packages/soothe-daemon/src/soothe_daemon/server/commands.py`
   - Add `cron_add` handler → `CronService.add_job()`

4. **Add HTTP REST endpoints for CLI management**
   - Location: `packages/soothe-daemon/src/soothe_daemon/channels/http_rest.py`
   - GET `/api/v1/cron/jobs` — list jobs (optional status filter)
   - GET `/api/v1/cron/jobs/{job_id}` — show job details
   - DELETE `/api/v1/cron/jobs/{job_id}` — cancel job

5. **Wire CronService to ChannelManager**
   - Location: `packages/soothe-daemon/src/soothe_daemon/channel_manager.py`
   - Pass `cron_service` to `HttpRestChannel` constructor

6. **Create and manage CronService in daemon**
   - Location: `packages/soothe-daemon/src/soothe_daemon/server/core.py`
   - Create `CronService` after `AutopilotService` is built
   - Start monitoring loop after autopilot starts
   - Stop on daemon shutdown

#### Tests

- Manual testing in TUI for `/cron` submission
- CLI command testing: `soothe cron list`, `soothe cron show`, `soothe cron cancel`
- HTTP REST endpoint testing

---

### Phase 5: Testing & Polish

**Estimated effort**: 1 session

#### Tasks

1. **Complete unit test coverage**
   - All components have unit tests
   - Edge cases: empty list, invalid job_id, wrong user_id
   - Error paths: extraction failure, DB failure, Autopilot unavailable

2. **Integration tests**
   - Submission → DB → verify persisted
   - Due job → AutopilotService → verify goal created
   - Recurring completion → verify next_run updated
   - Daemon restart → jobs survive

3. **Config sync verification**
   - `config/config.template.yml` and `config/develop/config.yml` match
   - CronConfig defaults sensible

4. **Run verification**
   - `./scripts/verify_finally.sh` passes
   - No lint errors
   - All tests pass

5. **Documentation**
   - Update CLAUDE.md if needed
   - RFC-229 cross-references already added

---

## Dependencies

| Dependency | Status | Notes |
|------------|--------|-------|
| AutopilotService | Exists | RFC-222 implemented |
| SchedulerService | Exists | Enhance, not replace |
| Metadata database | Exists | RFC-802 implemented |
| LLM utilities | Exists | Use `init_chat_model()` |
| TUI command system | Exists | Follow existing pattern |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| LLM extraction unreliable | Confidence threshold + retry + fallback error message |
| DB migration issues | Use existing schema pattern; test with SQLite and PostgreSQL |
| Tick timing drift | Use asyncio interval, not wall-clock comparison |
| Goal execution failures don't block rescheduling | Recurring jobs reschedule regardless of outcome |

---

## Files Changed (estimated)

| File | Action |
|------|--------|
| `packages/soothe/src/soothe/foundation/cron/__init__.py` | Create |
| `packages/soothe/src/soothe/foundation/cron/service.py` | Create |
| `packages/soothe/src/soothe/foundation/cron/extraction.py` | Create |
| `packages/soothe/src/soothe/foundation/cron/models.py` | Create |
| `packages/soothe/src/soothe/foundation/cron/store.py` | Create |
| `packages/soothe/src/soothe/config/settings.py` | Modify (add CronConfig) |
| `packages/soothe/src/soothe/config/models.py` | Modify (add CronConfig model) |
| `packages/soothe/src/soothe/core/goal_engine/scheduled_tasks.py` | Modify (enhance) |
| `packages/soothe-daemon/src/soothe_daemon/server/core.py` | Modify (create/manage CronService) |
| `packages/soothe-daemon/src/soothe_daemon/server/commands.py` | Modify (add cron_add RPC handler) |
| `packages/soothe-daemon/src/soothe_daemon/server/handlers.py` | Modify (wire handler mixin) |
| `packages/soothe-daemon/src/soothe_daemon/channel_manager.py` | Modify (pass cron_service) |
| `packages/soothe-daemon/src/soothe_daemon/channels/http_rest.py` | Modify (add cron REST endpoints) |
| `packages/soothe-cli/src/soothe_cli/tui/command_registry.py` | Modify (add /cron only) |
| `packages/soothe-cli/src/soothe_cli/cli/main.py` | Modify (register cron app) |
| `packages/soothe-cli/src/soothe_cli/cli/commands/cron_cmd.py` | Create (CLI subcommands) |
| `config/config.template.yml` | Modify (add cron section) |
| `config/develop/config.yml` | Modify (add cron section) |
| `packages/soothe/tests/unit/cron/*.py` | Create (unit tests) |
| `packages/soothe/tests/integration/test_cron*.py` | Create (integration tests) |

---

## Verification Checklist

Before marking complete:

- [ ] All 5 phases implemented
- [ ] Unit tests pass for each component
- [ ] Integration tests pass
- [ ] `./scripts/verify_finally.sh` passes
- [ ] Config template and dev files synced
- [ ] Manual TUI testing confirms commands work
- [ ] RFC-229 status updated to "Implemented"

---

*Implementing RFC-229: Natural language scheduled jobs for Autopilot.*
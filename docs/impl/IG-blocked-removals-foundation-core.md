# Blocked Removals: soothe.foundation.core

> Document ID: DOS-08  
> Created: 2025-01-XX  
> Related: WND-04 (Dead Code Removal Plan), DOS-07 (Removal Execution)

---

## Summary

During execution of WND-04 (Dead Code Removal Plan), two symbols were identified as **blocked from removal** due to active ecosystem dependencies and/or RFC documentation requirements.

| Symbol | Status | Blocker Type | Action Required |
|--------|--------|--------------|-----------------|
| `JobState` | ⛔ **BLOCKED** | Active Usage | Keep; no removal planned |
| `Job` | ⛔ **BLOCKED** | RFC Documentation | Schedule RFC audit |

---

## Blocked Item 1: JobState Enum

### Location
`packages/soothe/src/soothe/foundation/core/entities.py` (lines 12-49)

### Blocker: Active Ecosystem Usage

The `JobState` enum is actively used across multiple packages:

| Package | File | Usage |
|---------|------|-------|
| soothe-cli | `src/soothe_cli/commands/cron_cmd.py` | CLI command handling |
| soothe-daemon | `src/soothe_daemon/protocol/schemas.py` | Protocol schemas |
| soothe-sdk | `src/soothe_sdk/client/protocol_params.py` | Client protocol params |
| soothe-sdk | `src/soothe_sdk/client/ws_command_client.py` | WebSocket client |
| soothe | `src/soothe/foundation/cron/models.py` | Cron models |
| soothe | `src/soothe/foundation/cron/service.py` | Cron service |
| soothe | `src/soothe/foundation/cron/store.py` | Cron store |

### Decision
**KEEP** - Do not remove. This is a core part of the job lifecycle API used across the entire ecosystem.

---

## Blocked Item 2: Job Dataclass

### Location
`packages/soothe/src/soothe/foundation/core/entities.py` (lines 162-223)

### Blocker: RFC Documentation

The `Job` dataclass is documented in the following RFCs:

| RFC | Section | Context |
|-----|---------|---------|
| RFC-228 | Job Lifecycle | Core job entity definition |
| RFC-626 | Cron Integration | Job scheduling and execution |

### Concern
While `Job` is documented in RFCs, there is a **potential mismatch** between:
1. **RFC documentation** (describes `Job` as core entity)
2. **Runtime usage** (may have evolved or been superseded by other implementations)

The `Job` class was found to have **zero runtime usages** in the codebase (via vulture/dead code scan), but this conflicts with its documented importance in RFCs.

### Decision
**BLOCKED** - Schedule separate RFC audit to verify actual runtime usage vs documentation.

---

## Recommended Actions

### Immediate
- [x] Keep `JobState` - no removal planned
- [x] Keep `Job` - pending audit

### Short-term (Next Sprint)
- [ ] Schedule RFC audit for `Job` dataclass
- [ ] Review RFC-228 and RFC-626 for accuracy
- [ ] Verify if `Job` is used via dynamic imports, serialization, or external consumers
- [ ] Check if `Job` has been superseded by `CronJob` or other entities

### Audit Checklist for Job Dataclass

When conducting the RFC audit, verify:

1. **Runtime Usage**
   - [ ] Search for dynamic imports (`getattr`, `importlib`)
   - [ ] Check serialization/deserialization paths
   - [ ] Review external API consumers
   - [ ] Check database schema migrations

2. **RFC Accuracy**
   - [ ] Does RFC-228 still reflect current implementation?
   - [ ] Is `Job` actually used in cron integration (RFC-626)?
   - [ ] Are there newer entities that replaced `Job`?

3. **Migration Path**
   - [ ] If `Job` is unused, document migration to replacement
   - [ ] If `Job` is used externally, document public API commitment

---

## Related Work

| Document | Description |
|----------|-------------|
| WND-04 | Dead code removal plan (Phases 1-2 completed) |
| DOS-07 | Removal execution (JobCheckpoint, constants removed) |
| RFC-228 | Job Lifecycle specification |
| RFC-626 | Cron Integration specification |

---

## Changelog

| Date | Change | Author |
|------|--------|--------|
| 2025-01-XX | Initial blocked items documentation | Assistant |

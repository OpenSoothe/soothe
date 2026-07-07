# Blocked Removals: soothe.foundation.core

> Document ID: DOS-08  
> Created: 2025-01-XX  
> Related: WND-04 (Dead Code Removal Plan), DOS-07 (Removal Execution), IG-563

---

## Summary

During execution of WND-04 (Dead Code Removal Plan), symbols were identified as **blocked from removal** due to active ecosystem dependencies and/or RFC documentation requirements.

| Symbol | Status | Blocker Type | Action Required |
|--------|--------|--------------|-----------------|
| `JobState` | ✅ **REMOVED** (IG-563) | Was incorrectly blocked | Confirmed zero runtime consumers; distinct from cron `JobStatus` |
| `Job` | ✅ **REMOVED** (IG-563) | Was blocked pending audit | Audit complete: unused facade; daemon Job IPC uses `GoalNode` via ContextEngine |

---

## Resolution (IG-563)

The prior audit conflated `foundation.core.entities.JobState` with `foundation.cron.models.JobStatus`. Only the cron enum is used across the ecosystem. The `Job` dataclass had zero runtime imports outside lazy exports in `core/__init__.py`.

Both symbols were removed in IG-563. See [`IG-563-foundation-dead-code-cleanup.md`](IG-563-foundation-dead-code-cleanup.md).

---

## Changelog

| Date | Change | Author |
|------|--------|--------|
| 2025-01-XX | Initial blocked items documentation | Assistant |
| 2026-07-07 | Job/JobState removed after audit (IG-563) | Assistant |

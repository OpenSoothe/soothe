# IG-638: Execution tools phase 4 — retention, tail, capped stdout

**Status:** Complete

## Goal

Complete background log lifecycle and reduce memory use for verbose sync commands.

## Scope

1. `background_log_retention_days` config — prune stale `bg-*.log` on spawn (0 = disable).
2. `tail_background_log` tool — last N lines from `bg-{pid}.log`.
3. `run_command` — stop reading stdout once `max_output_length` is reached (kill process group).

## Verification

- `./scripts/verify_finally.sh` — passed

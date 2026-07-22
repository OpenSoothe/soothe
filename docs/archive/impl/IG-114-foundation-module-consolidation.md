# IG-114: Consolidate `soothe`

## Goal

- Move `soothe.core.foundation` → `soothe`.
- Merge `soothe.text` and `soothe.slash_commands` into `soothe`.
- Remove `core/foundation`, `text/`, and `slash_commands/` package roots.

## Verification

`./scripts/verify_finally.sh` (includes `scripts/check_module_import_boundaries.sh`).

## Status

Completed.

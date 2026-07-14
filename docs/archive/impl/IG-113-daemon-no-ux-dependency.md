# IG-113: Daemon must not depend on UX

## Goal

Eliminate all `soothe.ux` imports from `soothe.daemon`. Shared text filtering, AI message extraction, Rich plan rendering, and slash-command handling live under `soothe.foundation` (merged from former `soothe.text` / `soothe.slash_commands`) and `soothe.plan`; UX re-exports where needed.

## Changes

- `daemon/entrypoint.py`: `setup_logging` from `soothe.logging`.
- New `soothe/text/ai_message.py`, `soothe/text/internal_assistant.py`; `DisplayPolicy` delegates internal JSON/search-data filtering to `internal_assistant`.
- New `soothe/plan/rich_tree.py`: `render_plan_tree`.
- New `soothe/slash_commands/`: moved from `ux/tui/commands.py`; daemon `_handlers` imports from here.
- `daemon/query_engine.py`: imports from `soothe.foundation` only (for text helpers).
- `daemon/health/__init__.py`: docstring examples without UX.
- Regression guard: `scripts/check_module_import_boundaries.sh` (wired into `verify_finally.sh`).

## Verification

`./scripts/verify_finally.sh`

## Status

Completed.

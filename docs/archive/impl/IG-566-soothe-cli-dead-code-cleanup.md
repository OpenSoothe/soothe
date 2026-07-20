# IG-566: soothe-cli Legacy and Dead Code Cleanup

## Status

Completed

## Goal

Remove confirmed dead and unwired code from `packages/soothe-cli` without changing current TUI or headless behavior.

## Removed

| Item | Reason |
|------|--------|
| `tui/widgets/autopilot_dashboard.py` | Fully implemented but never imported or mounted; TUI `/autopilot` submits jobs only |
| `AUTOPILOT_*` constants in `tui/preview_limits.py` | Only consumed by deleted dashboard module |
| `runtime/wire/display_text.py` | Zero importers; callers use `soothe_sdk.display.text_extract` directly |
| `create_display_policy()` in `runtime/policy/display_policy.py` | Never called; `EventProcessor` uses `DisplayPolicy()` directly |
| `StreamAccumulator` alias in `runtime/state/stream_accumulator.py` | Unused alias for `StreamingTextAccumulator` |
| `get_user_claude_skills_dir()`, `get_project_claude_skills_dir()`, `get_built_in_skills_dir()`, `get_extra_skills_dirs()` in `tui/config.py` | Experimental or thin getters with zero callers |
| `tui/app/_commands.py` | Vestigial mixin; sole method moved into `_ExecutionMixin` |

## Retained (operational, not dead)

| Item | Reason |
|------|--------|
| Legacy env aliases (`DA_CLI_RECENT_THREADS`, `SOOTHE_NO_UPDATE_CHECK`, etc.) | Active backward compatibility |
| Protocol-1 / flat-error unwrapping in daemon session and processor | Still exercised by tests and live clients |
| Dual slash-command registries (`command_registry` + `slash_commands`) | Both actively used |
| `tui/hooks.py` stub | Called from production; extension point |
| Daemon RPC `autopilot_dashboard` | Unchanged; Go client and daemon handlers remain |

## Verification

```bash
.venv/bin/vulture packages/soothe-cli/src --min-confidence 90
./scripts/verify_finally.sh
```

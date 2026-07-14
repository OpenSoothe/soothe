# IG-220: TUI `/threads` restore history load

**Status:** Completed  
**Scope:** Fix thread restore flow where selecting a thread in TUI does not reload prior history.

## Checklist

- [x] `packages/soothe/src/soothe/core/runner/__init__.py` - pass `include_events` through `get_persisted_thread_messages`
- [x] `packages/soothe-cli/src/soothe_cli/tui/daemon_session.py` - add request/response helper for thread message retrieval
- [x] `packages/soothe-cli/src/soothe_cli/tui/app.py` - use daemon-session helper when fetching thread activity events
- [x] Add/extend unit tests for include-events forwarding and thread message RPC helper
- [x] Run `./scripts/verify_finally.sh` (fails due unrelated environment/dependency issues)

## Notes

- Root cause: TUI thread restore requests full thread history (`include_events=True`) but the daemon runner wrapper did not accept/forward that field, breaking the history event fetch path and leaving restore with incomplete or empty history.
- Targeted tests passed:
  - `uv run pytest tests/unit/ux/tui/test_daemon_session_normalize.py -q`
  - `uv run pytest tests/unit/core/runner/test_runner_thread_messages.py -q`
- Full verify (`./scripts/verify_finally.sh`) fails outside this fix area due environment/package issues (`pandas` import and missing `tarzi/pkg_resources`).

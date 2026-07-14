# IG-223: Resume thread checkpoint rehydration

**Status:** Completed  
**Scope:** Auto-recover CoreAgent checkpoint messages from thread logs when resuming a thread with empty persisted `messages` state.

## Checklist

- [x] `packages/soothe-cli/src/soothe_cli/tui/app.py` - detect empty daemon thread state and attempt conversation-log recovery
- [x] `packages/soothe-cli/src/soothe_cli/tui/app.py` - persist recovered messages back via `thread_update_state`
- [x] `packages/soothe-cli/tests/unit/tui/test_convert_messages_to_data.py` - add resume rehydration regression tests
- [x] Run targeted `soothe-cli` unit tests

## Notes

- UI card replay can succeed while CoreAgent checkpoint state is empty; this makes the model respond as if there is no prior context.
- Recovery should rebuild minimal conversation memory (`HumanMessage` / `AIMessage`) from persisted thread conversation rows.
- Verification:
  - `uv run pytest tests/unit/tui/test_convert_messages_to_data.py tests/unit/ux/tui/test_daemon_session_normalize.py -q`

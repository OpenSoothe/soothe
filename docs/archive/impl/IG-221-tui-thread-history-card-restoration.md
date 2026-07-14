# IG-221: TUI resumed-thread card restoration

**Status:** Completed  
**Scope:** Ensure resumed threads render canonical TUI cards (tool/user/assistant) instead of degraded generic app messages.

## Checklist

- [x] `packages/soothe-cli/src/soothe_cli/tui/app.py` - prefer checkpoint message conversion for resumed history
- [x] `packages/soothe-cli/src/soothe_cli/tui/app.py` - use ThreadLogger event conversion only as fallback when checkpoint messages are unavailable
- [x] `packages/soothe-cli/src/soothe_cli/tui/app.py` - recover tool names/outputs from `thread_messages` metadata in fallback mode
- [x] `packages/soothe-cli/tests/unit/tui/test_convert_messages_to_data.py` - add regression tests for checkpoint-priority and metadata-based fallback conversion
- [x] Run targeted `soothe-cli` unit tests

## Notes

- Current resumed-history merge path can produce noisy generic `Event` lines and `Tool: unknown(...)` rows when ThreadLogger events are converted without using metadata-rich fields.
- Checkpoint messages already map to canonical TUI cards via `_convert_messages_to_data`; this should be the primary restoration source.
- Verification:
  - `uv run pytest tests/unit/tui/test_convert_messages_to_data.py tests/unit/ux/tui/test_daemon_session_normalize.py -q`

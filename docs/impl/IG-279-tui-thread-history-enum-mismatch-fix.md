# IG-220: TUI thread history enum mismatch fix

**Status:** Completed  
**Scope:** Fix thread history loading crash caused by stale message-conversion enums/fields in TUI history recovery.

## Checklist

- [x] Identify failing conversion path in `soothe_cli.tui.app` (`_fetch_thread_history_data`).
- [x] Update ThreadLogger event conversion to current `MessageData` schema.
- [x] Update combined timeline conversion to reuse canonical checkpoint message conversion.
- [x] Run targeted verification for `soothe-cli`.

## Notes

- Observed runtime error: `AttributeError: HUMAN` from stale enum reference in `_convert_single_message_to_data`.
- The affected methods still used legacy fields (`message_type`, `status`, `result`, `namespace`) incompatible with current `MessageData`.
- `_convert_combined_to_data` now batches checkpoint messages and delegates conversion to `_convert_messages_to_data`, preserving existing tool-call/result matching logic and avoiding enum drift between duplicate conversion paths.

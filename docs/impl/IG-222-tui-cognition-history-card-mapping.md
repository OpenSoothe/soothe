# IG-222: TUI cognition history card mapping

**Status:** Completed  
**Scope:** Restore cognition-specific TUI cards (goal tree, plan reasoning, step progress) when replaying resumed thread history.

## Checklist

- [x] `packages/soothe-cli/src/soothe_cli/tui/app.py` - map persisted cognition event types to `MessageData` cognition variants
- [x] `packages/soothe-cli/src/soothe_cli/tui/app.py` - avoid generic fallback `Event:` lines for known cognition event payloads
- [x] `packages/soothe-cli/tests/unit/tui/test_convert_messages_to_data.py` - add regression coverage for cognition-event-to-card conversion
- [x] Run targeted `soothe-cli` unit tests

## Notes

- Symptom: resumed threads show plain `Event: soothe.cognition.agent_loop.*` lines instead of cognition cards.
- Root cause: history fallback conversion recognizes tool and generic events, but does not map cognition event payloads into specialized `MessageType` variants.
- Verification:
  - `uv run pytest tests/unit/tui/test_convert_messages_to_data.py tests/unit/ux/tui/test_daemon_session_normalize.py -q`

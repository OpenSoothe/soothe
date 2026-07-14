# IG-210: Tool result dead code cleanup

## Status

Completed — `./scripts/verify_finally.sh` passed after changes below.

## Goal

After migrating TUI tool cards to `extract_tool_result_card_payload` / `ToolResultCardPayload`, remove duplicated error-detection logic and obsolete comments. Align headless `EventProcessor` and thread history conversion with the same unified payload helper.

## Work items

1. **EventProcessor** (`packages/soothe-cli/src/soothe_cli/shared/event_processor.py`): Use `extract_tool_result_card_payload` for `is_error` in `_handle_tool_message` and `_handle_tool_message_dict`. Remove inline substring `is_error` blocks. Keep `extract_tool_brief` for renderer one-line summaries.

2. **TUI app history** (`packages/soothe-cli/src/soothe_cli/tui/app.py`): In `_convert_messages_to_data`, use the payload helper for `ToolStatus` and `tool_output` (with fallback if payload is `None`).

3. **Cleanup**: Remove obsolete re-export comment block in `packages/soothe-cli/src/soothe_cli/tui/tool_display.py`.

4. **Tests**: Extend `test_event_processor.py` for `status: error` dict; add or extend test for `_convert_messages_to_data` multimodal content if applicable.

5. **Verification**: Run `./scripts/verify_finally.sh`.

## Notes

- Headless tool-result error classification now respects LangChain `status` the same way as the TUI path, with heuristic fallback via `infer_tool_output_suggests_error` inside the payload module.

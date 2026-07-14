# IG-129: TUI debug trace (logging + tests)

## Overview

Add an opt-in **TUI debug mode** that emits structured **INFO** logs for the Textual UI path (`EventProcessor` → `TuiRenderer`) so agents and developers can diagnose duplicate streaming, namespace/`is_main` issues, and tool/turn boundaries without guessing from pixels.

## Configuration

- **Env**: `SOOTHE_TUI_DEBUG=true` (or `1` / `yes`, per Pydantic bool parsing)
- **YAML**: `tui_debug: true` under root `SootheConfig`
- **Logger**: `soothe.ux.tui.trace` — lines are prefixed with `tui_trace |`

## Implementation

| Area | Change |
|------|--------|
| `config/settings.py` | `tui_debug: bool = False` |
| `soothe/ux/shared/tui_trace_log.py` | `log_tui_trace(tui_debug=..., event=..., **fields)` |
| `soothe/ux/tui/renderer.py` | `tui_debug` ctor flag; trace assistant/tool/turn/suppress |
| `soothe/ux/shared/event_processor.py` | `tui_debug` ctor flag; trace `process_event`, stream routing, messages, emits |
| `soothe/ux/tui/app.py` | Pass `config.tui_debug` into `TuiRenderer` and `EventProcessor` |

## Testing

- `tests/unit/test_tui_debug_trace.py`: caplog on `soothe.ux.tui.trace` for `TuiRenderer` and `EventProcessor` with `tui_debug=True`.

## Verification

Run `./scripts/verify_finally.sh`.

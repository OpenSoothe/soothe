# IG-118: CLI headless progress — tree to information stream

**Status**: Completed  
**Created**: 2026-04-02  
**Scope**: Headless CLI (`--no-tui`) stderr progress layout  

## Overview

Replace nested `└`-style indentation for goal/step/progress events with a flat, chronological stream. Icons and verbosity behavior are unchanged.

## Files

| File | Change |
|------|--------|
| `src/soothe/ux/cli/stream/display_line.py` | `indent_for_level`: all levels use empty indent |
| `src/soothe/ux/cli/stream/pipeline.py` | `_on_loop_agent_reason`: one `DisplayLine` per non-empty line |
| `src/soothe/ux/cli/renderer.py` | `on_tool_result`: no `└` prefix |
| `tests/unit/test_cli_stream_display_pipeline.py` | Updated expectations + multiline reason test |

## Out of scope

- TUI plan tree and `tui/utils.py`
- Optional CLI flag for legacy tree layout

## Verification

```bash
./scripts/verify_finally.sh
```

## Follow-up: icon / LLM spacing (2026-04-02)

- Soothe stderr lines with icons (`DisplayLine`, `⚙` tool call, `✓`/`✗` tool result, errors) use `_stderr_begin_icon_block()`: after any LLM text on stdout, the next stderr icon block is prefixed with one blank stderr line.
- LLM streaming no longer inserts `\n\n` after stderr; multi-step flush uses a single `\n` before the deferred answer instead of `\n\n`.
- `on_tool_call` no longer prepends an unconditional `\n` so consecutive stderr lines stay compact.

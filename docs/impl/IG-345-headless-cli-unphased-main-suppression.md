# IG-345: Headless CLI — suppress unphased main-graph assistant text

## Status

Complete.

## Problem

`soothe --no-tui -p` prints intermediate CoreAgent narration during the execute wave (unphased `AIMessage` text) in addition to the final `goal_completion` synthesis. IG-343 documented headless as RFC-614 loop-tagged output only; `_suppress_main_assistant_body_for_headless_obj` / `_suppress_main_assistant_body_for_headless_dict` regressed to always return `False`.

## Fix

1. **Headless**: Restore suppression when `headless_output` and main graph: emit assistant body only if `assistant_output_phase(msg)` is in `LOOP_ASSISTANT_OUTPUT_PHASES`.
2. **Goal completion streaming (same file)**: Pre-existing test failure — `mark_final_answer_locked` after the first non-chunk segment blocked further segments; `final_loop_output_emitted` was set too aggressively. Relaxed: do not lock per non-chunk segment; do not register `final_loop_output_emitted` on the plain non-chunk path. Preserve boundary whitespace for non-chunk text when `final_output_mode` is `streaming` so segment boundaries match.

## Files

- `packages/soothe-cli/src/soothe_cli/shared/event_processor.py`
- `packages/soothe-cli/tests/unit/ux/test_event_processor.py`

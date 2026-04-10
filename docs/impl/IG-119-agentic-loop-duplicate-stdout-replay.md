# IG-119: Agentic Loop Duplicate Stdout (Synthetic AIMessage Replay)

**Status**: Completed  
**Date**: 2026-04-02  
**RFC References**: RFC-0008 (Agentic Goal Execution)

## Problem

Headless CLI showed the same user-visible answer multiple times after a goal completed: formatted markdown, alternate phrasing, raw tool payloads (e.g. Python list repr), then repeats.

## Root cause

In `SootheRunner._run_agentic_loop`, on `completed` the runner yielded an extra LangGraph-style message:

`AIMessage(content=final_result.full_output)`.

During the Act phase, `Executor._stream_and_collect` already forwarded all `messages` stream chunks to the client and built `StepResult.output` from the same AI + tool content. `ReasonPhase` then sets `full_output` from those step outputs (`to_evidence_string(truncate=False)`). Re-yielding that blob duplicates everything already streamed to stdout.

IG-105 addressed duplicate paths between **custom final-report events** and AIMessage; this case is **synthetic replay** of streamed content at loop completion.

## Solution

Stop emitting the synthetic `AIMessage` on agentic loop completion. Consumers still receive `full_output` on `ReasonResult` / custom completion events; live stream remains the single source of truth for assistant text.

Additionally, suppress multi-step assistant body replay in headless CLI renderer:
- when `multi_step_active=True`, `on_assistant_text()` no longer buffers/prints step body text;
- `on_turn_end()` no longer flushes suppressed multi-step bodies to stdout.
- `soothe.cognition.agent_loop.reason` now emits a single concise judgement line
  (prefer `user_summary`), instead of splitting one reason event into multiple arrow lines.
- Introduced shared `PresentationEngine` policy module for reason dedup/rate-limit
  and tool-result payload summarization to reduce CLI noise.

This keeps CLI output focused on progress summaries and completion lines, removing noisy step dumps.

## Files

- `src/soothe/core/runner/_runner_agentic.py` — remove redundant `AIMessage` yield.
- `src/soothe/ux/cli/renderer.py` — suppress multi-step assistant body output/replay.
- `src/soothe/ux/cli/stream/pipeline.py` — collapse reason event to one output line.
- `src/soothe/ux/shared/presentation_engine.py` — centralized presentation policy rules.
- `tests/unit/test_cli_renderer_spacing.py` — add regression test for no replay.
- `tests/unit/test_cli_stream_display_pipeline.py` — update reason-line expectations.

## Follow-up (2026-04-02)

Suppressing all assistant stdout in multi-iteration headless mode left **no** user-visible answer on stdout at `done`. `AgenticLoopCompletedEvent` now carries optional `final_stdout_message` (`full_output` or `user_summary`); `CliRenderer` writes it once when `multi_step_active` and locks `PresentationEngine` to avoid trailing duplicates.

# IG-311: CLI/TUI — simplify explore Task JSON assistant output

**Status**: In progress  
**Created**: 2026-05-02

## Goal

When the explore subagent streams structured JSON (`AIMessage` content: assessment `decision` blobs and final `ExploreResult`), replace raw JSON in Task-scoped stdout/TUI with the `summary` line when present (ExploreResult). Assessment-only `decision` JSON is suppressed entirely (empty display); milestones already show progress via wire events.

## Implementation

- Shared helper in `soothe_cli/shared/explore_task_display.py`: parse concatenated JSON objects, pick summary or last decision.
- **CLI** (`CliRenderer.on_assistant_text`): buffer streaming chunks for `task_scope` explore; on final chunk, format and emit once (preserves `⚙ Task(explore):…` prefix).
- **TUI** (`textual_adapter`): allow explore subgraph text through suppress gate; accumulate without per-chunk append for explore Task JSON; `_flush_assistant_text_ns` applies the same formatter.

## Verification

`./scripts/verify_finally.sh`

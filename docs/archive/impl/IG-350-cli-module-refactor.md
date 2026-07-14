# IG-350: CLI Module Refactor (`packages/soothe-cli/src/soothe_cli/cli/`)

## Context

`packages/soothe-cli/src/soothe_cli/cli/` accumulated dead code and a few
loosely organized helpers as the headless and TUI display paths converged on a
single UX tier (per IG-343 client verbosity refactor and IG-348 deprecated
`CliRenderer` removal):

- `StreamDisplayPipeline._dispatch_event` no longer routes to several
  `_on_subagent_*` / `_on_capability_*` handlers — they sit unreferenced in the
  file alongside unused result-preview extractors whose output is set but never
  read.
- `PipelineContext` carries tool-call / parallel-mode state that the pipeline
  does not consume; only its own tests touch it.
- `cli/stream/formatter.py` keeps a `_derive_source_prefix(namespace)` helper
  that always returns `None` (single UX tier, no debug prefixes), plus three
  format helpers (`abbreviate_text`, `format_tool_call`, `format_tool_result`)
  whose only call sites are tests or removed dead methods.
- `DisplayLine.source_prefix` is therefore always `None`.
- `cli/utils.py::make_tool_block` is unused.
- `cli/main.py` inlines five `_thread_*` Typer wrappers that simply forward to
  `cli/commands/thread_cmd.py` — autopilot already exposes a sub-`Typer`
  directly; thread should mirror it.
- `cli/headless_renderer.py` is only consumed by `cli/execution/daemon.py`, and
  `cli/task_scope_display.py` is a stream-display formatting helper used by
  `cli/stream/formatter.py` and the TUI.

## Work

### 1. Dead code removal

- Delete `cli/utils.py` (`make_tool_block` has no callers).
- Trim `cli/stream/pipeline.py`:
  - Remove unused handlers `_on_subagent_dispatched`, `_on_subagent_judgement`,
    `_on_subagent_step`, `_on_capability_step`, `_on_capability_activity`.
  - Remove unused constants `BATCH_STEP_STARTED`, `BATCH_STEP_COMPLETED`.
  - Remove `_extract_result_preview` and the four subagent-specific extractors
    plus the writes to `subagent_completion_shown` / `subagent_result_preview`.
  - Drop `_current_namespace` tracking and `namespace=` kwargs from formatter
    calls.
- Slim `cli/stream/context.py` to goal/step state only:
  - Drop `pending_tool_calls`, `parallel_mode`, `parallel_header_emitted`,
    `step_header_emitted`, `subagent_name`, `subagent_milestones`,
    `subagent_completion_shown`, `subagent_result_preview` fields.
  - Drop `start_tool_call`, `complete_tool_call`, and `ToolCallInfo`.
  - Update `cli/stream/__init__.py` to drop `ToolCallInfo` re-exports.
- Simplify `cli/stream/formatter.py` (IG-343 final cleanup):
  - Remove `_derive_source_prefix` and the `namespace` parameter from every
    `format_*` function.
  - Remove `abbreviate_text`, `format_tool_call`, and `format_tool_result`.
- Remove `source_prefix` field and rendering from
  `cli/stream/display_line.py::DisplayLine`.

### 2. Reorganization

- Move thread Typer wrappers from `cli/main.py` into a `thread_app` declared in
  `cli/commands/thread_cmd.py` (mirroring `autopilot_cmd.py`).
- Relocate `cli/headless_renderer.py` to
  `cli/execution/headless_renderer.py`; update `cli/execution/daemon.py` import.
- Relocate `cli/task_scope_display.py` to `cli/stream/task_scope.py`; update
  `cli/stream/formatter.py` and `tui/textual_adapter.py` imports.

### 3. Tests

- Delete `tests/unit/ux/test_debug_prefix.py`.
- Trim `tests/unit/ux/cli/test_cli_stream_display_pipeline.py`: drop tests for
  `abbreviate_text`, `format_tool_call`, `format_tool_result`,
  `start_tool_call` / `complete_tool_call` / `parallel_mode`; keep coverage
  for goal/step/subagent flows.
- Update import paths in `tests/unit/ux/cli/test_task_scope_display.py` and
  `tests/unit/ux/cli/test_headless_renderer_streaming.py`.

## Verification

`./scripts/verify_finally.sh` (format check, lint, unit tests).

## Out of scope

- `loop_commands.py` (lives at the package root, not under `cli/`).
- Daemon, SDK, deeper TUI internals (only import paths updated).
- Deduplicating `_require_daemon` / `_check_daemon` / `_rpc` between
  `loop_commands.py` and `cli/commands/thread_cmd.py` — potential follow-up.

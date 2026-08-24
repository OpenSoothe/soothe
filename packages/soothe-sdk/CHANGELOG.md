# Changelog

All notable changes to soothe-sdk are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.12] - 2026-08-24

### Added
- Add `PLAN_REVIEW` to the `MessageType` enum and the corresponding plan-review answered-card fields on `MessageData`: `plan_review_action` (`"Approve"`/`"Reject"`), `plan_review_comments`, `plan_markdown`, `plan_path`, and `plan_origin_node` (`plan_mode_review` / `planner_subagent_review`). These fields are registered in `UPDATABLE_FIELDS` so the display-card ledger can update plan-review cards in place.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v1.0.11...v1.0.12

## [1.0.11] - 2026-08-24

### Fixed
- Restore `push_/reset_/publish_/clear_langfuse_system_prompt_hint` in `observability.langfuse.system_hint` — these were wrongly removed as "dead code" in 1.0.10 by the CFB-01 scan (which only checked monorepo `src/` for callers), but `soothe-nano` imports `publish_` and `clear_` at runtime in its `system_prompt` middleware. The removal caused an `ImportError` that crashed every loop's first execute step.

### Changed
- Add `soothe-nano` as a workspace member (submodule at `packages/soothe-nano`) with `workspace = true` source in the root `pyproject.toml`; update Makefile `PACKAGES` to format/lint/test nano alongside the other monorepo packages.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v1.0.10...v1.0.11

## [1.0.10] - 2026-08-21

### Changed
- Drop the `medium` task-complexity tier from `TaskComplexity` (and its `MEDIUM` member) so routing collapses to three levels: `minimal`, `simple`, and `complex`. Update the `RoutingClassification.task_complexity` field description accordingly.

### Removed
- Drop the legacy `trivial` label from the loop-stream phase allowlist test in favor of the renamed `minimal` label.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v1.0.9...v1.0.10

## [1.0.9] - 2026-08-20

### Fixed
- Flatten inherited LangGraph `AsyncCallbackManager` callbacks into a plain handler list in `merge_langfuse_runnable_config` so nano structured-output invokes no longer leak the node-level callback manager. Also surface `inheritable_handlers` when flattening.
- Add a `trace_context` property to the Langfuse callback handler (read/write view of the pinned trace context) and drop the stale `parent_run_id` gate so pinned trace parents resolve reliably.
- Try the new `langfuse.api.ingestion.types.trace_body.TraceBody` import path first, falling back to the legacy `langfuse.api.resources.ingestion.types.trace_body.TraceBody` so trace ingestion works across Langfuse versions.

### Removed
- Drop the unused `tool_lookup_step_id` helper from `display.message_processing` and the `intent_classify_langfuse_run_display_name` helper / `_INTAKE_CLASSIFY_RUN_NAME` constant from the Langfuse name helpers.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v1.0.8...v1.0.9

## [1.0.8] - 2026-08-09

### Removed
- Drop `ConcurrencyPolicy.max_parallel_goals` — goal fan-out is host Autopilot config (`agent.autopilot.max_parallel_goals`); StrangeLoop workers are single-goal. Persisted plans that still carry the key are accepted via `extra="ignore"`.

[Compare with previous version]: https://github.com/mirasoth/soothe-sdk/compare/v1.0.7...v1.0.8

## [1.0.5] - 2026-07-22

### Removed
- Drop unused tool event constants (`TOOL_STARTED`, `TOOL_COMPLETED`, `TOOL_ERROR`), message constants (`MESSAGE_RECEIVED`, `MESSAGE_SENT`), and `STRANGE_LOOP_ITERATION` — no package emits these wire types.

### Changed
- Update module-path references from the removed `soothe.foundation` namespace to `soothe.events` / `soothe.sloop` in serde type registration and registry docstrings.
- Replace the hard-coded README version line with a dynamic PyPI version badge.

[Compare with previous version]: https://github.com/mirasoth/soothe-sdk/compare/v1.0.4...v1.0.5

## [1.0.4] - 2026-07-21

### Added
- Protocol-primitive event constants: `ERROR`, `LLM_RETRY_ATTEMPT`, `MEMORY_RECALLED`, `MEMORY_STORED`, `POLICY_CHECKED`, `POLICY_DENIED` — canonical wire-visible constants shared across packages.

[Compare with previous version]: https://github.com/mirasoth/soothe-sdk/compare/v1.0.3...v1.0.4

## [1.0.3] - 2026-07-21

### Added
- Add `soothe_sdk.core.registry` — the canonical event registry owning `EventPriority`, `EventMeta`, `EventRegistry`, the process-wide `REGISTRY` singleton, and `register_event()` (auto-extracts the type string from a Pydantic model, resolves domain-based verbosity, allowlists `soothe.subagent.*` wire types). `soothe_sdk.core` re-exports the trio and `REGISTRY`/`register_event`.

### Changed
- Make `soothe_sdk.plugin.register_event` a thin re-export of `soothe_sdk.core.registry.register_event`; the `from soothe_sdk.plugin import register_event` import path is preserved for plugin authors.

### Removed
- Drop the dead lightweight plugin-registry path (`PluginEventMeta`, `_PLUGIN_EVENTS`, `get_plugin_events`, `clear_plugin_events`); plugin events now register into the shared `REGISTRY` with full metadata via the unified `register_event`.

[Compare with previous version]: https://github.com/mirasoth/soothe-sdk/compare/v1.0.2...v1.0.3

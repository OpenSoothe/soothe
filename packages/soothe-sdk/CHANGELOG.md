# Changelog

All notable changes to soothe-sdk are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.3] - 2026-07-21

### Added
- `soothe_sdk.core.registry` — canonical event registry owning `EventPriority`, `EventMeta`, `EventRegistry`, the process-wide `REGISTRY` singleton, and `register_event()` (auto-extracts the type string from a Pydantic model, resolves domain-based verbosity, allowlists `soothe.subagent.*` wire types). `soothe_sdk.core` re-exports the trio and `REGISTRY`/`register_event`.

### Changed
- `soothe_sdk.plugin.register_event` is now a thin re-export of `soothe_sdk.core.registry.register_event`; the `from soothe_sdk.plugin import register_event` import path is preserved for plugin authors.

### Removed
- Dead lightweight plugin-registry path: `PluginEventMeta`, `_PLUGIN_EVENTS`, `get_plugin_events`, and `clear_plugin_events` (zero consumers outside the SDK). Plugin events now register into the shared `REGISTRY` with full metadata (including priority) via the unified `register_event`.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v1.0.2...v1.0.3

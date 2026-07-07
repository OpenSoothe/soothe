# IG-407: Config Unification - Merge Agentic and Execution Sections

**Status**: 🔄 In Progress (schema, daemon YAML, and core wiring done; optional doc sweep remains)
**Started**: 2026-05-07
**RFC References**: RFC-201 (AgentLoop), RFC-220 (Loop Orchestrator)

**Recent (2026-05-07 follow-up)**

- **CLI sample** [`config/soothe-cli.dev.yml`](../../config/soothe-cli.dev.yml): trimmed keys that `SootheCliConfig.from_config_file` never applied (`verbosity`, `ui`, `tui`, websocket retry/timeout stubs). Canonical shape uses `daemon.transports.websocket` + `logging_level`.
- **Daemon YAML**: removed ineffective / misleading template keys (`tools.wizsearch.crawler`, sqlite_vec `db_path` / `vector_size` / `distance` until `VectorStoreProviderConfig` supports them), dropped stale footer comment; removed commented duplicate `router` block from `config.dev.yml`.
- **`SootheConfig._merge_top_level_logging_yaml`**: legacy top-level `logging.report_output` now merges into `agent_loop.report_output` (the old `data["agentic"]` path was a no-op after IG-407 removed the `agentic` field).
- **Models**: restored standalone `AutopilotConfig` (it had been accidentally merged into `InfrastructureLimitsConfig`); moved `RecoveryConfig` / `ToolCallLimitConfig` / `ToolRetryConfig` / `InfrastructureLimitsConfig` **above** `AgentLoopConfig` so `default_factory=InfrastructureLimitsConfig` resolves at class body time.
- **Imports**: fixed mistaken `soothe.core.agent_loop.agent_loop.limits.*` paths (bad bulk replace) → `soothe.core.agent_loop.execution.*`.
- **Runner / execute node**: `ConcurrencyController` still takes `ConcurrencyPolicy`; build it from flat `agent_loop.limits` fields (removed stale `limits.concurrency` nested access).
- **Tests**: integration + unit fixtures updated off `config.agentic` / `config.execution.concurrency` → `config.agent_loop` / `config.agent_loop.limits`.

## Goal

Merge `agentic` and `execution` configuration sections into unified `agent_loop` section with two-level structure:
- Behavior fields: `agent_loop.*` (direct fields, max 2 levels nesting)
- Infrastructure limits: `agent_loop.limits.*` (dedicated subsection)

Clean cut migration: NO backward compatibility, direct replacement.

## Scope

- Refactor Pydantic config models (models.py, settings.py)
- Update config YAML files (template + dev, keep synchronized)
- Update ~20+ code usage sites to new config paths
- Clean cut migration (remove deprecated classes, no backward compatibility)
- Update tests and documentation

## Files Affected

### Schema (Critical) ✅
- `packages/soothe/src/soothe/config/models.py` (Deleted AgenticLoopConfig + ExecutionConfig, added InfrastructureLimitsConfig + AgentLoopConfig)
- `packages/soothe/src/soothe/config/settings.py` (Added agent_loop field, removed backward compatibility)
- `packages/soothe/src/soothe/config/__init__.py` (Updated exports)

### Config YAML (Critical - MUST synchronize) ✅
- `config/config.template.yml` (unified `agent_loop`; removed dead keys and stale footer)
- `config/config.dev.yml` (synchronized with template structure where shared)
- `config/soothe-cli.dev.yml` (repo sample aligned with what `SootheCliConfig` actually loads — separate from daemon YAML)

### Code Usage Sites ✅
- Bulk updated 15+ files using sed replacement:
  - `config.agentic.* → config.agent_loop.*`
  - `config.execution.* → config.agent_loop.limits.*`
- Updated middleware/tool_limits.py (ExecutionConfig → InfrastructureLimitsConfig)
- Updated subagents/explore/middleware.py (ExecutionConfig → InfrastructureLimitsConfig)
- Updated middleware/_builder.py (all LLM limits paths)
- Updated all agent_loop code files (runner, executor, planner, etc.)

### Tests
- [x] Unit tests pass after import-path and model-order fixes (run `./scripts/verify_finally.sh`)
- [ ] Spot-check integration / fixtures if any still reference removed YAML keys

### Docs
- [ ] Update RFC-201 config references
- [ ] Update RFC-220 topology references
- [ ] Update IG-394 implementation notes
- [ ] Update CLAUDE.md config section (mention `agent_loop` + `soothe-cli.yml` scope)

## Progress

### Phase 1: Schema Refactoring ✅
- [x] Create `InfrastructureLimitsConfig` class (absorb ExecutionConfig fields)
- [x] Create unified `AgentLoopConfig` class (merge AgenticLoopConfig + limits)
- [x] Delete deprecated `AgenticLoopConfig` and `ExecutionConfig` classes
- [x] Update `settings.py` to use `agent_loop` field (clean cut)
- [x] Update `config/__init__.py` exports

### Phase 2: Config YAML Migration ✅
- [x] Update `config/config.template.yml` with unified agent_loop structure
- [x] Update `config/config.dev.yml` with same structure (synchronized)

### Phase 3: Code Usage Sites ✅
- [x] Bulk update all 15+ files to new config paths
- [x] Update middleware builder (LLM limits)
- [x] Update explore middleware (limits config)
- [x] Update tool_limits.py (InfrastructureLimitsConfig)
- [x] Update all runner/executor/planner files

### Phase 4: Tests & Docs 🔄
- [x] Run verification script; fix failures (import paths, model class order, `AutopilotConfig`, CLI lint)
- [ ] Update RFC-201 config references
- [ ] Update RFC-220 topology references
- [ ] Update IG-394 implementation notes
- [ ] Update CLAUDE.md config section

### Phase 5: Verification 🔄
- [x] Run `./scripts/verify_finally.sh` (format, lint, tests) — required before merge
- [ ] Optional: manual daemon + TUI smoke with `config.dev.yml` and symlinked `soothe-cli.dev.yml`

## Notes

- Clean cut migration: Removed all backward compatibility
- Per Critical Rule #2: `config.template.yml` and `config.dev.yml` stay structurally aligned for shared sections ✅
- Per Critical Rule #5: Must run `./scripts/verify_finally.sh` before commit
- **Follow-up (not done here)**: extend `VectorStoreProviderConfig` + `_vector_store_provider_kwargs` if sqlite_vec should be configurable from YAML (`db_path`, `vector_size`, distance).
- Delete `packages/soothe/src/soothe/config/models.py.bak` when no longer needed for recovery reference.
# Legacy Shim Decommission Backlog

> Catalog of all active backward-compatibility shims, migration guards, and
> legacy-format converters across the Soothe workspace. Each entry has a
> concrete decommission criterion. Shims must NOT be removed until their
> criterion is met.

**Total shim sites: 47** (8 nano, 14 CLI, 25 daemon)

---

## Risk Levels

| Risk | Meaning |
|---|---|
| **High** | Removing before criterion is met will break live wire-protocol clients or running data migrations. Requires coordinated client deprecation + migration script. |
| **Medium** | Removing before criterion is met may break deployed configs or specific client versions. Requires config audit or version-gated removal. |
| **Low** | Removing before criterion is met affects only local convenience aliases or historical fallbacks. Safe to remove once internal callers are updated. |
| **None** | No behavioral risk — comment-only or documentation. Can be cleaned opportunistically. |

---

## Part 1: Nano Shims (8 sites)

Nano is a standalone package and must not carry host/daemon wire-migration debt.
These 8 shims are config-schema migration guards that protect users upgrading
from older config formats. They are the only shims allowed in nano.

### N1: Reject legacy `role` key in embedding config

| Field | Value |
|---|---|
| ID | N1 |
| Location | `packages/soothe-nano/src/soothe_nano/config/models.py:126` |
| Symbol | `_reject_legacy_embedding_role()` |
| Type | Migration guard (Pydantic `model_validator`) |
| Risk | **Medium** |
| Behavior | Rejects removed top-level `role` key in embedding config, directing users to `roles` list. |
| Decommission criterion | All deployed configs use `roles` list, not `role`. Verify via config audit across deployments. |

### N2: Reject legacy `embedding_dims` key

| Field | Value |
|---|---|
| ID | N2 |
| Location | `packages/soothe-nano/src/soothe_nano/config/models.py:153` |
| Symbol | `_reject_legacy_embedding_dims()` |
| Type | Migration guard (Pydantic `model_validator`) |
| Risk | **Medium** |
| Behavior | Rejects removed top-level `embedding_dims` key, directing users to profile-based dimension config. |
| Decommission criterion | All deployed configs use profile-based dimensions. Verify via config audit. |

### N3: Migrate legacy `url` field to `endpoint`

| Field | Value |
|---|---|
| ID | N3 |
| Location | `packages/soothe-nano/src/soothe_nano/config/models.py:236` |
| Symbol | `_migrate_legacy_url_field()` |
| Type | Migration guard (Pydantic `model_validator`) |
| Risk | **Low** |
| Behavior | Maps deprecated `url` key to `endpoint` during config validation. Non-rejecting (auto-migrates). |
| Decommission criterion | All deployed configs use `endpoint`, not `url`. Verify via config audit. |

### N4: Normalize legacy routing config

| Field | Value |
|---|---|
| ID | N4 |
| Location | `packages/soothe-nano/src/soothe_nano/config/models.py:636` |
| Symbol | `_normalize_legacy_routing()` |
| Type | Migration guard (Pydantic `model_validator`) |
| Risk | **Low** |
| Behavior | Normalizes old routing config format to current structure during validation. Non-rejecting. |
| Decommission criterion | All deployed configs use the current routing structure. Verify via config audit. |

### N5: Strip legacy `claude_core_agent` key

| Field | Value |
|---|---|
| ID | N5 |
| Location | `packages/soothe-nano/src/soothe_nano/config/models.py:1483` |
| Symbol | `_strip_legacy_claude_core_agent()` |
| Type | Migration guard (Pydantic `model_validator`) |
| Risk | **Low** |
| Behavior | Strips removed `claude_core_agent` key from config during validation. Non-rejecting. |
| Decommission criterion | All deployed configs no longer contain `claude_core_agent`. Verify via config audit. |

### N6: Filesystem `backup_dir` parameter (legacy no-op)

| Field | Value |
|---|---|
| ID | N6 |
| Location | `packages/soothe-nano/src/soothe_nano/middleware/filesystem.py:179` |
| Symbol | `backup_dir` parameter |
| Type | Compat parameter (accepted but ignored) |
| Risk | **Low** |
| Behavior | Parameter accepted for backward compatibility but performs no operation. |
| Decommission criterion | All callers stop passing `backup_dir`. Verify via call-site audit. |

### N7: Local path resolution `config` parameter (legacy fallback)

| Field | Value |
|---|---|
| ID | N7 |
| Location | `packages/soothe-nano/src/soothe_nano/toolkits/_internal/local_path_resolution.py:25` |
| Symbol | `config` parameter |
| Type | Compat parameter (legacy: expand user only) |
| Risk | **Low** |
| Behavior | When `config` is `None`, falls back to user-home expansion only (legacy behavior). |
| Decommission criterion | All callers pass a valid `SootheConfig`. Verify via call-site audit. |

### N8: Nano `SootheConfig` split-config mirror

| Field | Value |
|---|---|
| ID | N8 |
| Location | `packages/soothe-nano/src/soothe_nano/config/settings.py` (entire `SootheConfig` class) |
| Symbol | `SootheConfig(BaseSettings)` |
| Type | Split-config mirror (nano ships standalone; host extends) |
| Risk | **Medium** |
| Behavior | Nano defines its own `SootheConfig` independent of the host's. Host's `SootheConfig` adds host-only fields (autopilot, cron, skillify). Both inherit `BaseSettings` independently. This is the documented split-config pattern — not a dead duplicate (verified by `check_nano_duplicate_symbols.py`). |
| Decommission criterion | Structural — cannot be removed while nano ships as a standalone package. Track as architecture decision, not a shim to delete. |

---

## Part 2: CLI Shims (14 sites)

### C1: Legacy CLI config path migration

| Field | Value |
|---|---|
| ID | C1 |
| Location | `packages/soothe-cli/src/soothe_cli/tui/model_config.py:23-50` |
| Symbol | `_LEGACY_CLI_CONFIG_PATH` + migration logic |
| Type | Config migration (one-time file rename) |
| Risk | **Low** |
| Behavior | Detects old `config.yml` path and renames to `cli_prefs.yml` on load. |
| Decommission criterion | All users have migrated to `cli_prefs.yml`. Can be removed after 2 release cycles. |

### C2: Legacy update-check env var aliases

| Field | Value |
|---|---|
| ID | C2 |
| Location | `packages/soothe-cli/src/soothe_cli/tui/update_check.py:322,343,365` |
| Symbol | `SOOTHE_NO_UPDATE_CHECK`, `SOOTHE_AUTO_UPDATE` |
| Type | Env var alias |
| Risk | **Low** |
| Behavior | Legacy env var names read as fallback for current `SOOTHE_UPDATE_CHECK` env vars. |
| Decommission criterion | All deployments use current env var names. Document in migration guide, remove after 2 release cycles. |

### C3: Legacy recent-threads env var alias

| Field | Value |
|---|---|
| ID | C3 |
| Location | `packages/soothe-cli/src/soothe_cli/tui/sessions.py:256` |
| Symbol | `DA_CLI_RECENT_THREADS` → `DA_CLI_RECENT_LOOPS` |
| Type | Env var alias |
| Risk | **Low** |
| Behavior | Reads legacy `DA_CLI_RECENT_THREADS` as alias for `DA_CLI_RECENT_LOOPS`. |
| Decommission criterion | All deployments use `DA_CLI_RECENT_LOOPS`. Remove after 2 release cycles. |

### C4: `action_quit_or_interrupt` backward-compat alias

| Field | Value |
|---|---|
| ID | C4 |
| Location | `packages/soothe-cli/src/soothe_cli/tui/app/_messages_mixin.py:640` |
| Symbol | `action_quit_or_interrupt()` |
| Type | Method alias |
| Risk | **Low** |
| Behavior | Backward-compatible alias for `action_dismiss_ui`. Delegates directly. |
| Decommission criterion | All keybinding configs updated to use `action_dismiss_ui`. Remove after 1 release cycle. |

### C5: Deprecated `mcp_config` CLI parameter

| Field | Value |
|---|---|
| ID | C5 |
| Location | `packages/soothe-cli/src/soothe_cli/cli/commands/run_cmd.py:39` |
| Symbol | `mcp_config` parameter |
| Type | Deprecated parameter |
| Risk | **Low** |
| Behavior | Accepts `mcp_config` but emits deprecation warning — MCP servers must be configured on the daemon. |
| Decommission criterion | All users configure MCP on the daemon, not via CLI. Remove after 2 release cycles. |

### C6: Legacy final-flush comment

| Field | Value |
|---|---|
| ID | C6 |
| Location | `packages/soothe-cli/src/soothe_cli/runtime/parse/tool_call_resolution.py:523` |
| Symbol | "legacy / final flush" comment |
| Type | Active code path comment |
| Risk | **None** |
| Behavior | Documents that the final flush path handles legacy tool-call resolution. Active code. |
| Decommission criterion | Comment-only. Clean up when the surrounding code is refactored. |

### C7: Legacy flat errors support

| Field | Value |
|---|---|
| ID | C7 |
| Location | `packages/soothe-cli/src/soothe_cli/runtime/headless/processor.py:470-479` |
| Symbol | "legacy flat errors" support |
| Type | Legacy format support |
| Risk | **Low** |
| Behavior | Supports legacy flat error format in headless processor output. |
| Decommission criterion | All daemon instances emit structured errors. Remove after daemon protocol-0 deprecation. |

### C8: Legacy frame shape comment

| Field | Value |
|---|---|
| ID | C8 |
| Location | `packages/soothe-cli/src/soothe_cli/cli/execution/daemon.py:256` |
| Symbol | "legacy frame shape" comment |
| Type | Legacy format comment |
| Risk | **None** |
| Behavior | Documents legacy frame shape handling in daemon communication. Active code. |
| Decommission criterion | Comment-only. Clean up when surrounding code is refactored. |

### C9: Legacy cognition row type

| Field | Value |
|---|---|
| ID | C9 |
| Location | `packages/soothe-cli/src/soothe_cli/tui/widgets/cognition_step_activity.py:252` |
| Symbol | "legacy" row type comment |
| Type | Legacy format comment |
| Risk | **None** |
| Behavior | Documents handling of legacy row types in cognition activity display. Active code. |
| Decommission criterion | Comment-only. Clean up when TUI row rendering is refactored. |

### C10: Deprecated model status rendering

| Field | Value |
|---|---|
| ID | C10 |
| Location | `packages/soothe-cli/src/soothe_cli/tui/widgets/model_selector.py:648-649` |
| Symbol | `status == "deprecated"` rendering |
| Type | Active UI rendering |
| Risk | **None** |
| Behavior | Renders deprecated models with a distinct visual style in the model selector TUI. Intentional display logic. |
| Decommission criterion | Not a shim — intentional UI feature. Do not remove. |

### C11: Historical reader removal note

| Field | Value |
|---|---|
| ID | C11 |
| Location | `packages/soothe-cli/src/soothe_cli/tui/_history.py:131` |
| Symbol | "Legacy checkpoint + activity-log readers were removed" |
| Type | Historical comment |
| Risk | **None** |
| Behavior | Documents that legacy readers were already removed. Comment-only. |
| Decommission criterion | Comment-only. Can be cleaned opportunistically. |

### C12: Stub hook dispatch

| Field | Value |
|---|---|
| ID | C12 |
| Location | `packages/soothe-cli/src/soothe_cli/tui/hooks.py` (entire file) |
| Symbol | `dispatch_hook()` |
| Type | Stub placeholder |
| Risk | **Low** |
| Behavior | Called at 5 sites in the TUI but does nothing ("no hooks are currently registered"). Intentional extension point placeholder. |
| Decommission criterion | Either wire real hooks or confirm the extension point will not be used. If unused, remove the file and all 5 call sites. |

### C13: `legacy_windows` Rich parameter

| Field | Value |
|---|---|
| ID | C13 |
| Location | `packages/soothe-cli/src/soothe_cli/tui/markdown_theme.py:343` |
| Symbol | `legacy_windows` parameter |
| Type | Rich library passthrough |
| Risk | **None** |
| Behavior | Passed to Rich console for Windows compatibility. Library-level parameter. |
| Decommission criterion | Not a shim — Rich library API. Do not remove. |

---

## Part 3: Daemon Shims (25 sites)

### Protocol & Wire Migration (High Risk)

### D1: Legacy streaming frame → protocol-1 `next` translator

| Field | Value |
|---|---|
| ID | D1 |
| Location | `packages/soothe-daemon/src/soothe_daemon/server/session.py:39,95,115,145,676,693,705` |
| Symbol | `_wrap_legacy_streaming_frame()`, `_translate_legacy_frame()` |
| Type | Wire migration (protocol-0 → protocol-1) |
| Risk | **High** |
| Behavior | Wraps legacy streaming frames as protocol-1 `next` envelopes for clients still using protocol-0. Active protocol translation. |
| Decommission criterion | All clients have migrated to protocol-1 wire format. Requires client version audit + deprecation cycle. |

### D2: Legacy flat-form wire schemas

| Field | Value |
|---|---|
| ID | D2 |
| Location | `packages/soothe-daemon/src/soothe_daemon/protocol/schemas.py:228,378,384,401,410,542,545,558` |
| Symbol | `LoopDetachParamsFlat`, `CommandParamsFlat`, `CommandRequestParamsFlat`, `AutopilotSubscribeFlat`, `AutopilotUnsubscribeFlat`, flat-form dispatch table |
| Type | Wire migration (legacy flat schemas) |
| Risk | **High** |
| Behavior | Accepts legacy flat-form (`type`-discriminated) wire messages alongside protocol-1 envelope form. Multiple Pydantic models + dispatch table entries. |
| Decommission criterion | All clients send protocol-1 envelope form. Requires client version audit + deprecation cycle. Reject flat-form at dispatch (line 558 is already envelope-only). |

### D3: Legacy `command` message handler

| Field | Value |
|---|---|
| ID | D3 |
| Location | `packages/soothe-daemon/src/soothe_daemon/protocol/router.py:886,1799,2052` |
| Symbol | `_handle_legacy_command()`, `DEPRECATED_LOOP_AUTOPILOT_MODE` references |
| Type | Wire migration |
| Risk | **Medium** |
| Behavior | Handles legacy `command` (slash) messages. Also references `DEPRECATED_LOOP_AUTOPILOT_MODE = "solo"` for backward-compat `autopilot_mode` field. |
| Decommission criterion | All clients use protocol-1 RPC method dispatch, not legacy `command` messages. Remove `DEPRECATED_LOOP_AUTOPILOT_MODE` when `autopilot_mode` field is dropped. |

### D4: Legacy intent hint rejection with migration messages

| Field | Value |
|---|---|
| ID | D4 |
| Location | `packages/soothe-daemon/src/soothe_daemon/protocol/intent_hints.py:16` |
| Symbol | Legacy wire values rejected with migration messages |
| Type | Wire migration |
| Risk | **Medium** |
| Behavior | Rejects legacy intent hint values with helpful migration messages directing users to current values. |
| Decommission criterion | All clients use current intent hint vocabulary. Remove migration messages after 2 release cycles. |

### D5: Legacy error code aliases

| Field | Value |
|---|---|
| ID | D5 |
| Location | `packages/soothe-daemon/src/soothe_daemon/protocol/error_codes.py:50` |
| Symbol | Legacy string code aliases in `ErrorCode(IntEnum)` |
| Type | Code aliasing |
| Risk | **Medium** |
| Behavior | Aliases legacy string error code names to their new integer enum values for backward compatibility. |
| Decommission criterion | All clients use integer error codes, not legacy string names. Verify via client audit. |

### D6: Legacy flat-form validation exemption

| Field | Value |
|---|---|
| ID | D6 |
| Location | `packages/soothe-daemon/src/soothe_daemon/protocol/validation.py:38,53` |
| Symbol | Legacy flat-form exemption during migration window |
| Type | Wire migration |
| Risk | **Medium** |
| Behavior | Exempts legacy flat-form messages from strict validation during the protocol-0→1 migration window. |
| Decommission criterion | All clients use protocol-1. Remove exemption when flat-form is rejected at dispatch. |

### Data Migration (Medium Risk)

### D7: Lazy goal snapshot migration from legacy card ledger

| Field | Value |
|---|---|
| ID | D7 |
| Location | `packages/soothe-daemon/src/soothe_daemon/display/loop_card_manager.py:548,603` |
| Symbol | `_migrate_legacy_goal_snapshots()` |
| Type | Data migration (lazy, on-load) |
| Risk | **Medium** |
| Behavior | Synthesizes goal snapshots from legacy card ledger entries on first load after upgrade. One-time lazy migration. |
| Decommission criterion | All loop databases have been loaded once post-upgrade (migration has run). Verify via migration audit log, then remove. |

### D8: Legacy MS Teams ref schema migration

| Field | Value |
|---|---|
| ID | D8 |
| Location | `packages/soothe-daemon/src/soothe_daemon/channels/msteams.py:585,627,649` |
| Symbol | `_normalize_legacy_ref()`, `_load_refs_with_compat()` |
| Type | Data migration (on-load) |
| Risk | **Medium** |
| Behavior | Normalizes stored MS Teams ref records from legacy/current schema on load. Compatibility fallback for legacy layouts. |
| Decommission criterion | All MS Teams ref files have been loaded once post-upgrade. Verify via audit, then remove. |

### D9: Legacy assistant row in query engine

| Field | Value |
|---|---|
| ID | D9 |
| Location | `packages/soothe-daemon/src/soothe_daemon/query/engine.py:1083,1086,1322,1449,1455,1465,1468` |
| Symbol | `write_legacy_assistant_row` |
| Type | Data migration (query-time compat) |
| Risk | **Medium** |
| Behavior | Writes legacy concat rows for backward compatibility with older query consumers. Conditional on `write_legacy_assistant_row` flag. |
| Decommission criterion | All query consumers use the new structured row format. Remove the flag and legacy row write path. |

### D10: Legacy `goal_records` → RFC-626 schema migration

| Field | Value |
|---|---|
| ID | D10 |
| Location | `packages/soothe-daemon/src/soothe_daemon/...` (delegates to host `packages/soothe/src/soothe/sloop/checkpoints/sqlite_backend.py:1063,1111`) |
| Symbol | `_migrate_goal_records_slim()` |
| Type | Schema migration (SQLite on-connect) |
| Risk | **High** |
| Behavior | Migrates legacy `goal_records` columns to RFC-626 `GoalIndexEntry` schema on SQLite connection. Active DB migration. |
| Decommission criterion | All SQLite checkpoint databases have been migrated (columns no longer exist). Verify via DB schema audit, then remove. |

### Config & Infrastructure (Low Risk)

### D11: `DEPRECATED_LOOP_AUTOPILOT_MODE` constant

| Field | Value |
|---|---|
| ID | D11 |
| Location | `packages/soothe-daemon/src/soothe_daemon/runtime/__init__.py:11` |
| Symbol | `DEPRECATED_LOOP_AUTOPILOT_MODE = "solo"` |
| Type | Deprecated constant |
| Risk | **Medium** |
| Behavior | Referenced by `protocol/router.py:1799,2052` for backward-compat `autopilot_mode` field in legacy wire messages. |
| Decommission criterion | All clients use the current autopilot mode vocabulary. Remove when `autopilot_mode` field is dropped from wire protocol. |

### D12: Backward-compatible alias for tests and patches

| Field | Value |
|---|---|
| ID | D12 |
| Location | `packages/soothe-daemon/src/soothe_daemon/runner/_worker_runner.py:82` |
| Symbol | Backward-compatible alias |
| Type | Test alias |
| Risk | **Low** |
| Behavior | Alias maintained for tests and external patches that reference the old name. |
| Decommission criterion | All tests and patches updated to use the current name. Verify via test audit. |

### D13: Legacy or corrupt loop re-resolve

| Field | Value |
|---|---|
| ID | D13 |
| Location | `packages/soothe-daemon/src/soothe_daemon/runtime/loop_dispatcher.py:89` |
| Symbol | "legacy or corrupt" re-resolve comment |
| Type | Legacy fallback |
| Risk | **Low** |
| Behavior | Re-resolves loop workspace when the field is missing (legacy or corrupt state). Active fallback. |
| Decommission criterion | All loop records have the workspace field populated. Remove when the fallback path is never triggered. |

### D14: Legacy `command` message warning

| Field | Value |
|---|---|
| ID | D14 |
| Location | `packages/soothe-daemon/src/soothe_daemon/server/handlers.py:175` |
| Symbol | "Received legacy 'command' message in loop worker — ignoring" |
| Type | Legacy guard |
| Risk | **Low** |
| Behavior | Logs a warning when a legacy `command` message reaches the loop worker, then ignores it. |
| Decommission criterion | All clients use protocol-1 RPC dispatch. Remove when legacy `command` messages are rejected at protocol layer. |

### D15: Legacy metadata database check

| Field | Value |
|---|---|
| ID | D15 |
| Location | `packages/soothe-daemon/src/soothe_daemon/persistence/health_check.py:56` |
| Symbol | "Legacy: check metadata database" |
| Type | Legacy DB check |
| Risk | **Low** |
| Behavior | Health check for legacy metadata database layout. |
| Decommission criterion | All deployments use the current database layout. Remove after DB migration is complete. |

### D16: Identity disabled by default for backward compatibility

| Field | Value |
|---|---|
| ID | D16 |
| Location | `packages/soothe-daemon/src/soothe_daemon/config/settings.py:85` |
| Symbol | `enabled` field — "Disabled by default for backward compatibility" |
| Type | Config default |
| Risk | **Low** |
| Behavior | Identity service disabled by default to avoid breaking deployments that don't have identity configured. |
| Decommission criterion | Identity service is stable and documented. Flip default to `True` after 1 release cycle, then remove the comment. |

### D17: Legacy `_context_tokens` fallback in router

| Field | Value |
|---|---|
| ID | D17 |
| Location | `packages/soothe-daemon/src/soothe_daemon/protocol/router.py:2523` |
| Symbol | `_context_tokens` fallback |
| Type | Legacy fallback |
| Risk | **Low** |
| Behavior | Falls back to legacy `_context_tokens` on the CoreAgent when the new token-counting API is unavailable. |
| Decommission criterion | All CoreAgent instances implement the new token-counting API. Remove the fallback. |

---

## Part 4: Host (Soothe) Shims (9 sites)

The host package (`packages/soothe/src/soothe/`) contains active migration
guards and legacy-format converters. These are host-specific (not covered by
nano or daemon shims) and count toward the 47-site total.

### H1: Reject legacy flat router config

| Field | Value |
|---|---|
| ID | H1 |
| Location | `packages/soothe/src/soothe/config/settings.py:330` |
| Symbol | `_reject_legacy_flat_router()` |
| Type | Migration guard (Pydantic `model_validator`) |
| Risk | **Medium** |
| Behavior | Rejects removed top-level `router`/`embedding_dims` YAML keys, directing users to `router_profiles`. Host mirror of nano's config guard. |
| Decommission criterion | All deployed configs use `router_profiles`. Verify via config audit. |

### H2: Deprecated `adaptive` alias for `auto`

| Field | Value |
|---|---|
| ID | H2 |
| Location | `packages/soothe/src/soothe/config/models.py:87` |
| Symbol | `normalize_agentic_final_response_mode()` — `adaptive` → `auto` |
| Type | Deprecated alias normalizer |
| Risk | **Low** |
| Behavior | Maps deprecated `adaptive` value to `auto` during config validation. |
| Decommission criterion | All deployed configs use `auto`, not `adaptive`. Remove after 2 release cycles. |

### H3: `DEFAULT_STRANGE_LOOP_MAX_ITERATIONS` alias

| Field | Value |
|---|---|
| ID | H3 |
| Location | `packages/soothe/src/soothe/config/constants.py:35` |
| Symbol | `DEFAULT_STRANGE_LOOP_MAX_ITERATIONS = DEFAULT_MAX_ITERATIONS` |
| Type | Back-compat alias |
| Risk | **Low** |
| Behavior | Pure alias for renamed constant. Referenced by 7 host modules (runner, strange_loop, execution_checkpoint, schemas, sloop_manager). |
| Decommission criterion | All callers use `DEFAULT_MAX_ITERATIONS` directly. Verify via grep, then remove alias. |

### H4: Legacy `ask_user` to wire clarify converter

| Field | Value |
|---|---|
| ID | H4 |
| Location | `packages/soothe/src/soothe/sloop/cognition/plan_generation_wire.py:105,133-135` |
| Symbol | `_legacy_ask_user_to_clarify()` |
| Type | Legacy format converter |
| Risk | **Medium** |
| Behavior | Converts a lone legacy `ask_user` step into wire clarify shape. Called by `coerce_plan_generation_wire_dict()` to salvage "glm-style malformations and legacy PlanGeneration dicts." |
| Decommission criterion | All plans use wire clarify shape natively. Remove when legacy `ask_user` steps are no longer generated by any model. |

### H5: Strip legacy StrangeLoop suffix from goal text

| Field | Value |
|---|---|
| ID | H5 |
| Location | `packages/soothe/src/soothe/prompts/user_message.py:24` |
| Symbol | Goal text suffix stripping |
| Type | Legacy cleanup |
| Risk | **Low** |
| Behavior | Strips legacy StrangeLoop suffix accidentally baked into goal text or stored checkpoints. Active cleanup logic. |
| Decommission criterion | All checkpoints have been re-loaded post-fix (suffix no longer present). Remove when old checkpoints are no longer in use. |

### H6: Legacy no-policy clarification fallback

| Field | Value |
|---|---|
| ID | H6 |
| Location | `packages/soothe/src/soothe/sloop/engine/strange_loop.py:177` |
| Symbol | "deferred via the legacy no-policy path" |
| Type | Legacy fallback |
| Risk | **Medium** |
| Behavior | Clarification requests fall through when no clarification policy is configured. Active fallback path. |
| Decommission criterion | Clarification policy is always configured at startup. Remove the no-policy fallback when the policy is mandatory. |

### H7: Legacy hard-defer path on veritas failure

| Field | Value |
|---|---|
| ID | H7 |
| Location | `packages/soothe/src/soothe/sloop/clarification/runtime_factory.py:72` |
| Symbol | Legacy hard-defer path |
| Type | Legacy fallback |
| Risk | **Medium** |
| Behavior | Hard-defers clarification when the Veritas auto-answerer fails. Active fallback path. |
| Decommission criterion | Veritas failure always defers cleanly via the new policy path. Remove the legacy hard-defer fallback. |

### H8: Legacy single-question turn format

| Field | Value |
|---|---|
| ID | H8 |
| Location | `packages/soothe/src/soothe/sloop/orchestrator/runner.py:134` |
| Symbol | Single-string form for legacy single-question turns |
| Type | Legacy format support |
| Risk | **Low** |
| Behavior | Supports legacy single-string question format in wire for turns that predate the multi-question form. |
| Decommission criterion | All turns use multi-question wire form. Remove when single-question turns are no longer generated. |

### H9: Legacy goal submission fallback

| Field | Value |
|---|---|
| ID | H9 |
| Location | `packages/soothe/src/soothe/sloop/nodes/execute_steps.py:54` |
| Symbol | "Fall back to goal when `goal_user_submission` is None" |
| Type | Legacy fallback |
| Risk | **Low** |
| Behavior | Falls back to goal text when `goal_user_submission` is None (autopilot or legacy paths). Active fallback. |
| Decommission criterion | All goal submissions populate `goal_user_submission`. Remove the fallback when the field is always set. |

### Additional Host Comment-Only Sites (Not Counted)

The following host sites are comment-only or log messages with no behavioral
risk. They are tracked for visibility but not counted in the 47-site total:

- `config/models.py:373` — ledger limit "preserve legacy behavior: full ledger, no copies" comment
- `sloop/engine/graph_interrupt.py:189` — watchdog "preserves backward compatibility" comment
- `workspace/resolution.py:59` — "Cleaned legacy anonymous workspace" log message

---

## Decommission Priorities

### Priority 1 — Wire Protocol Migration (High Risk, Coordinated)

Shims D1, D2, D3, D4, D5, D6, D10, D11, D17 are tied to the protocol-0→1
migration and legacy wire-format support. These should be decommissioned
together as part of a single RFC:

1. Announce protocol-0 deprecation in release N.
2. Emit deprecation warnings in release N+1 when protocol-0 messages are
   received.
3. Reject protocol-0 messages in release N+2.
4. Remove all protocol-0 shims in release N+3.

### Priority 2 — Data Migration (Medium Risk, Audit-Gated)

Shims D7, D8, D9, D10, H1, H4, H6, H7 require verification that all data has
been migrated or all callers use the new format:

1. Add migration audit logging (if not present).
2. Wait one full release cycle.
3. Verify audit logs show zero migrations triggered.
4. Remove migration code.

### Priority 3 — Config Migration (Low Risk, Time-Gated)

Shims N1-N5, C1, C2, C3, C5, D16 can be removed after 2 release cycles:

1. Document current config format in migration guide.
2. Wait 2 release cycles.
3. Remove migration guards and aliases.

### Priority 4 — Code Cleanup (Low Risk, Opportunistic)

Shims C4, C6, C8, C9, C11, C13, D12, D13, D14, D15, H2, H3, H5, H8, H9 and
host comment-only sites can be cleaned up during routine refactoring of the
surrounding code.

---

## Summary

| Package | Shim Count | High Risk | Medium Risk | Low Risk | None |
|---|---|---|---|---|---|
| Nano | 8 | 0 | 3 | 4 | 0 |
| CLI | 13 | 0 | 0 | 7 | 6 |
| Host | 9 | 0 | 4 | 5 | 0 |
| Daemon | 17 | 3 | 2 | 7 | 0 |
| **Total** | **47** | **3** | **9** | **23** | **6** |

| Decommission Priority | Shims | Strategy |
|---|---|---|
| P1 — Wire protocol | D1-D6, D10, D11, D17 (9 shims) | Coordinated RFC, 4-release deprecation cycle |
| P2 — Data migration | D7-D10, H1, H4, H6, H7 (8 shims) | Audit-gated, 1-release verification |
| P3 — Config migration | N1-N5, C1-C3, C5, D16 (9 shims) | Time-gated, 2-release cycle |
| P4 — Code cleanup | C4, C6-C13, D12-D15, H2, H3, H5, H8, H9 + host comments (21 shims) | Opportunistic, during refactoring |

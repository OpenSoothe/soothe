# IG-639: Resolver + Daemon Error Duplication Cleanup

**Guide**: IG-639
**Created**: 2026-07-22
**Related**: IG-638 (Cross-Package Duplication Cleanup), IG-622 (daemon kill
guards), IG-635 (Nano Host-Coupling Excision), `AGENTS.md` §3b/§3c/§7b,
`scripts/check_nano_duplicate_symbols.py`
**Status**: COMPLETE — PR-1/PR-2/PR-3 done.
`_resolver_infra.py`, `SharedCheckpointerPool`, `PostgresPoolRegistry`, and
`config/{settings,models}.py` remain deferred (see "Out of scope").
`verify_finally.sh` fully green (2026-07-22).

## Context

Post–IG-638 audit found the remaining high-ROI duplication is **drifted
near-copies** in the host resolver layer and a daemon fork of nano's error
formatters — not dead symbols (the duplicate-symbol checker is already green).

| Pair | Similarity | Host-only delta |
|------|------------|-----------------|
| `resolve/_lazy_subagent.py` ↔ `runner/resolver/_lazy_subagent.py` | ~99% | import path for `_default_materialize` |
| `resolve/_resolver_tools.py` ↔ `runner/resolver/_resolver_tools.py` | ~99% | `ensure_daemon_kill_guards_installed()` ×2 |
| `soothe_daemon/utils/error_events.py` ↔ nano `utils/error_format.py` | ~same body | uses host `ERROR` re-export (identical SDK string) |
| `spec_subagent_name` in host `subagent_catalog.py` | identical | nano already owns the helper |

Kill guards are already a **nano hook** (`register_protected_kill_hook`); host
registers via `ensure_daemon_kill_guards_installed`. Daemon server installs at
startup. Inline calls inside toolkit resolution are redundant if the host
installs once at agent-build entry.

## Scope

### IN SCOPE (mechanical, boundary-correct)

- **PR-1 — Resolver tools + lazy re-exports.** Host
  `runner/resolver/_resolver_tools.py` and `_lazy_subagent.py` become re-export
  shims over nano. Install kill guards once in `AgentBuilder.build` /
  `create_soothe_agent` (daemon already installs at server start). Repoint host
  unit-test patch targets from
  `soothe.runner.resolver._resolver_tools.*` to
  `soothe_nano.resolve._resolver_tools.*` where needed (same pattern as IG-638
  provisioning patches).
- **PR-2 — Daemon error helpers.** Replace
  `soothe_daemon/utils/error_events.py` body with re-exports of nano
  `format_cli_error` / `emit_error_event`. Nano already contains the worker-
  subprocess message; ERROR is SDK-owned and identical across packages.
- **PR-3 — Small orphans.** Host `spec_subagent_name` imports from
  `soothe_nano.agent.subagent_catalog`. Host
  `load_workspace_project_instructions` re-exports nano's alias (keep
  `load_agent_instructions` test-hook wrapper).
- **Allowlist hygiene.** Drop allowlist entries that no longer define host-side
  duplicates once shims are imports-only (`LazySubagentRunnable`,
  `subagent_description`, `emit_error_event`, …).

### OUT OF SCOPE (design / singleton — follow-up RFC)

- **`_resolver_infra.py` drift.** Host SQLite path uses
  `PersistenceDirectoryManager.get_loop_checkpoint_path()`; nano uses
  `SOOTHE_DATA_DIR / soothe_checkpoints.db`. Not a pure re-export.
- **`SharedCheckpointerPool` + `PostgresPoolRegistry` forks.** Host binds host
  registry (checkpoints pool) via module-level singletons — same blocker as
  IG-638 deferred registry RFC.
- **`config/{settings,models}.py` near-duplicates.** Split-config intentional
  mirror; needs shared-base RFC (IG-638 deferred).
- **`StepResult` / `ProtocolError`.** Intentional dual roles (IG-638 deferred).
- **`format_cli_error` SDK vs nano richness.** SDK keeps a minimal client-safe
  variant; nano keeps the rich CLI simplifier. Daemon will use nano (this IG);
  full triple-consolidation is a separate RFC.

## Package-boundary rules (MUST)

1. Do **not** move StrangeLoop / Autopilot / CE / cron / intake / daemon concepts
   into nano.
2. Host and daemon **may** import nano; nano must not import host/daemon.
3. Prefer host/daemon **re-export or subclass** of nano over byte-copies.
4. Kill-guard registration stays host-owned; nano only exposes the hook.

## Progress

### PR-1 — Resolver tools + lazy (DONE, 2026-07-22)

- Host `runner/resolver/_resolver_tools.py` is a re-export shim over nano
  (including `_call_subagent_factory` / `_resolve_single_tool_group*` for
  host callers and tests).
- Host `runner/resolver/_lazy_subagent.py` is a re-export shim over nano.
- Kill guards install once at `AgentBuilder.build` entry (daemon server start
  unchanged).
- Host unit-test patches for `_call_subagent_factory` repointed to
  `soothe_nano.resolve._resolver_tools`.
- Nano tests that incorrectly imported host
  `_resolve_single_tool_group_uncached` now import from nano (boundary fix
  surfaced by the shim — the old host copy had been hiding the leak).

### PR-2 — Daemon error helpers (DONE, 2026-07-22)

- `soothe_daemon/utils/error_events.py` re-exports nano
  `format_cli_error` / `emit_error_event`. Daemon-specific worker message
  already lives in nano's `_simplify_error_message`.

### PR-3 — Small orphans + allowlist (DONE, 2026-07-22)

- Host `spec_subagent_name` imported from
  `soothe_nano.agent.subagent_catalog` (intake catalog helpers stay host-local).
- Host `load_workspace_project_instructions` kept as a thin alias through
  host `load_agent_instructions` (preserves test hooks).
- Dropped allowlist entries for `LazySubagentRunnable`, `subagent_description`,
  and `emit_error_event` (host/daemon no longer define them).

### Verification (DONE, 2026-07-22)

`./scripts/verify_finally.sh` **fully green**.

## Status

**COMPLETE** for PR-1, PR-2, PR-3. Deferred items remain under "Out of scope"
(infra path divergence, pool-registry singleton RFC, config shared-base RFC,
StepResult / ProtocolError).

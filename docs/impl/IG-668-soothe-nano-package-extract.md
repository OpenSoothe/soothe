# IG-668: Extract soothe-nano (Coding CoreAgent)

**Guide**: IG-668  
**Title**: Extract batteries-included Coding CoreAgent into `soothe-nano`  
**Created**: 2026-07-20  
**Related**: RFC-000, RFC-100, RFC-001; design draft `docs/drafts/2026-07-20-soothe-nano-package-layout-design.md`  
**Status**: Complete (Phases A–D, 2026-07-20)

---

## Goal

```
soothe-deepagents → soothe-sdk → soothe-nano → soothe → daemon/cli
soothe-plugins → soothe-nano
```

`soothe-nano` owns the Coding CoreAgent runtime (tools, core subagents, skills, MCP, config, protocols, FS/security/workspace). Full `soothe` owns StrangeLoop, Autopilot, Context Engine, cron, identity service, and runner orchestration.

**Hard rule**: `soothe_nano` must never import `soothe`.

---

## Phase A — CoreAgent wrappers

1. Scaffold `packages/soothe-nano` (layout + `pyproject.toml` + workspace wiring).
2. Move CoreAgent runtime wrappers into `soothe_nano.agent` (`CodingCoreAgent`, `LazyCoreAgent`).
3. Host nano-local helpers previously imported from `foundation.sloop` (`ephemeral_execute_stream_enabled`, intake-only partition helpers).
4. Soothe re-exports / shims keep existing import paths working.
5. Verify scripts know about `soothe-nano` and enforce `nano ↛ soothe`.

---

## Phase B — Builder / factory / middleware

1. Move `AgentBuilder`, `create_soothe_agent` / `create_nano_agent`, middleware stack builder into `soothe_nano`.
2. `NanoConfig` alias → `SootheConfig` (proper subset split deferred to RFC-100 follow-up).
3. Soothe `AgentBuilder` subclass injects StrangeLoop `resolve_planner` when omitted.
4. Soothe `create_soothe_agent` promotes returned agent to `soothe.foundation.coreagent.coding.CodingCoreAgent`.

---

## Phase C — Toolkits, subagents, infra cluster

Bulk-migrated into `soothe_nano/` (via `scripts/migrate_soothe_nano_cluster.py`):

| Area | Canonical path |
|------|----------------|
| Toolkits | `soothe_nano.toolkits` |
| Middleware | `soothe_nano.middleware` |
| Skills + skillify | `soothe_nano.skills`, `soothe_nano.skillify` |
| MCP | `soothe_nano.mcp` |
| Plugin hooks | `soothe_nano.plugin` |
| Config | `soothe_nano.config` |
| Protocols (CoreAgent-oriented) | `soothe_nano.protocols` |
| Utils / logging | `soothe_nano.utils`, `soothe_nano.logging` |
| Core subagents | `soothe_nano.subagents` |
| FS / security / workspace / events | `soothe_nano.filesystem`, `.security`, `.workspace`, `.events` |
| Backends (CoreAgent cluster) | `soothe_nano.backends` |
| Resolvers | `soothe_nano.resolve` |

**Left in soothe** (StrangeLoop-only): `foundation/sloop`, loop persistence writer/reconciler, loop planner/runner protocols, cron, identity service, runner orchestration.

**Shim pattern**: leaf modules use `sys.modules` alias or explicit re-export; config uses re-export (not module replacement) to preserve Pydantic model identity.

---

## Phase D — Plugins + cleanup

1. `soothe-plugins` depends on `soothe-nano` (not full `soothe`).
2. `./scripts/verify_finally.sh` green across all packages.
3. RFC-100 slim-config follow-up remains optional.

---

## Module placement (summary)

| Canonical in `soothe_nano` | Compat in `soothe` |
|----------------------------|-------------------|
| `soothe_nano.agent.*` | `soothe.foundation.coreagent.coding.*` (subclass + planner injection) |
| `soothe_nano.config.*` | `soothe.config.*` re-exports |
| `soothe_nano.toolkits.*` etc. | `soothe.toolkits.*` etc. shims |
| `soothe_nano.filesystem.*` | `soothe.foundation.filesystem.*` shims |
| `resolve_planner` → `None` in nano | soothe builder injects StrangeLoop planner |

---

## Exit criteria

### Phase A
- [x] `packages/soothe-nano` is a uv workspace member
- [x] `soothe` depends on `soothe-nano`
- [x] CoreAgent wrappers live under `soothe_nano.agent` with no `soothe` imports
- [x] Existing `soothe.foundation.coreagent` import paths still work
- [x] verify enforces nano must not import soothe

### Phase B
- [x] `AgentBuilder` / factory in `soothe_nano.agent`
- [x] `create_nano_agent` public API
- [x] Soothe builder injects planner; compat `CodingCoreAgent.create()`

### Phase C
- [x] Toolkits, middleware, skills, MCP, subagents, config, protocols, backends in nano
- [x] Soothe shims preserve import paths
- [x] StrangeLoop-only modules remain in soothe

### Phase D
- [x] `soothe-plugins` → `soothe-nano`
- [x] `./scripts/verify_finally.sh` green

---

## Follow-ups

- RFC-100: split `NanoConfig` proper subset from `SootheConfig`
- Point plugin implementations at `soothe_nano.*` imports directly (shims work today)
- Retire `scripts/migrate_soothe_nano_cluster.py` once no longer needed for reference

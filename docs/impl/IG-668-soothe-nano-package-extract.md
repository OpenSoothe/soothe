# IG-668: Extract soothe-nano (Coding CoreAgent)

**Guide**: IG-668  
**Title**: Extract batteries-included Coding CoreAgent into `soothe-nano`  
**Created**: 2026-07-20  
**Related**: RFC-000, RFC-100, RFC-001; archived design draft `docs/archive/drafts/2026-07-20-soothe-nano-package-layout-design.md`  
**Status**: Complete (Phases A–D + purification Phases 0–3, 2026-07-20)

---

## Goal

```
soothe-deepagents → soothe-sdk → soothe-nano → soothe → daemon/cli
                         ↑_______________|
soothe-plugins → soothe-nano
soothe-daemon  → soothe-nano (direct) + soothe
```

`soothe-nano` owns the Coding CoreAgent runtime (tools, core subagents, skills, MCP, config slice, FS/security/workspace). Shared protocols live in `soothe_sdk.protocols`. Full `soothe` owns StrangeLoop, Autopilot, Context Engine, cron, identity service, and runner orchestration. Consumers that import `soothe_nano` declare a **direct** `soothe-nano` dependency (do not rely only on transitive `soothe`).

**Hard rule**: `soothe_nano` must never import `soothe`, and must not know about StrangeLoop / Autopilot / Context Engine / cron / identity **service** / daemon loop orchestration.

---

## Phase A — CoreAgent wrappers

1. Scaffold `packages/soothe-nano` (layout + `pyproject.toml` + workspace wiring).
2. Move CoreAgent runtime wrappers into `soothe_nano.agent` (`CodingCoreAgent`, `LazyCoreAgent`).
3. Host nano-local helpers previously imported from `foundation.sloop` (`ephemeral_execute_stream_enabled` now lives on `soothe_nano.agent.core_agent`; intake-only partition helpers live on `soothe.foundation.sloop.subagent_catalog`).
4. Soothe re-exports / shims keep existing import paths working.
5. Verify scripts know about `soothe-nano` and enforce `nano ↛ soothe`.

---

## Phase B — Builder / factory / middleware

1. Move `AgentBuilder`, `create_soothe_agent` / `create_nano_agent`, middleware stack builder into `soothe_nano`.
2. `NanoConfig` alias → slim CoreAgent config; full `SootheConfig` stays in soothe (composition).
3. Soothe `AgentBuilder` subclass injects StrangeLoop `resolve_planner` when omitted.
4. Soothe `create_soothe_agent` promotes returned agent to `soothe.foundation.coreagent.coding.CodingCoreAgent`.

---

## Phase C — Toolkits, subagents, infra cluster

Bulk-migrated into `soothe_nano/`:

| Area | Canonical path |
|------|----------------|
| Toolkits | `soothe_nano.toolkits` |
| Middleware | `soothe_nano.middleware` |
| Skills (catalog / progressive) | `soothe_nano.skills` |
| Skillify (semantic warehouse) | `soothe_daemon.skillify` (+ DTOs in `soothe_sdk.skillify`) |
| MCP | `soothe_nano.mcp` |
| Plugin hooks | `soothe_nano.plugin` |
| Config (CoreAgent slice) | `soothe_nano.config` |
| Protocols | `soothe_sdk.protocols` (not nano) |
| Utils / logging (CoreAgent) | `soothe_nano.utils`, `soothe_nano.logging` |
| Core subagents | `soothe_nano.subagents` |
| FS / security / workspace / events | `soothe_nano.filesystem`, `.security`, `.workspace`, `.events` |
| Backends (CoreAgent cluster) | `soothe_nano.backends` |
| Resolvers | `soothe_nano.resolve` |

**Left in soothe** (StrangeLoop-only): `foundation/sloop`, loop persistence, loop planner/runner protocols, cron, identity service, runner orchestration, veritas, loop messages, goal-loop Langfuse.

---

## Phase D — Plugins + cleanup

1. `soothe-plugins` and `soothe-daemon` depend on `soothe-nano` directly (plugins: not full `soothe`).
2. Workspace root + Makefile include `soothe-nano` in sync/build/publish paths.
3. `./scripts/verify_finally.sh` green across all packages.

---

## Boundary purification (Phase 0)

Move L2/L3-owned modules out of nano into soothe, then scrub nano:

| Moved to soothe | Kept / scrubbed in nano |
|-----------------|-------------------------|
| L2/L3 events, internal bus | Client stream / tool / subagent lifecycle events |
| Full `SootheConfig` (`agent.loop`, cron, Autopilot, CE) | `NanoConfig` / `agent.middleware` CoreAgent slice |
| `loop_messages`, goal-completion stream helpers | Generic stream parsers |
| Clarification / veritas | Core subagents (explore, research, plan, …) |
| Loop workspace + CE persistence | Non-loop workspace / FS / security |
| Pass1/Pass2 intention models | `RoutingClassification` / `TaskComplexity` |
| Langfuse `_goal_loop` | CoreAgent Langfuse helpers |

`agent_middleware_config()` reads `agent.middleware` or falls back to `agent.loop` when a full soothe config is passed into nano middleware.

Exit gate: `scripts/check_module_import_boundaries.sh` Rule 3c bans L2/L3 symbols in nano (except allowed “no StrangeLoop” docs).

---

## Test home (Phase 1)

Pure-nano tests live under `packages/soothe-nano/tests/` (mcp, backends, toolkits, skills, filesystem, most subagents except veritas, matching integration). Skillify tests live under `packages/soothe-daemon/tests/` (`unit/skillify`, `integration/skillify`).

- Slim `conftest.py`: env + temp workspace; **no** `SootheRunner`.
- Loop / sloop / context / cron / autopilot / runner / veritas / mixed tests remain in `packages/soothe/tests/`.

---

## Option B production imports (Phase 2)

Production code imports `soothe_nano.*` directly. Leaf `sys.modules` shims under `soothe` were deleted.

**Kept permanently (or until RFC-100):**

- `soothe.config` — host composition (`SootheConfig` wrapping nano slice)
- `soothe.foundation.coreagent.coding.*` — planner injection + class promotion
- Soothe-native L2/L3 modules (events, sloop, loop_workspace, veritas, …)
- Mixed package surfaces: `soothe.logging` (ThreadLogger + nano setup), `soothe.utils` (loop_messages / goal_completion), `soothe.utils.observability.langfuse` (goal-loop facade)

---

## Module placement (summary)

| Canonical in `soothe_nano` | Compat / host in `soothe` |
|----------------------------|---------------------------|
| `soothe_nano.agent.*` | `soothe.foundation.coreagent.coding.*` (subclass + planner injection) |
| `soothe_nano.config.*` (slim) | `soothe.config.*` (full composition) |
| `soothe_nano.toolkits.*` etc. | Direct `soothe_nano` imports (no leaf shims) |
| `resolve_planner` → `None` in nano | soothe builder injects StrangeLoop planner |
| Shared contracts (`CoreAgentProtocol`, planner/memory/durability/…, policy, persistence, vector store, identity) | Canonical **only** in ``soothe_sdk.protocols`` (nano protocols package removed) |
| Skills catalog / progressive search | `soothe_nano.skills` (substring only; no Skillify import) |
| Skillify DTOs | `soothe_sdk.skillify` |
| Skillify service | `soothe_daemon.skillify` (host config `skillify:` on `soothe.config`) |

---

## Exit criteria

### Phase A–D
- [x] Package extract, shims (interim), plugins → nano, verify green

### Phase 0 — Purify
- [x] L2/L3 modules restored in soothe; nano scrubbed
- [x] Config split: nano middleware slice vs soothe orchestration
- [x] Boundary gate for L2/L3 symbols

### Phase 1 — Tests
- [x] Pure-nano tests under `soothe-nano/tests`
- [x] Slim nano conftest

### Phase 2 — Option B
- [x] Production imports → `soothe_nano.*`
- [x] Leaf shims deleted; host wrappers retained

### Phase 3 — Docs / enforce
- [x] This IG updated
- [x] `check_module_import_boundaries.sh` Rule 3c

---

## Follow-ups

- RFC-100: further slim `NanoConfig` vs `SootheConfig` field ownership
- Optional: remove leftover package-level lazy `__getattr__` bridges once call sites are fully on nano
- Done: Skillify service moved to `soothe_daemon.skillify`; DTOs in `soothe_sdk.skillify`; nano progressive search is substring-only
- Done: identity errors → `soothe_sdk.identity.errors`; base events consolidated on `soothe_sdk.core.events`; `extract_text_from_ai_message` → `soothe_sdk.display.text_extract`
- Done: nano `prompts/` CoreAgent-only; host loop/intake/plan prompts live under `soothe.prompts`
- Done: intake-only catalog / partition / task guard moved to `soothe.foundation.sloop`; nano retains `spec_subagent_name` only; Rule 3c bans intake-only tokens in nano src
- Optional later: move `IdentityMiddleware` / runtime out of nano into soothe
- Session handover (next agent): [HANDOVER-2026-07-20-soothe-nano.md](HANDOVER-2026-07-20-soothe-nano.md)

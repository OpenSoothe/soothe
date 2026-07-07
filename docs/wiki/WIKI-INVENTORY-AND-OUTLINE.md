---
title: Wiki Inventory & New Content Outline
description: >-
  Audit of existing wiki files, cross-reference conflicts, codebase discrepancies,
  documentation gaps, and the target outline for wiki content alignment.
---

# Wiki Inventory & New Content Outline

**Created**: 2026-07-07
**Purpose**: Align `docs/wiki/` with the latest codebase status, resolve cross-reference conflicts, and establish a sharp, non-verbose content outline per section.

---

## A. Wiki File Inventory (74 files)

### Root-level files (21)

| File | Purpose | Codebase mapping | Overlaps with |
|------|---------|-------------------|---------------|
| `index.md` | Wiki hub & navigation | N/A (meta) | — |
| `getting-started.md` | **Legacy redirect** to `getting-started/index.md` | N/A | `getting-started/index.md` |
| `configuration.md` | **Legacy redirect** to `configuration-guide/index.md` | `config/` | `configuration-guide/index.md` |
| `authentication.md` | External auth with reverse proxies | `soothe_daemon/` auth | — |
| `autonomous-mode.md` | Autopilot mode user guide | `foundation/autopilot/`, `runner/_runner_autopilot_worker.py` | (gap: no architecture page) |
| `cli-reference.md` | CLI command docs | `soothe_cli/cli/` | — |
| `tui-guide.md` | TUI walkthrough | `soothe_cli/tui/` | — |
| `daemon-management.md` | Daemon lifecycle (start/stop/attach) | `soothe_daemon/server/` | — |
| `multi-transport.md` | WebSocket transport config | `soothe_daemon/server/` | — |
| `subagents.md` | User-facing subagents guide | `subagents/` | `capabilities/subagents.md` |
| `thread-management.md` | Conversation threads & resumption | `runner/_thread_manager.py`, `backends/durability/` | — |
| `query-processing-flow.md` | End-to-end query flow | `runner/`, `soothe_daemon/query/` | — |
| `troubleshooting.md` | Common issues & solutions | N/A | `troubleshooting/index.md` |
| `faq.md` | FAQ by topic | N/A | — |
| `changelog.md` | Version history | N/A | — |
| `testing-guide.md` | Testing workflow | `tests/` across packages | — |
| `contributing-guide.md` | Dev workflow & standards | `CLAUDE.md` | — |
| `howto_debug.md` | Debug & diagnostics | `logging/` | — |
| `clone-bandwidth-strategy.md` | Git clone optimization | N/A (repo meta) | — |
| `channel-plugin-guide.md` | Channel plugin development | `soothe_daemon/channels/` | — |
| `user_guide.md` | **Legacy** comprehensive user guide | N/A | `user-guides/index.md` |

### Subdirectory files (53)

| Path | Purpose | Codebase mapping |
|------|---------|-------------------|
| `getting-started/index.md` | Getting started hub | N/A |
| `getting-started/Installation.md` | Install instructions | `pyproject.toml` |
| `getting-started/Quick-Start.md` | First session | — |
| `getting-started/Basic-Concepts.md` | Core concepts | `foundation/` |
| `user-guides/index.md` | User guides hub (points to root files) | N/A |
| `architecture/index.md` | System design overview | `foundation/` |
| `core/index.md` | Core modules hub | `foundation/` |
| `core/agent-factory.md` | CoreAgent construction | `foundation/core/agent/_builder.py` |
| `core/runner.md` | SootheRunner | `runner/` |
| `core/strangeloop.md` | StrangeLoop | `foundation/sloop/` |
| `core/goal-engine.md` | ContextEngine | `foundation/context/` |
| `core/events.md` | Event system | `foundation/events/` |
| `core/resolver.md` | Protocol resolver | `runner/resolver/` |
| `core/workspace.md` | Workspace management | `foundation/workspace/` |
| `protocols/index.md` | Protocol layer hub | `protocols/` |
| `protocols/context.md` | ContextProtocol (**draft**) | `protocols/` (not impl) |
| `protocols/durability.md` | DurabilityProtocol | `protocols/durability.py` |
| `protocols/memory.md` | MemoryProtocol | `protocols/memory.py` |
| `protocols/planner.md` | PlannerProtocol & LoopPlannerProtocol | `protocols/planner.py`, `loop_planner.py` |
| `protocols/policy.md` | PolicyProtocol | `protocols/policy.py` |
| `protocols/vector-store-persistence.md` | VectorStoreProtocol & AsyncPersistStore | `protocols/vector_store.py`, `persistence.py` |
| `protocols/execution-protocols.md` | LoopRunner & Autopilot dispatch | `protocols/runner.py` |
| `protocols/loop-protocols.md` | Loop-level protocols | `protocols/loop_working_memory.py`, `loop_planner.py`, `operation_security.py` |
| `backends/index.md` | Backends hub | `backends/` |
| `backends/durability-backends.md` | Durability backends | `backends/durability/` |
| `backends/memory-backends.md` | Memory backends (MemU) | `backends/memory/` |
| `backends/persistence-backends.md` | Persistence backends | `backends/persistence/` |
| `backends/policy-backends.md` | Policy backends | `protocols/policy.py` |
| `backends/vector-store-backends.md` | Vector store backends | `backends/vector_store/` |
| `capabilities/index.md` | Capabilities hub | `subagents/`, `toolkits/`, `mcp/` |
| `capabilities/subagents.md` | Subagents architecture | `subagents/` |
| `capabilities/tools.md` | Tools system | `toolkits/` |
| `capabilities/mcp.md` | MCP integration | `mcp/` |
| `capabilities/extension-patterns.md` | Plugin extension patterns | `plugin/`, `soothe_sdk/plugin/` |
| `configuration-guide/index.md` | Config guide hub | `config/` |
| `configuration-guide/yaml-reference.md` | YAML schema | `config/settings.py` |
| `configuration-guide/environment-variables.md` | `SOOTHE_*` vars | `config/` |
| `configuration-guide/common-patterns.md` | Config examples | — |
| `configuration-guide/provider-setup.md` | LLM providers, vector stores | `config/` |
| `deployment/index.md` | Deployment hub | N/A |
| `deployment/production-setup.md` | Docker/systemd/K8s | — |
| `deployment/monitoring.md` | Langfuse, logs, health | `soothe_daemon/health/` |
| `deployment/security.md` | TLS, reverse proxy | — |
| `deployment/scaling.md` | Horizontal scaling | — |
| `deployment/backup-recovery.md` | PostgreSQL backup | `backends/durability/` |
| `api-reference/index.md` | API reference hub | N/A |
| `api-reference/core-api.md` | Core (`soothe`) API | `soothe/` |
| `api-reference/daemon-api.md` | Daemon API | `soothe_daemon/` |
| `api-reference/sdk-api.md` | SDK API | `soothe_sdk/` |
| `development/index.md` | Dev & contributing hub | N/A |
| `troubleshooting/index.md` | Troubleshooting hub (points to root) | N/A |
| `archive/index.md` | Archive hub | N/A |
| `archive/WIKI-ARCHITECTURE.md` | **Archived** wiki structure proposal | N/A (historical) |

---

## B. Cross-Reference Conflicts

### B.1 Duplicate hubs (same topic, multiple files)

| Conflict | Files | Resolution |
|----------|-------|------------|
| Getting Started hub | `getting-started.md` (legacy redirect) vs `getting-started/index.md` | **Delete** `getting-started.md`; keep `getting-started/index.md` as sole hub |
| User Guide hub | `user_guide.md` (legacy) vs `user-guides/index.md` | **Delete** `user_guide.md`; keep `user-guides/index.md` |
| Troubleshooting hub | `troubleshooting.md` (content) vs `troubleshooting/index.md` (hub pointing to root) | **Merge**: make `troubleshooting/index.md` the hub with full content; delete root `troubleshooting.md` or keep as redirect |
| Configuration hub | `configuration.md` (legacy redirect) vs `configuration-guide/index.md` | **Delete** `configuration.md`; keep `configuration-guide/index.md` |
| Subagents | `subagents.md` (user-facing) vs `capabilities/subagents.md` (architecture) | **Keep both** with clear audience split: root = usage, `capabilities/` = architecture. Add cross-links |

### B.2 Orphan files (exist but not linked from `index.md`)

These files exist but are NOT reachable from the main `index.md` navigation:

- `user-guides/index.md` — hub exists but `index.md` links to root `user_guide.md` instead
- `capabilities/` directory (5 files) — has its own nav but not linked from main `index.md`
- `protocols/` directory (9 files) — has its own nav but not linked from main `index.md`
- `api-reference/` directory (4 files) — has its own nav but not linked from main `index.md`
- `development/` directory (1 file) — not linked from main `index.md`
- `archive/` directory (2 files) — not linked from main `index.md`
- `troubleshooting/` directory (1 file) — not linked from main `index.md`
- `channel-plugin-guide.md` — not linked from `index.md`
- `clone-bandwidth-strategy.md` — not linked from `index.md` (only from `development/index.md`)

### B.3 Broken RFC references

RFCs referenced in wiki but **not present** in `docs/specs/`:

| RFC | Referenced in | Issue |
|-----|---------------|-------|
| `RFC-200` | `index.md` (ContextEngine label) | Does not exist — should be `RFC-624` |
| `RFC-203` | `protocols/loop-protocols.md` (LoopWorkingMemory) | Does not exist |
| `RFC-215` | (scattered) | Does not exist |
| `RFC-216` | (scattered) | Does not exist |
| `RFC-300` | `protocols/context.md`, `memory.md`, `vector-store-persistence.md` | Does not exist (may be intentionally archived — referenced as "superseded") |
| `RFC-611` | (scattered) | Does not exist |
| `RFC-800` | (scattered) | Does not exist — likely should be `RFC-801` |

---

## C. Codebase-Wiki Discrepancies

### C.1 "Layer N" terminology violation (CRITICAL)

**CLAUDE.md rule 6**: "NEVER use 'layer N' — use concrete names (CoreAgent, StrangeLoop, GoalEngine)."

**Violation scope** — "Layer 1/2/3" appears pervasively in:

| File | Usage |
|------|-------|
| `core/agent-factory.md` | "Layer 1 runtime foundation", "Layer 1/Layer 2 contract" |
| `core/strangeloop.md` | "Layer 2 of the execution model", "Layer 3", "Layer 1" |
| `core/goal-engine.md` | "Layer 3 of Soothe's execution model", "Layer 2" |
| `core/runner.md` | "Layer 2 hints" |
| `core/index.md` | "Layer 1 never knows about goals" |
| `api-reference/core-api.md` | "Layer 1/2/3" table |
| `api-reference/index.md` | "Layer 1/2/3" architectural layering |
| `api-reference/daemon-api.md` | "Layer 3" |
| `contributing-guide.md` | (scattered) |

**Fix**: Replace all "Layer 1" → "CoreAgent", "Layer 2" → "StrangeLoop", "Layer 3" → "ContextEngine" (or "SootheDaemon" where the daemon-layer meaning is intended — see C.2).

### C.2 Conflicting three-level models

Two **different** three-level decompositions are used in the wiki:

| Source | Level 1 | Level 2 | Level 3 |
|--------|---------|---------|---------|
| `core/` docs | CoreAgent | StrangeLoop | ContextEngine |
| `api-reference/` docs | CoreAgent | SootheRunner | SootheDaemon |

These conflate the **execution model** (CoreAgent → StrangeLoop → ContextEngine) with the **deployment model** (CoreAgent → SootheRunner → SootheDaemon). The runner sits between execution and deployment.

**Fix**: Clarify two separate models:
- **Execution model**: CoreAgent → StrangeLoop → ContextEngine (within `foundation/`)
- **Deployment model**: CoreAgent → SootheRunner → SootheDaemon (across packages)

### C.3 ContextEngine / RFC-200 mismatch

`index.md` line 125 labels ContextEngine as "(RFC-200)" but:
- RFC-200 does not exist in `docs/specs/`
- The correct RFC is **RFC-624** (`context-engine.md`)
- `core/goal-engine.md` correctly references RFC-624

**Fix**: Update `index.md` architecture diagram to reference RFC-624.

### C.4 Archived WIKI-ARCHITECTURE.md structure mismatch

`archive/WIKI-ARCHITECTURE.md` describes a planned `modules/` directory structure (with `modules/core/`, `modules/protocols/`, `modules/backends/`, etc.) that was never implemented. The actual wiki uses `core/`, `protocols/`, `backends/`, `capabilities/` directly under `docs/wiki/`.

**Status**: Already marked as archived with a clear disclaimer. **No action needed** beyond ensuring the disclaimer is prominent.

---

## D. Documentation Gaps (codebase modules with no wiki coverage)

### D.1 Critical gaps (core infrastructure, no dedicated page)

| Codebase module | Significance | RFCs | Gap |
|-----------------|--------------|------|-----|
| `foundation/autopilot/` (engine, monitor, service) | 24/7 autonomous scheduling — the core differentiator | RFC-204, RFC-222, RFC-228, RFC-625 | **No architecture page**. Only user-facing `autonomous-mode.md` and tangential mentions in `runner.md` |
| `foundation/cron/` (service, store, extraction, models) | Scheduled task service | RFC-229 | **No wiki page at all** |
| `middleware/` (20+ files: system_prompt, policy, skill_activation, code_interpreter, edit_coalescing, llm_rate_limit, etc.) | Agent middleware pipeline | RFC-206, RFC-104 | **No dedicated page**. Mentioned in passing in `core/agent-factory.md` |
| `skills/` (registry, catalog, budget, discovery, search, workspace_sync) | Skill system — core capability | RFC-105 | **No dedicated page**. Mentioned in `capabilities/` but no architecture doc |
| `foundation/identity/` | Identity protocol | RFC-307 | **No wiki page** (protocol exists in `protocols/` dir but no wiki) |
| `foundation/persistence/` | Persistence foundation | RFC-802 | **No wiki page** |

### D.2 Partial coverage gaps (page exists but incomplete)

| Codebase module | Existing page | Gap |
|-----------------|---------------|-----|
| `foundation/sloop/` substructure (chitchat_fallbacks, clarification, cognition, intention, orchestrator, prompts, state, utils) | `core/strangeloop.md` | Covers engine concept but not the full subdirectory decomposition |
| `foundation/context/` substructure (dag_utils, ledger, planning, projection, semantic, persistence) | `core/goal-engine.md` | Covers DAG and ledger but not planning/projection subdirs in detail |
| `mcp/` internals (auth, budget, cleanup, connection, reconnect, transports) | `capabilities/mcp.md` | High-level only; no detail on auth, reconnect, budget subsystems |
| `plugin/` lifecycle (cache, context, discovery, lazy, lifecycle, loader, manifest) | `capabilities/extension-patterns.md` | Covers decorators but not the loader/lifecycle/discovery internals |
| `toolkits/` (data, datetime, deepxiv, execution, file_ops, http_requests, wizsearch, progressive) | `capabilities/tools.md` | High-level toolkit table only |
| `soothe_daemon/` internals (bootstrap, channels, display, event, health, protocol, query, runtime, services) | `api-reference/daemon-api.md` | High-level only; channels has separate `channel-plugin-guide.md` but display/health/services uncovered |

### D.3 Missing protocol pages

| Protocol in codebase | Wiki page | Gap |
|---------------------|-----------|-----|
| `protocols/core_agent.py` (CoreAgentProtocol) | None | No dedicated protocol page |
| `protocols/concurrency.py` | None | No dedicated protocol page |
| `protocols/operation_security.py` | Mentioned in `loop-protocols.md` | No dedicated page |
| `protocols/persistence.py` (AsyncPersistStore) | Covered in `vector-store-persistence.md` | OK |
| Identity protocol (RFC-307) | None | No page despite RFC existing |

---

## E. Target Content Outline

Based on the inventory and gaps above, the target wiki structure should be:

```
docs/wiki/
├── index.md                          # Hub — fix RFC-200→624, add links to all subdirs
│
├── getting-started/                  # (keep) — onboarding
│   ├── index.md                      # Hub
│   ├── Installation.md
│   ├── Quick-Start.md
│   └── Basic-Concepts.md
│
├── user-guides/                      # (keep) — daily usage
│   └── index.md                      # Hub → links to root usage files
│
├── architecture/                     # (keep) — system design
│   └── index.md                      # Overview — fix Layer N → concrete names
│
├── core/                             # (keep) — foundation modules
│   ├── index.md                      # Hub — fix Layer N
│   ├── agent-factory.md              # CoreAgent — fix Layer N
│   ├── runner.md                     # SootheRunner — fix Layer N
│   ├── strangeloop.md                # StrangeLoop — fix Layer N
│   ├── goal-engine.md                # ContextEngine — fix Layer N
│   ├── events.md                     # Event system
│   ├── resolver.md                   # Protocol resolver
│   ├── workspace.md                  # Workspace management
│   ├── autopilot.md                  # NEW — Autopilot engine (foundation/autopilot/)
│   ├── cron-service.md               # NEW — Cron service (foundation/cron/)
│   └── middleware.md                 # NEW — Middleware pipeline (middleware/)
│
├── protocols/                        # (keep) — protocol abstractions
│   ├── index.md
│   ├── durability.md
│   ├── memory.md
│   ├── planner.md
│   ├── policy.md
│   ├── vector-store-persistence.md
│   ├── context.md                    # (draft status — keep)
│   ├── execution-protocols.md
│   ├── loop-protocols.md
│   └── identity.md                   # NEW — Identity protocol (RFC-307)
│
├── backends/                         # (keep) — protocol implementations
│   ├── index.md
│   ├── durability-backends.md
│   ├── memory-backends.md
│   ├── persistence-backends.md
│   ├── policy-backends.md
│   └── vector-store-backends.md
│
├── capabilities/                     # (keep) — extensibility
│   ├── index.md
│   ├── subagents.md                  # Architecture
│   ├── tools.md
│   ├── mcp.md
│   ├── extension-patterns.md
│   └── skills.md                     # NEW — Skill system (skills/)
│
├── configuration-guide/             # (keep) — config reference
│   ├── index.md
│   ├── yaml-reference.md
│   ├── environment-variables.md
│   ├── common-patterns.md
│   └── provider-setup.md
│
├── deployment/                       # (keep) — ops
│   ├── index.md
│   ├── production-setup.md
│   ├── monitoring.md
│   ├── security.md
│   ├── scaling.md
│   └── backup-recovery.md
│
├── api-reference/                    # (keep) — package APIs
│   ├── index.md                      # Fix Layer N → concrete names
│   ├── core-api.md                   # Fix Layer N
│   ├── daemon-api.md
│   └── sdk-api.md
│
├── development/                      # (keep) — contributing
│   └── index.md
│
├── troubleshooting/                  # (keep, merge content)
│   └── index.md                      # Merge root troubleshooting.md content here
│
├── archive/                          # (keep) — historical
│   ├── index.md
│   └── WIKI-ARCHITECTURE.md
│
├── [root usage files — keep]
│   ├── cli-reference.md
│   ├── tui-guide.md
│   ├── autonomous-mode.md
│   ├── subagents.md                  # User-facing (cross-link to capabilities/)
│   ├── thread-management.md
│   ├── daemon-management.md
│   ├── multi-transport.md
│   ├── authentication.md
│   ├── channel-plugin-guide.md
│   ├── query-processing-flow.md
│   ├── faq.md
│   ├── changelog.md
│   ├── testing-guide.md
│   ├── contributing-guide.md
│   ├── howto_debug.md
│   └── clone-bandwidth-strategy.md
│
└── [DELETE — legacy duplicates]
    ├── getting-started.md            # Replaced by getting-started/index.md
    ├── configuration.md              # Replaced by configuration-guide/index.md
    ├── user_guide.md                 # Replaced by user-guides/index.md
    └── troubleshooting.md            # Merged into troubleshooting/index.md
```

### New pages to create (6)

1. **`core/autopilot.md`** — Autopilot engine architecture (`foundation/autopilot/`): engine/consensus, proposal_queue, scheduled_tasks, monitor/backoff_reasoner, service. RFCs: 204, 222, 228, 625.
2. **`core/cron-service.md`** — Cron service (`foundation/cron/`): service, store, extraction, models. RFC-229.
3. **`core/middleware.md`** — Middleware pipeline (`middleware/`): system_prompt, policy, workspace_context, skill_activation, code_interpreter, edit_coalescing, llm_rate_limit, model_call_profiler, per_turn_model, progressive_tools, role_routing, tool_*. RFC-206, RFC-104.
4. **`capabilities/skills.md`** — Skill system (`skills/`): registry, catalog, budget, discovery, search, workspace_sync, builtin_skills. RFC-105.
5. **`protocols/identity.md`** — Identity protocol. RFC-307.
6. *(Optional)* **`core/identity.md`** — Identity foundation (`foundation/identity/`) if substantial enough.

### Pages to delete (4 legacy duplicates)

- `getting-started.md`
- `configuration.md`
- `user_guide.md`
- `troubleshooting.md` (after merging content into `troubleshooting/index.md`)

### Pages to fix (terminology & references)

- All `core/*.md` and `api-reference/*.md` — replace "Layer 1/2/3" with concrete names
- `index.md` — fix RFC-200 → RFC-624; add nav links to `capabilities/`, `protocols/`, `api-reference/`, `development/`, `archive/`, `troubleshooting/`
- `contributing-guide.md` — fix Layer N references
- Fix/remove broken RFC references: RFC-200, RFC-203, RFC-215, RFC-216, RFC-300, RFC-611, RFC-800

---

## F. Content Polish Guidelines (per outline section)

Each wiki page should follow these sharp, non-verbose principles:

1. **Lead with purpose** — first line states what the module does, not what it "is".
2. **One concept per page** — no sprawling catch-all pages.
3. **Codebase-accurate** — every class/path referenced must exist in `packages/`.
4. **No "Layer N"** — use concrete names (CoreAgent, StrangeLoop, ContextEngine, SootheRunner, SootheDaemon).
5. **RFC references verified** — only link RFCs that exist in `docs/specs/`.
6. **Cross-links bidirectional** — if page A links to B, B should link back to A where relevant.
7. **No internal IG/RFC identifiers in user-visible text** — per CLAUDE.md rule 6, RFC/IG IDs allowed only in docstrings/comments, not in runtime strings. Wiki is documentation (not runtime), so RFC references in wiki prose are acceptable, but should not appear in CLI/log/error text.
8. **Tables over paragraphs** — for comparisons, taxonomies, and status tables.
9. **Code blocks with source paths** — every code example should reference its source file.
10. **Max 200 lines per page** — split if longer; use sub-pages for deep dives.

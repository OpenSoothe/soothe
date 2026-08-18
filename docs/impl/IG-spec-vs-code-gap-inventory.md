# Spec-vs-Code Gap Inventory

> Built from OKT-01 RFC inventory (81 active RFCs in `docs/specs/` + 9 archived
> in `docs/archive/specs/`) cross-referenced against `packages/{soothe,
> soothe-daemon, soothe-cli}` source.

---

## Method

1. Extracted title, status, and `##` section headings from every RFC in
   `docs/specs/` and `docs/archive/specs/` (see OKT-01).
2. For each RFC, ran targeted `rg -l "<component>"` against `packages/` (source
   only, excluding `tests/`) for the primary class/module/function named in the
   spec.
3. Cross-referenced hits against the RFC's stated `Status:` line to classify:
   - **Implemented** — RFC `Status: Implemented` and code evidence present
   - **Specified, not implemented (SNI)** — RFC describes a component with no
     code evidence (pure gap)
   - **Implemented, not documented (IND)** — code present but no RFC or RFC
     still `Draft`/`Proposed` despite shipped code (drift)
   - **Partial / drift** — code exists but RFC status or design diverges

---

## A. Implemented RFCs (spec ↔ code aligned)

These RFCs declare `Status: Implemented` and code evidence confirms the primary
component exists in `packages/`:

| RFC | Topic | Primary code location |
|-----|-------|----------------------|
| RFC-000 | System Conceptual Design | (foundational; reflected across `soothe/`) |
| RFC-001 | Core Modules Architecture | `packages/soothe/src/soothe/protocols/` |
| RFC-101 | Tool Interface & Event Naming | `packages/soothe/src/soothe/events/catalog.py` |
| RFC-102 | Secure Filesystem Path Handling | `packages/soothe/src/soothe/workspace/scoped.py`, `core_resolution.py` |
| RFC-104 | Dynamic System Context Injection | `packages/soothe/src/soothe/prompts/project_instructions.py`, `system_templates.py` |
| RFC-204 | Autopilot Mode | `packages/soothe/src/soothe/autopilot/service.py` |
| RFC-219 | Goal Completion Module | `packages/soothe/src/soothe/utils/goal_completion_stream.py` |
| RFC-222 | Autopilot Daemon Architecture | `packages/soothe/src/soothe/autopilot/service.py`, `workers/` |
| RFC-301 | Protocol Registry (Planner/Policy/Durability/VectorStore) | `packages/soothe/src/soothe/protocols/`, `runner/resolver/` |
| RFC-401 | Event Processing & Filtering | `packages/soothe/src/soothe/events/`, `visibility.py` |
| RFC-500 | CLI TUI Architecture | `packages/soothe-cli/src/soothe_cli/tui/` |
| RFC-600 | Plugin Extension System | (wired through `soothe-cli` + `soothe-daemon/channels/registry.py`) |
| RFC-601 | Built-in Plugin Agents | `packages/soothe/src/soothe/subagents/veritas/` |
| RFC-604 | Plan Phase Robustness (Three-Layer Defense) | `packages/soothe/src/soothe/sloop/cognition/` |
| RFC-625 | AutopilotMonitor & ContextEngine Unification | `packages/soothe/src/soothe/autopilot/monitor/`, `context/` |
| RFC-628 | Cognition Step Card & SubAgent Card Display | `packages/soothe-cli/src/soothe_cli/tui/widgets/` |
| RFC-900 | RFC Deprecation / Reclassification Scheme | (meta; docs/specs reorg) |

---

## B. Specified but Not Implemented (SNI) — pure gaps

RFCs that name a component/class/middleware that has **no corresponding code**
in `packages/`. These are the highest-priority gaps.

| RFC | Specified component | Evidence of absence |
|-----|---------------------|---------------------|
| **RFC-412** | `MCPRegistry`, `MCPActivationMiddleware`, `ProgressiveMCPRegistry`, `search_mcp_tools`, `MultiServerMCPClient` import | Only `MCPRegistry` string referenced in 2 files; no `soothe.mcp` package exists; `langchain_mcp_adapters` declared but never imported in source. RFC itself states "MCP is entirely non-functional" (§Motivation). |
| **RFC-412 (rev 2026-07-11)** | `ProgressiveMCPRegistry`, `MCPActivationMiddleware`, `search_mcp_tools` | Zero hits for these symbols in `packages/`. Progressive MCP loading is "listing-only" per RFC. |
| **RFC-301** | `ProtocolRegistry` (centralized registry class) | Zero code hits for `ProtocolRegistry`/`protocol_registry`. Protocols are wired ad-hoc in `protocols/__init__.py` and `runner/resolver/`, not via a registry abstraction. |
| **RFC-302** | `ContextRetrievalModule` (self-contained retrieval module on `ContextProtocol`) | Zero hits for `ContextRetrievalModule`. `ContextProtocol` exists conceptually but the retrieval module is absent. |
| **RFC-223** | Checkpoint forking (`CheckpointFork`, `thread_fork`) | Zero hits for `checkpoint_fork`/`thread_fork`/`ThreadFork`. Fork strategy in RFC is unimplemented. |
| **RFC-225** | `LoopContinuity`, `GoalRecord` enrichment | Zero hits for `loop_continuity`/`LoopContinuity`/`GoalRecord`. |
| **RFC-226** | `ContinuationAware` plan_assess, post-execute fast exit | Zero hits for `continuation_aware`/`ContinuationAware`. |
| **RFC-227** | `PriorProgressDigest`, prior-progress digest | Zero hits for `prior_progress_digest`/`PriorProgressDigest`. |
| **RFC-221** | `SubprocessRunner`, `RayRunner` named class, `ThreadPoolRunner` | `ray_runner.py`/`ray_actor.py` exist but `SubprocessRunner`/`ThreadPoolRunner` classes absent. Loop runner protocol partially implemented. |
| **RFC-633** | `PlanArtifact` artifact model, human review flow | `plan_artifact` appears as a string literal in sidecar stages but no `PlanArtifact` class or human-review workflow exists. |
| **RFC-632** | `LoopScopedRouter` profile override | Only `router_profile_override`/`router_profile_selector` TUI widget; no daemon-side loop-scoped override enforcement class. |
| **RFC-631** | `GoalDisplaySnapshot` server-owned write path | Display store files exist but write-path (§8) for goal-bound snapshots is partial. |
| **RFC-627** | Unified LLM Utilities module | No `soothe.llm` or unified utilities module; LLM calls scattered. |
| **RFC-621** | Workspace host convention for containers | Zero hits for `workspace_host`/`WorkspaceHost`. |
| **RFC-629** | Client Library Appkit (multi-language) | Client libs exist in `client/{go,python,rust,typescript}` submodules but Appkit tier API not standardized. |
| **RFC-504** | `soothe loop tree`, `soothe loop prune`, `soothe loop delete` commands | `loop_cmd.py` exists with `list`/`describe`; `tree`/`prune`/`delete` commands not implemented. |
| **RFC-502** | Unified Presentation Engine (daemon-side `PresentationEngine`) | `presentation/engine.py` exists only in CLI; daemon-side unified engine absent. |
| **RFC-452** | Unified Thread Management (unified `thread` command + multi-thread architecture) | No `UnifiedThreadManagement`/`unified_thread` classes; thread mgmt split across `runner/_thread_manager.py` and daemon `runtime/thread_state.py`. |
| **RFC-901** | `OperationSecurityProtocol` | Zero hits for `OperationSecurity`/`OperationSecurityProtocol`. `security/` package contains only `daemon_kill_guards.py`. |
| **RFC-902** | Same-File Edit Concurrency / Optimization | Zero hits for `SameFileEdit`/`same_file_edit`/`edit_lock`. |
| **RFC-801** | SQLite Backend Specification (formal backend contract) | SQLite backends exist (`store_sqlite.py`, `sqlite_backend.py`) but not as the formal `SQLiteBackend` class hierarchy RFC describes. |
| **RFC-803** | StrangeLoop Checkpoint Backend (unified persistence manager API) | Backend classes exist (`archive_backend`, `sqlite_backend`, `postgres_backend`) but unified `PersistenceManager` API and async write pipeline (Phase 6) incomplete. |
| **RFC-413** | Server-owned Display Card Ledger (full phased migration) | `LoopCardManager` exists but `DisplayCardLedger` class name absent; structural live path via `soothe.card.*` shipped per IG-655 but full ledger migration incomplete. |
| **RFC-403** | Unified Event Naming (complete migration map) | Event catalog exists but migration from old names per RFC §8 migration map not fully applied. |
| **RFC-450** | Unified Daemon Communication Protocol (versioning, capability negotiation) | Wire protocol exists but capability negotiation (§8) and versioning (§8) not implemented. |
| **RFC-503** | Loop-First User Experience (full detachment, client session mgmt) | Partial — `loop_cmd.py` and headless exist but detachment behavior and session management incomplete. |
| **RFC-614** | Unified Daemon→Client Streaming Messaging | `UnifiedStreaming` absent as a named framework; streaming is ad-hoc. |
| **RFC-616** | Scenario-Driven Goal Completion Synthesis | `synthesis.py` exists in `sloop/engine/` but scenario classifier (`scenario_classifier.py`) is present; full scenario-driven synthesis path partial. |
| **RFC-618** | Plan Subagent with Explore Delegation | `subagent_catalog.py` lists `planner` as intake-only wired; explore delegation (RFC-618) partially superseded by RFC-633. Explore agent itself absent. |
| **RFC-619** | Deep Research Subagent (Phase 2 `academic_research`) | `deep_research` listed in `subagent_catalog.py` INTAKE_ONLY set; Phase 2 `academic_research` not implemented. |
| **RFC-622** | CoreAgent Clarification Relay + Veritas subagent TUI toggle | Relay wired (`sloop/clarification/`, `await_user`, CE park on hard-defer per IG-749). Remaining gap: full CLI `goal answer` UX polish. |
| **RFC-623** | Veritas Auto-Mode Robustness | DeferKind + interactive fallback wired; empty-answer / wire `defer_kind` covered in IG-749. |
| **RFC-630** | Start-Phase LLM Intake and Branch Routing | `sloop/intention/` two-pass classifier exists; branch routing (§10) wiring partial. |
| **RFC-603** | Reasoning Quality & Progressive Actions | `sloop/cognition/` has phase/planner; progressive actions spec (RFC-603) not fully aligned. |
| **RFC-606** | DeepAgents CLI TUI Migration | Migration largely done (CLI/TUI in `soothe-cli`); remaining phases per RFC §Implementation Phases incomplete. |
| **RFC-607** | Progressive Display Refinements Post-Migration | Partial; display refinements ongoing. |
| **RFC-610** | SDK Module Structure Refactoring | `soothe_sdk` is a PyPI dependency (submodule at `packages/soothe-sdk`); refactoring spec not applied in this repo. |
| **RFC-802** | Persistence Architecture Refactor (unified persistence) | `persistence/unified.py` exists; full refactor (PostgreSQL database schema, config migration) partial. |
| **RFC-213** | StrangeLoop Reasoning Quality & Robustness (two-phase plan architecture) | Two-phase plan exists in `sloop/cognition/`; reasoning quality progressive actions historical section superseded. |
| **RFC-214** | Volatility-Tiered Prompt Architecture & Unified Message Ledger | `ledger.py` exists; volatility-tiered prompt architecture (target design §) partially implemented. |
| **RFC-217** | Goal Context Management for StrangeLoop | `GoalContextManager` referenced in `sloop/engine/` but RFC `Status: Draft`; implementation status section says "completed" but class not fully unified. |
| **RFC-218** | StrangeLoop Checkpoint Tree Architecture | Checkpoint manager + backends exist; checkpoint tree pruning strategy (§) not implemented. |
| **RFC-220** | LangGraph Agent Loop Orchestrator | `sloop/orchestrator/` exists with builder/runner/state; normative identity/isolation rules (§) and bounded evidence gathering partial. |
| **RFC-224** | Automatic Context Window Management | `context_window_manager.py` exists; step thread handling (§) and event definition partial. |
| **RFC-228** | Autopilot Job IPC Commands | `protocol/autopilot_commands.py` exists; `Status: Proposed` — some commands shipped, full command set incomplete. |
| **RFC-229** | Cron Service for Autopilot | `cron/service.py` + `cron_cmd.py` exist; `Status: Proposed` — TUI `/cron` and full CLI integration partial. |
| **RFC-230** | Job Maturity Assessment | `verify/job_maturity.py` + `JobMaturityAssessor` exist; rail exclusivity and IPC observation points partial. |
| **RFC-231** | LoopRail and Rail Exec | `rails/` + `autopilot/rail/` exist; verb body modes (M3 `do:` recipes) and fan-out contract partial. |
| **RFC-232** | Flat WavePlan Wire Ingest | `autopilot/rail/wave_plan.py` exists; semi-structured ingest and architecture gate partial. |
| **RFC-103** | Thread-Aware Workspace | `workspace/scoped.py`, `loop_workspace.py` exist; `Status: Draft` — thread-aware workspace edge cases and security model partial. |
| **RFC-105** | Progressive Skill Loading | `skillify/` package in daemon; `Status: Draft` — progressive disclosure middleware and cost model partial. |
| **RFC-201** | StrangeLoop Plan-Execute Loop | `sloop/engine/strange_loop.py` exists; `Status: Implemented (Partially Superseded)` — superseded by RFC-220/RFC-624. |
| **RFC-206** | Hierarchical Prompt Architecture | `prompts/` package exists; `Status: Draft` — ambiguity handling and module design partial. |
| **RFC-207** | StrangeLoop Thread Lifecycle & Goal Context | Thread manager exists; `Status: Draft` — thread health monitoring and knowledge transfer partial. |
| **RFC-211** | Layer 2 Tool Result Optimization | `sloop/engine/tool_call_*` modules exist; `Status: Draft` — responsibility shift architecture partial. |
| **RFC-501** | Display & Verbosity | `display_policy.py` in CLI; `Status: Draft` — full display architecture and migration mapping partial. |
| **RFC-454** | Slash Command Architecture | `tui/commands/slash_commands.py` exists; `Status: Draft` — daemon implementation and removed code sections partial. |
| **RFC-307** | IdentityProtocol Architecture | `identity/` package exists; `Status: Draft` — middleware integration and CLI commands partial. |
| **RFC-305** | PolicyProtocol Architecture | `ConfigDrivenPolicy` referenced in tests only; `Status: Draft` — permission categories and config-driven implementation partial. |
| **RFC-306** | DurabilityProtocol Architecture | `DurabilityProtocol` referenced in resolver/config; `Status: Draft` — persistence directory layout and integration points partial. |
| **RFC-304** | PlannerProtocol Architecture | `LLMPlanner` exists in `protocols/loop_planner.py`; `Status: Draft` — design principles and config partial. |
| **RFC-303** | MemoryProtocol Architecture | `MemoryProtocol`/`loop_working_memory.py` exist; `Status: Draft` — memory integration flow and implementations partial. |

---

## C. Implemented but Not Documented (IND) — code without matching RFC

Code modules in `packages/` that have no dedicated RFC or are documented only
in IGs (implementation guides) rather than specs:

| Code module | Notes |
|-------------|-------|
| `packages/soothe/src/soothe/diagnose/` (api, host, models) | Host diagnostics API — no dedicated RFC. |
| `packages/soothe/src/soothe/utils/observability/langfuse/` | Langfuse observability integration — no RFC. |
| `packages/soothe/src/soothe/utils/prompt_clock.py` | Prompt timing utility — no RFC. |
| `packages/soothe/src/soothe/security/daemon_kill_guards.py` | Daemon kill guard — no RFC (RFC-901 covers operation security but doesn't name this). |
| `packages/soothe-daemon/src/soothe_daemon/health/` | Health check system — referenced in RFC-412 but no dedicated RFC. |
| `packages/soothe-daemon/src/soothe_daemon/notify/` | Notification sinks (email, feishu, webhook) — no dedicated RFC. |
| `packages/soothe-daemon/src/soothe_daemon/skillify/` | Skill warehouse/indexer/retriever — referenced in RFC-105 but no dedicated RFC for the daemon-side skillify package. |
| `packages/soothe-daemon/src/soothe_daemon/query/` | Query engine, stream delivery, turn boundary — no dedicated RFC. |
| `packages/soothe-daemon/src/soothe_daemon/runtime/loop_broadcast_budget.py` | Loop broadcast budget — no RFC. |
| `packages/soothe-daemon/src/soothe_daemon/runtime/loop_gc.py` | Loop garbage collection — no RFC. |
| `packages/soothe-daemon/src/soothe_daemon/runtime/loop_reconcile.py` | Loop reconciliation — no RFC. |
| `packages/soothe-daemon/src/soothe_daemon/services/memory_profiler.py` | Memory profiling service — no RFC. |
| `packages/soothe-daemon/src/soothe_daemon/services/image_understanding.py` | Image understanding service — no RFC. |
| `packages/soothe-daemon/src/soothe_daemon/services/intent_hint_turn.py` | Intent hint per turn — no RFC. |
| `packages/soothe-cli/src/soothe_cli/tui/unicode_security.py` | Unicode security checks — no RFC. |
| `packages/soothe-cli/src/soothe_cli/tui/update_check.py` | Update check — no RFC. |
| `packages/soothe-cli/src/soothe_cli/tui/mermaid_render.py` | Mermaid rendering — no RFC. |
| `packages/soothe-cli/src/soothe_cli/tui/file_change_notify.py` | File change notification — no RFC. |

---

## D. Drift / Status Mismatches

RFCs where the `Status:` line doesn't match code reality:

| RFC | Declared status | Actual code state |
|-----|-----------------|-------------------|
| RFC-217 | `Status: Draft` (body says "completed") | `GoalContextManager` exists and is wired into `sloop/engine/`. Status should be `Implemented`. |
| RFC-222 | `Status: Implemented` | Accurate — `AutopilotService` fully shipped. |
| RFC-625 | `Status: Implemented` | Accurate — monitor + CE unification shipped. |
| RFC-628 | `Status: Implemented (Parts I–III)` | Accurate — step card display shipped. |
| RFC-624 | `Status: Draft` (body shows Phases 1, 3a–3d, 4 Stage 1 all "Done") | Code: `context/engine.py`, `GoalNode`, `StepNode`, `ContextBundle`, `LedgerManager`, `ProjectionEngine`, `SemanticLoader` all present. Status should be `Implemented` (Phase 4 Stage 2 in progress). |
| RFC-626 | `Status: Draft` | `ExecutionState` only in daemon `protocol/schemas.py`; `LoopState` still exists in `sloop/cognition/` and `config/models.py`. LoopState elimination **not complete** — status accurately `Draft`. |
| RFC-201 | `Status: Implemented (Partially Superseded)` | Accurate — superseded by RFC-220/624 but still in use. |
| RFC-413 | `Status: Draft (Phases 1–4 shipped)` | `LoopCardManager` exists but `DisplayCardLedger` class absent. Status comment is more optimistic than code. |
| RFC-228 | `Status: Proposed` | `protocol/autopilot_commands.py` shipped; should be `Draft` or `Implemented (partial)`. |
| RFC-229 | `Status: Proposed` | `cron/service.py` + CLI `cron_cmd.py` shipped; should be `Draft` or `Implemented (partial)`. |
| RFC-302 | `Status: Draft` | `ContextProtocol` concept implemented via `context/engine.py` but `ContextRetrievalModule` absent. Status accurate. |
| RFC-105 | `Status: Draft` | `skillify/` package shipped in daemon; progressive disclosure partial. Status should note partial implementation. |

---

## E. Priority Summary

### High-priority gaps (spec'd, zero code, blocks user-facing features)

1. **RFC-412 MCP Management** — entire MCP subsystem non-functional. No
   `soothe.mcp` package, no `MultiServerMCPClient` import, no
   `MCPActivationMiddleware`. This is the largest single gap.
2. **RFC-504 Loop Management Commands** — `loop tree`/`prune`/`delete` not
   implemented (only `list`/`describe` exist).
3. **RFC-901 OperationSecurityProtocol** — no security protocol class; `security/`
   package has only kill guards.
4. **RFC-902 Same-File Edit Optimization** — no implementation.
5. **RFC-627 Unified LLM Utilities** — no unified module; LLM calls scattered.
6. **RFC-621 Workspace Host Convention** — no implementation (blocks container
   deployments).

### Medium-priority gaps (partial implementation, RFC still Draft)

7. **RFC-223 Checkpoint Forking** — fork strategy unimplemented.
8. **RFC-225/226/227 Loop Continuity & Plan-Assess Digests** — zero code.
9. **RFC-633 PlanArtifact & Human Review** — no artifact class or review flow.
10. **RFC-632 Loop-Scoped Router Override** — daemon-side enforcement absent.
11. **RFC-452 Unified Thread Management** — no unified class.
12. **RFC-614 Unified Streaming Messaging** — no named framework.
13. **RFC-413 Display Card Ledger** — `DisplayCardLedger` class absent despite
    partial shipping.
14. **RFC-301 ProtocolRegistry** — centralized registry absent (protocols wired
    ad-hoc).
15. **RFC-302 ContextRetrievalModule** — retrieval module absent.

### Documentation debt (code without RFC)

16. **diagnose/, health/, notify/, query/, skillify/** packages — no dedicated
    RFCs.
17. **Langfuse observability** — no RFC.
18. **Loop GC / reconcile / broadcast budget** — no RFC.

### Status drift (RFC status doesn't match code)

19. **RFC-217** should be `Implemented` (body says completed, code exists).
20. **RFC-624** should be `Implemented` (Phases 1–4 Stage 1 done per body).
21. **RFC-228/229** should be `Draft` or `Implemented (partial)` (code shipped).
22. **RFC-413** status comment overstates implementation vs. code reality.

---

## F. Archived RFCs (historical only — `docs/archive/specs/`)

These 9 RFCs are superseded/archived and not counted as active gaps:

- RFC-200 (Autonomous Goal Management → superseded by RFC-222)
- RFC-203 (StrangeLoop State & Memory → superseded by RFC-626)
- RFC-216 (StrangeLoop Multi-Thread Lifecycle → superseded by RFC-207/452)
- RFC-300 (Context & Memory Protocols → superseded by RFC-302/303)
- RFC-411 (Event Stream Replay → superseded by RFC-401/403)
- RFC-505 (Soothe Desktop Client → archived)
- RFC-605 (Explore Subagent Parallel Spawning → archived)
- RFC-613 (Explore Agent LLM-Orchestrated Search → archived)
- RFC-700 (Desktop App Product Redesign → archived)

---

*Inventory complete. 81 active RFCs scanned against `packages/{soothe,
soothe-daemon, soothe-cli}` source. 17 fully implemented, 55 partial/unimplemented
gaps, 18 code-without-RFC modules, 6 status drift items.*

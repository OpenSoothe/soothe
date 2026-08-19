# RFC History

This document tracks the chronological evolution of RFCs in the Soothe project.

**Last Updated**: 2026-08-19
**Total RFCs**: 92 (83 active + 9 archived)

> Summary statistics (by status and kind) live in [rfc-index.md](rfc-index.md).

## Recent Changes

### 2026-08-19

- **RFC-904 - Sloop Recursive Step Decomposition**
  - Status: Proposed
  - Kind: Architecture Design
  - Revises: RFC-220 plan/eval spine; RFC-201 upfront plan waves; RFC-213
    assess+generate; RFC-624 StepDAG; RFC-630 Pass 2 (pass1 retained)
  - Design draft: `docs/archive/drafts/2026-08-19-sloop-recursive-decomposition-design.md`
  - Companion header updates: RFC-201, RFC-213, RFC-220, RFC-624, RFC-630,
    RFC-903
  - Design draft moved to `docs/archive/drafts/` after formalization
  - Related RFCs remain **active (partially superseded)** — not archived
    (RFC-900: only fully Deprecated RFCs archive after 90 days)

### 2026-08-18

- **RFC-903 - Sloop Graph Topology and Node Lifecycle**
  - Status: Proposed
  - Kind: Architecture Design
  - Revises: RFC-220 §Loop Graph Topology, §State and Schemas
  - Introduces 5-method `LoopNode` lifecycle (`pre`/`project`/`prompt`/
    `process`/`post`) and typed `RouteDecision`; folds `validate_plan` into
    `commit_plan` and `begin_iteration` into `check_limits` (14→12 nodes,
    11→8 routers). Wire-stable phases preserved.
  - Implementation guide: `docs/impl/IG-sloop-generalized-node-topology.md`

### 2026-08-14

- **RFC Methodology Guide** published at `docs/rfc-methodology-guide.md`.
  Synthesizes methodology from RFC-900, the RFC template, `rfc-namings.md`,
  `rfc-index.md`, and IG-744 into a single reusable playbook. Covers lifecycle,
  authoring, kinds, number segments, terminology, index hygiene, dependency
  tracking, deprecation/archival, path-restructure drift, gap inventory, gap
  triage scoring, and series consolidation triggers.

### 2026-08-08

- **RFC-231 §8–§9** revised: streaming slice catalog (no wave/stage CE
  barrier); spawn-ready makers as slice deps; host worktree merge into
  `job/<id>`; per-maker review/QA replaces batch integrate. IG-732 (Draft).
- **RFC-232** amended: optional per-slice `depends_on`; catalog SoT;
  `max_slices` preferred over nested wave rounds.
- **RFC-230** §8: `slices_ready_to_spawn`; deprecate `ready_for_next_wave`
  as spawn barrier.
- **RFC-231 §10**: catalog selection cascade adds structured light-LLM
  auto-pick when submit omits `rail_id` (confidence / abstain / fallback).
  IG-728.
- **RFC-228** `job_create`: optional `rail_id`; processing steps reference
  RFC-231 §10 resolution before rail bind / `job_start`.

### 2026-08-07

- **RFC-232** drafted: Flat WavePlan Wire Ingest (semi-structured markdown+JSON
  allowed; canonical plan is flat leaf `wave_slices` / `slices` only; nested
  waves/slices rejected with no clever-flatten; SoT remains `RailJobState`;
  amends RFC-231 §9).
- **RFC-231** drafted: LoopRail and Rail Exec (composable verb bodies).
  Normative Autopilot workflow patterns; Rail Exec (L0 CE primitives / L1
  catalog recipes / L2 flow) so custom rails match builtin power via YAML
  `verbs:` without `rail_id` forks.

### 2026-08-05

- **RFC-230** drafted: Job Maturity Assessment for Autopilot Rails (host
  assessor, `acceptance_met`, production `dag_idle`, rail-exclusive spawn).
  IG-692. RFC-228 `verification_rules` lifecycle points at RFC-230.

### 2026-07-27

- **RFC-413** Phase 4 complete (IG-655): append-oriented DisplayCardStore
  ledger, live `soothe.card.*` via `event`/`custom`, TUI prefers daemon
  projection for structural cards; inline tool rows remain live-only.

## Chronological Timeline

### Major Changes - 2026-08-08

**RFC-231 §8–§9 / RFC-232 / RFC-230**: Streaming Slice DAG + Host Worktrees

- Wave/stage is not a CE execution boundary; Autopilot grows the DAG via
  spawn-ready + optional WavePlan `depends_on`
- Host merge makers → `job/<id>`; land on main only at job complete
- Per-maker review/QA; batch `spawn_integrate` deprecated for greenfield merge

**RFC-231 §10 / RFC-228**: LLM LoopRail Auto-Pick

- Submit without `rail_id`: structured LLM over merged catalog → confidence
  gate → `.rail-default` / config / no rail
- Prompt: stable system + dynamic candidate cards (external rails first-class)
- **IG-728** implements; `job_create` documents optional `rail_id`

### Major Changes - 2026-08-07

**RFC-232**: Flat WavePlan Wire Ingest (Semi-Structured, No Nesting)

- Completion wire MAY be markdown + flat JSON; SoT remains `RailJobState.wave_slices`
- Nested waves/slices forbidden (reject, do not flatten)
- Architecture gate send-backs must include validation/nesting detail
- Amends RFC-231 §9 fan-out contract

**RFC-231**: LoopRail and Rail Exec (Composable Verb Bodies)

- Normative LoopRail: event → guard → catalog verb → CE DAG
- Rail Exec: verb bodies as L0 primitive sequences and/or NL briefs/intent
- Migration phases M1–M4 (recipe extract → overrides → multi-step → intent expand)
- §9 later amended by RFC-232 (flat WavePlan wire)

### Major Changes - 2026-08-05

**RFC-230**: Job Maturity Assessment for Autopilot Rails

- Host-side `JobMaturityAssessor` (Autopilot + CE) latches `acceptance_met`
- Production `dag_idle` for rail job completion; verifier must not spawn on
  rail-bound jobs; IG-692

**RFC-204 amendment + IG-693**: Rail-bound consensus send-back exhaustion

- Send-back budget is **per subgoal**, not the job root
- Rail-bound subgoals: exhaustion → **`failed`** + LoopRail `goal_failed`
  (not silent suspend); greenfield recovers via `retry_maker`
- Autopilot must not hard-accept via git/pytest for rail jobs

---

### Major Changes - 2026-07-24

**SQLite process-scoped Runtime + layout hard cut** (RFC-801 / RFC-802 / RFC-803)

- `SqliteStoreRuntime` / `SqliteRuntimeRegistry`: one Runtime per DB file; leased readers; `BEGIN IMMEDIATE` writes; uniform WAL + busy_timeout
- All SQLite purpose files under `$SOOTHE_DATA_DIR/databases/{purpose}.db` (`checkpoints`, `context`, `display`, `cron`, `identity`, `metadata`, `persist`, `vectors`, optional `memory`)
- Hard cut: no migration or legacy path shims
- RFC-803: SQLite checkpoint flush is process-scoped (parity with Postgres `LoopPersistenceWriter`)

---

### Major Changes - 2026-07-19

**Unified persistence backend** (AGENTS.md §10)

- `persistence.default_backend` is one mode for the whole process (postgresql XOR sqlite); mixing is forbidden
- Display cards, cron jobs, and identity follow the same backend
- Durability overrides that disagree with `default_backend` raise at daemon configure time

**RFC-413 amendment**: Display card ledger follows `persistence.default_backend`

- PostgreSQL → `soothe_metadata` (same tables as SQLite `display.db`)
- SQLite `display.db` remains the default for local/sqlite backends

---

### Major Changes - 2026-06-30

**RFC-629**: Client Library — Core Upgrade and Appkit Architecture (Go + TypeScript)

- Cross-language client architecture: Layer 0 (core `Client` transport/lifecycle), Layer 1 (`appkit`: `ConnectionPool`/`QueryGate`/`TurnRunner`/`EventClassifier`/`SSEBroadcaster`/`LoopSessionStore`), Layer 2 (product code)
- Layer 0 folds drop detection, `Reconnect`/`ReattachAndProbe`, readiness retry, and concurrent `(type, id)` multiplexing into core `Client`
- Layer 1 extracts reusable mechanics (pool, single-flight query gate, timeout turn loop, event→deliverable classification, SSE fan-out, persistence seam)
- Language-specific adaptations (Go channels/`context.Context` vs TypeScript `EventEmitter`/`AsyncGenerator`/`AbortSignal`); contract identical across both
- Extends RFC-450, RFC-610; implemented by IG-527 (Go), IG-528 (TypeScript)

**RFC-630**: Start-Phase LLM Intake and Branch Routing

- Replaces `IntentClassifier` + `_is_likely_agentic` heuristic bypass with a single 4-class intake LLM (`quiz | trivial | simple | complex`)
- Intake LLM runs `asyncio.gather`-ed with pre-graph IO cluster (checkpoint load, ContextEngine load, file reads, git status) so the round-trip is hidden
- `route_by_intent` edge: `quiz`→END, fresh `trivial`→synthetic 1-step plan, fresh `simple`→lightweight `plan_generate`, continuation `trivial/simple`→`plan_assess` discriminator, `complex`→full spine
- Continuation is structural (checkpoint), not an LLM label; clarification is emergent from the planner
- Feature flag `config.agent.loop.intake.branch_routing.enabled` (default `false`)
- Extends RFC-225, RFC-220; supersedes IG-518 heuristic-bypass path

---

### Major Changes - 2026-06-26

**RFC-628**: Cognition Step Card Display — canonical TUI step card spec

- Extracted `cognition_step_activity.py` (classification, activity tree, status lines)
- Unified `_sync_step_card_surface()` refresh pipeline
- Footer/branch Running lines show total tool counts (main + subgraph + orphan)
- Removed obsolete auto-collapse; manual click-to-collapse retained
- Extends RFC-500 § Event Rendering, RFC-501 § 7.3

---

### Major Changes - 2026-06-19

**RFC-900 Implementation**: Formalized deprecation and reclassification scheme

1. **Archived RFCs** (6):
   - RFC-200: Autonomous Goal Management Loop → Superseded by RFC-222, RFC-625
   - RFC-203: StrangeLoop State & Memory Architecture → Superseded by RFC-626
   - RFC-216: StrangeLoop Multi-Thread Infinite Lifecycle → Superseded by RFC-207
   - RFC-300: Context and Memory Architecture Design → Superseded by RFC-302, RFC-303
   - RFC-411: Event Stream Replay & History Reconstruction → Superseded by RFC-413
   - RFC-605: Explore Subagent and Parallel Spawning → Superseded by RFC-613

2. **Series Reclassification** (per RFC-900 series semantics):
   - **3xx Protocol Specifications**: RFC-302, RFC-303, RFC-304, RFC-305, RFC-306 (moved from 4xx)
   - **8xx Persistence & Backends**: RFC-801 (moved from 6xx)
   - **9xx Security & Policy**: RFC-901 (moved from 6xx)

3. **Process Documentation**:
   - Added RFC-900: Deprecation and Reclassification Scheme
   - Updated ../archive/specs/README.md with archival policy
   - Established 90-day deprecation → archival timeline

---

### 2026-06

- **2026-06-30**: RFC-630 - Start-Phase LLM Intake and Branch Routing
- **2026-06-30**: RFC-629 - Client Library Core Upgrade and Appkit Architecture (Go + TypeScript)
- **2026-06-26**: RFC-628 - Cognition Step Card Display
  - Status: Implemented
  - Kind: Implementation Interface Design
  - Depends on: RFC-500, RFC-501, RFC-607
  - Extends: RFC-500 (step card rendering), RFC-501 (TUI step card body)
  - Implemented by: IG-512, IG-513, IG-514, IG-515

- **2026-06-25**: RFC-307 - IdentityProtocol: AKSK Authentication & JWT Token Management
  - Status: Draft
  - Kind: Architecture Design
  - Dependencies: RFC-000, RFC-001, RFC-305
  - Authors: Platonic brainstorming session

- **2026-06-19**: RFC-200 - Autonomous Goal Management Loop
  - Status: Archived
  - Kind: Architecture Design
  - Superseded By: RFC-222, RFC-625
  - Archive Reason: Control flow replaced by autopilot push model, GoalEngine deleted

- **2026-06-19**: RFC-203 - StrangeLoop State & Memory Architecture
  - Status: Archived
  - Kind: Architecture Design / Impl Interface
  - Superseded By: RFC-626
  - Archive Reason: LoopState eliminated, consolidated into ExecutionState

- **2026-06-19**: RFC-300 - Context and Memory Architecture Design
  - Status: Archived
  - Kind: Architecture Design
  - Superseded By: RFC-302, RFC-303
  - Archive Reason: Combined spec split into separate ContextProtocol and MemoryProtocol specs

- **2026-06-19**: RFC-411 - Event Stream Replay & History Reconstruction
  - Status: Archived
  - Kind: Architecture Design
  - Superseded By: RFC-413
  - Archive Reason: Event stream replay replaced by server-owned display card ledger

- **2026-06-19**: RFC-605 - Explore Subagent and Parallel Spawning
  - Status: Archived
  - Kind: Architecture Design
  - Superseded By: RFC-613
  - Archive Reason: Fixed wave-based search replaced by LLM-orchestrated iterative search

- **2026-06-19**: RFC-216 - StrangeLoop Multi-Thread Infinite Lifecycle
  - Status: Archived
  - Kind: Architecture Design
  - Superseded By: RFC-207
  - Archive Reason: Thread lifecycle and automatic switching incorporated into RFC-207

- **2026-06-19**: RFC-900 - RFC Deprecation List and Number Segment Reclassification Scheme
  - Status: Proposed
  - Kind: Process Specification
  - Authors: Soothe Team

- **2026-06-19**: Series Reclassification
  - RFC-302, RFC-303, RFC-304, RFC-305, RFC-306: Reclassified from 4xx to 3xx (Protocol Specifications)
  - RFC-801: Reclassified from 6xx to 8xx (Persistence & Backends)
  - RFC-901: Reclassified from 6xx to 9xx (Security & Policy)

- **2026-06-16**: RFC-626 - Entity Model and State Management Consolidation
  - Status: Draft
  - Kind: Architecture Design
  - Authors: Soothe Team

- **2026-06-15**: RFC-625 - AutopilotMonitor as ContextEngine Monitor Submodule
  - Status: Implemented
  - Kind: Architecture Design
  - Authors: Soothe Team

- **2026-06-12**: RFC-624 - Context Engine — Unified Context Management
  - Status: Draft
  - Kind: Architecture Design
  - Authors: Soothe Team

- **2026-06-04**: RFC-803 - StrangeLoop Checkpoint Backend Architecture
  - Status: Draft
  - Kind: Architecture Design

- **2026-06-04**: RFC-228 - Autopilot Job IPC Commands for Desktop Integration
  - Status: Proposed
  - Kind: Protocol Specification

- **2026-06-04**: RFC-413 - Server-Owned Display Card Ledger
  - Status: Draft
  - Kind: Architecture Design
  - Authors: xiaming (with Claude)

- **2026-06-04**: RFC-505 - Soothe Desktop Client Architecture
  - Status: Archived (2026-08-06 — desktop submodule removed; see `docs/archive/notes/2026-08-06-desktop-app-removed.md`)
  - Kind: Architecture Design

- **2026-06-04**: RFC-700 - Desktop App Product Redesign
  - Status: Archived (2026-08-06 — desktop submodule removed)
  - Kind: Product Specification

- **2026-06-04**: RFC-413 supersedes RFC-411

- **2026-06-03**: RFC-623 - Veritas Auto-Mode Robustness
  - Status: Draft
  - Kind: Implementation Interface Design
  - Authors: Soothe Team

- **2026-06-02**: RFC-621 - Workspace Host Convention: Path Mapping for Containerized Daemon
  - Status: Draft
  - Kind: Architecture Design
  - Authors: Platonic Coding Workflow

- **2026-06-02**: RFC-622 - CoreAgent Clarification Relay
  - Status: Draft
  - Kind: Architecture Design
  - Authors: Soothe Team

- **2026-06-01**: RFC-227 - Plan-Assess Prior-Progress Digest
  - Status: Draft
  - Kind: Architecture Design
  - Authors: xiaming

### 2026-05

- **2026-05-29**: RFC-105 - Progressive Skill Loading
  - Status: Draft
  - Kind: Implementation Interface Design
  - Authors: Platonic brainstorming session

- **2026-05-29**: RFC-225 - Loop Continuity and Goal Record Enrichment
  - Status: Draft
  - Kind: Architecture Design
  - Authors: xiaming

- **2026-05-29**: RFC-226 - Continuation-Aware plan_assess and Post-Execute Fast Exit
  - Status: Draft
  - Kind: Architecture Design
  - Authors: xiaming

- **2026-05-29**: RFC-412 - MCP Management
  - Status: Draft
  - Kind: Implementation Interface Design
  - Authors: Platonic brainstorming session

- **2026-05-29**: RFC-620 - Unified Channel Architecture for Extensible Communication Endpoints
  - Status: Draft
  - Kind: Architecture Design

- **2026-05-28**: RFC-200 - Autonomous Goal Management Loop
  - Status: Implemented → Archived (2026-06-19)
  - Kind: Architecture Design
  - Note: Superseded by RFC-222 (control flow) and RFC-625 (GoalEngine deletion)

- **2026-05-28**: RFC-204 - Autopilot Mode (Layer 3 Extension)
  - Status: Implemented
  - Kind: Architecture Design

- **2026-05-27**: RFC-222 - Autopilot and Goal Engine Architecture (Daemon-Owned)
  - Status: Draft
  - Kind: Architecture Design

- **2026-05-27**: RFC-223 - Thread Inheritance with LangGraph Checkpoint Forking
  - Status: Draft
  - Kind: Architecture Design

- **2026-05-27**: RFC-224 - Automatic Context Window Management
  - Status: Draft
  - Kind: Architecture Design

- **2026-05-26**: RFC-000 - System Conceptual Design
  - Status: Implemented
  - Kind: Conceptual Design

- **2026-05-26**: RFC-100 - CoreAgent Runtime Architecture
  - Status: Draft
  - Kind: Architecture Design

- **2026-07-07**: RFC-619 revised — Deep Research Subagent (`deep_research` web-only + `academic_research`; adaptive report)
  - Status: Accepted (revised)
  - Kind: Architecture Design

- **2026-05-21**: RFC-619 - Deep Research Subagent (superseded by 2026-07-07 revision)
  - Status: Accepted
  - Kind: Architecture Design
  - Authors: Soothe Team

- **2026-05-21**: RFC-619 supersedes RFC-601

- **2026-05-13**: RFC-214 - Volatility-Tiered Prompt Architecture & Unified Message Ledger
  - Status: Draft
  - Kind: Architecture Design

- **2026-05-11**: RFC-618 - Plan Subagent — Structured Planning with Explore Delegation
  - Status: Draft
  - Kind: Architecture Design
  - Authors: Soothe Team

- **2026-05-09**: RFC-221 - LoopRunnerProtocol: Unified Subprocess-Isolated Agent Loop Execution
  - Status: Draft
  - Kind: Architecture Design

- **2026-05-05**: RFC-213 - StrangeLoop Reasoning Quality & Robustness
  - Status: Draft
  - Kind: Architecture Design
  - Authors: Claude Code

- **2026-05-05**: RFC-220 - LangGraph Agent Loop Orchestrator
  - Status: Draft
  - Kind: Architecture Design

- **2026-05-05**: RFC-604 - Plan Phase Robustness (Three-Layer Defense)
  - Status: Implemented
  - Kind: Architecture Design
  - Authors: Claude Sonnet 4.6

- **2026-05-05**: RFC-220 supersedes RFC-201

- **2026-05-04**: RFC-603 - Reasoning Quality & Progressive Actions
  - Status: Draft
  - Kind: Feature Enhancement
  - Authors: Claude Code

- **2026-05-01**: RFC-403 - Unified Event Naming Semantics
  - Status: Draft
  - Kind: Implementation Interface Design
  - Authors: Platonic Brainstorming Session

- **2026-05-01**: RFC-501 - Display & Verbosity
  - Status: Draft
  - Kind: Implementation Interface Design
  - Authors: Soothe Team

- **2026-05-01**: RFC-613 - Explore Agent — LLM-Orchestrated Iterative Search
  - Status: Draft
  - Kind: Architecture Design
  - Authors: Platonic Coding Workflow

- **2026-05-01**: RFC-501 supersedes RFC-0020

- **2026-05-01**: RFC-501 supersedes RFC-0024

- **2026-05-01**: RFC-613 supersedes RFC-605

### 2026-04

- **2026-04-30**: RFC-901 - OperationSecurityProtocol: Unified Workspace and Tool Operation Security
  - Status: Draft
  - Kind: Architecture Design
  - Note: Reclassified from 6xx to 9xx per RFC-900

- **2026-04-29**: RFC-201 - StrangeLoop Plan-Execute Loop Architecture (Consolidated Layer 2)
  - Status: Implemented
  - Kind: Architecture Design

- **2026-04-29**: RFC-401 - Event Processing & Filtering
  - Status: Implemented
  - Kind: Implementation Interface Design
  - Authors: Soothe Team

- **2026-04-29**: RFC-500 - CLI TUI Architecture Design
  - Status: Implemented
  - Kind: Architecture Design

- **2026-04-29**: RFC-401 supersedes RFC-0015

- **2026-04-29**: RFC-401 supersedes RFC-0019

- **2026-04-29**: RFC-401 supersedes RFC-0022

- **2026-04-28**: RFC-219 - Goal Completion Module Architecture
  - Status: Implemented
  - Kind: Architecture Design

- **2026-04-28**: RFC-616 - Scenario-Driven Goal Completion Synthesis
  - Status: Draft
  - Kind: Architecture Design

- **2026-04-27**: RFC-614 - Unified Daemon → Client Streaming Messaging Framework
  - Status: Draft
  - Kind: Architecture Design
  - Authors: Soothe Team

- **2026-04-22**: RFC-218 - StrangeLoop Checkpoint Tree Architecture
  - Status: Draft
  - Kind: Architecture Design

- **2026-04-22**: RFC-411 - Event Stream Replay & History Reconstruction
  - Status: Deprecated → Archived (2026-06-19)
  - Kind: Architecture Design
  - Superseded by: RFC-413 (Server-Owned Display Card Ledger)

- **2026-04-22**: RFC-503 - Loop-First User Experience Architecture
  - Status: Draft
  - Kind: Architecture Design

- **2026-04-22**: RFC-504 - Loop Management CLI Commands
  - Status: Draft
  - Kind: Implementation Interface Design

- **2026-04-22**: RFC-802 - Persistence Architecture Refactor
  - Status: Draft
  - Kind: Architecture Design
  - Authors: Platonic Coding Workflow

- **2026-04-17**: RFC-001 - Architecture Design for Core Protocol Modules
  - Status: Implemented

- **2026-04-17**: RFC-203 - StrangeLoop State & Memory Architecture
  - Status: Draft → Archived (2026-06-19)
  - Kind: Architecture Design / Impl Interface
  - Superseded by: RFC-626

- **2026-04-17**: RFC-207 - StrangeLoop Thread Management & Goal Context
  - Status: Draft
  - Kind: Architecture Design

- **2026-04-17**: RFC-217 - Goal Context Management for StrangeLoop
  - Status: Draft
  - Kind: Architecture Design

- **2026-04-17**: RFC-302 - ContextProtocol: Unbounded Knowledge & Goal-Centric Retrieval
  - Status: Implemented (partial)
  - Kind: Architecture Design
  - Note: Reclassified from 4xx to 3xx per RFC-900; implemented 2026-08-17 (HMX-05) — ContextProtocol/ContextRetrievalModule/KeywordContext in soothe.context.retrieval

- **2026-04-17**: RFC-303 - MemoryProtocol: Cross-Thread Memory & Context Separation
  - Status: Draft
  - Kind: Architecture Design
  - Note: Reclassified from 4xx to 3xx per RFC-900

- **2026-04-17**: RFC-304 - PlannerProtocol: Plan Creation & Two-Phase Implementation Pattern
  - Status: Draft
  - Kind: Architecture Design
  - Note: Reclassified from 4xx to 3xx per RFC-900

- **2026-04-17**: RFC-305 - PolicyProtocol: Permission Checking & Scope Matching
  - Status: Draft
  - Kind: Architecture Design
  - Note: Reclassified from 4xx to 3xx per RFC-900

- **2026-04-17**: RFC-306 - DurabilityProtocol: Thread Lifecycle & Metadata Management
  - Status: Draft
  - Kind: Architecture Design
  - Note: Reclassified from 4xx to 3xx per RFC-900

- **2026-04-17**: RFC-610 - SDK Module Structure Refactoring
  - Status: Draft
  - Kind: Architecture Design

- **2026-04-16**: RFC-216 - StrangeLoop Multi-Thread Infinite Lifecycle with Automatic Thread Switching
  - Status: Draft
  - Kind: Architecture Design
  - Note: Superseded by RFC-207 on 2026-06-19

- **2026-04-16**: RFC-454 - Slash Command Architecture
  - Status: Draft
  - Kind: Architecture Design

- **2026-04-14**: RFC-450 - Unified Daemon Communication Protocol for WebSocket IPC
  - Status: Implemented
  - Kind: Architecture Design

- **2026-04-14**: RFC-607 - Progressive Display Refinements Post-Migration
  - Status: Draft
  - Kind: Implementation Interface Design
  - Authors: Claude Code, Xiaming Chen

- **2026-04-13**: RFC-605 - Explore Subagent and Parallel Spawning
  - Status: Superseded → Archived (2026-06-19)
  - Kind: Architecture Design
  - Superseded by: RFC-613

- **2026-04-13**: RFC-606 - DeepAgents CLI TUI Migration
  - Status: Draft
  - Kind: Architecture Design + Implementation Interface Design

- **2026-04-10**: RFC-211 - Layer 2 Tool Result Optimization
  - Status: Draft
  - Kind: Architecture Design

- **2026-04-08**: RFC-206 - Hierarchical Prompt Architecture with System/User Separation
  - Status: Draft
  - Kind: Architecture Design

- **2026-04-05**: RFC-601 - Built-in Plugin Agents
  - Status: Implemented
  - Kind: Architecture Design
  - Authors: Soothe Team

- **2026-04-05**: RFC-601 supersedes RFC-0004

- **2026-04-05**: RFC-601 supersedes RFC-0005

- **2026-04-05**: RFC-601 supersedes RFC-0021

- **2026-04-04**: RFC-801 - SQLite Backend for Persistence, Durability, and Vector Store
  - Status: Draft
  - Kind: Architecture Design + Implementation Interface Design
  - Note: Reclassified from 6xx to 8xx per RFC-900

- **2026-04-02**: RFC-502 - Unified Presentation Engine
  - Status: Implemented (partial)
  - Kind: Implementation Interface Design
  - Authors: Soothe Team

### 2026-03

- **2026-03-31**: RFC-101 - Tool Interface & Event Naming
  - Status: Implemented
  - Kind: Implementation Interface Design
  - Authors: Xiaming Chen

- **2026-03-31**: RFC-103 - Thread-Aware Workspace
  - Status: Draft
  - Kind: Implementation Interface Design

- **2026-03-31**: RFC-104 - Dynamic System Context Injection
  - Status: Implemented
  - Kind: Implementation Interface Design

- **2026-03-31**: RFC-301 - Protocol Registry
  - Status: Implemented
  - Kind: Implementation Interface Design
  - Authors: Xiaming Chen

- **2026-03-31**: RFC-101 supersedes RFC-0016

- **2026-03-31**: RFC-101 supersedes RFC-0025

- **2026-03-27**: RFC-300 - Context and Memory Architecture Design
  - Status: Superseded → Archived (2026-06-19)
  - Superseded by: RFC-302, RFC-303

- **2026-03-27**: RFC-600 - Plugin Extension Specification
  - Status: Implemented
  - Kind: Architecture Design

- **2026-03-22**: RFC-452 - Unified Thread Management Architecture
  - Status: Draft
  - Kind: Architecture Design

- **2026-03-18**: RFC-102 - Secure Filesystem Path Handling and Security Policy
  - Status: Implemented
  - Kind: Implementation Interface Design

## Supersede Relationships

This section tracks which RFCs supersede older ones.

| RFC | Supersedes |
|-----|------------|
| RFC-101 | RFC-0016, RFC-0025 |
| RFC-220 | RFC-201 |
| RFC-401 | RFC-0015, RFC-0019, RFC-0022 |
| RFC-413 | RFC-411 |
| RFC-501 | RFC-0020, RFC-0024 |
| RFC-601 | RFC-0004, RFC-0005, RFC-0021 |
| RFC-613 | RFC-605 |
| RFC-619 | RFC-601 |
| RFC-622 |  |

## RFC Lifecycle Milestones

### Implemented RFCs

- **2026-05-28**: RFC-200 implemented
- **2026-05-28**: RFC-204 implemented
- **2026-05-26**: RFC-000 implemented
- **2026-05-05**: RFC-604 implemented
- **2026-04-29**: RFC-201 implemented
- **2026-04-29**: RFC-401 implemented
- **2026-04-29**: RFC-500 implemented
- **2026-04-28**: RFC-219 implemented
- **2026-04-17**: RFC-001 implemented
- **2026-04-14**: RFC-450 implemented
- **2026-04-05**: RFC-601 implemented
- **2026-03-31**: RFC-101 implemented
- **2026-03-31**: RFC-104 implemented
- **2026-03-31**: RFC-301 implemented
- **2026-03-27**: RFC-600 implemented
- **2026-03-18**: RFC-102 implemented

### Deprecated/Superseded RFCs

- **2026-04-22**: RFC-411 - Deprecated. Superseded by RFC-413.
- **2026-04-13**: RFC-605 - Superseded
- **2026-03-27**: RFC-300 - Superseded

## RFC Numbering Series

RFCs are organized into numbered series by category:

### 0xx - Foundation (System Design)

- RFC-000: System Conceptual Design
- RFC-001: Architecture Design for Core Protocol Modules

### 1xx - Core Agent (Runtime)

- RFC-100: CoreAgent Runtime Architecture
- RFC-101: Tool Interface & Event Naming
- RFC-102: Secure Filesystem Path Handling and Security Policy
- RFC-103: Thread-Aware Workspace
- RFC-104: Dynamic System Context Injection
- RFC-105: Progressive Skill Loading

### 2xx - StrangeLoop & Cognition

- RFC-200: Autonomous Goal Management Loop *(archived 2026-06-16)*
- RFC-201: StrangeLoop Plan-Execute Loop Architecture
- RFC-203: StrangeLoop State & Memory Architecture *(archived 2026-06-16)*
- RFC-204: Autopilot Mode
- RFC-206: Hierarchical Prompt Architecture
- RFC-207: StrangeLoop Thread Lifecycle & Goal Context Management
- RFC-211: Layer 2 Tool Result Optimization
- RFC-213: StrangeLoop Reasoning Quality & Robustness
- RFC-214: Volatility-Tiered Prompt Architecture & Unified Message Ledger
- RFC-216: StrangeLoop Multi-Thread Infinite Lifecycle *(archived)*
- RFC-217: Goal Context Management for StrangeLoop
- RFC-218: StrangeLoop Checkpoint Tree Architecture
- RFC-219: Goal Completion Module Architecture
- RFC-220: LangGraph Agent Loop Orchestrator
- RFC-221: Loop Runner Protocol and Subprocess Isolation
- RFC-222: Autopilot Daemon Architecture
- RFC-223: Thread Inheritance with LangGraph Checkpoint Forking
- RFC-224: Automatic Context Window Management
- RFC-225: Loop Continuity and Goal Record Enrichment
- RFC-226: Continuation-Aware plan_assess and Post-Execute Fast Exit
- RFC-227: Plan-Assess Prior-Progress Digest
- RFC-228: Autopilot Job IPC Commands
- RFC-229: Cron Service for Autopilot
- RFC-230: Job Maturity Assessment for Autopilot Rails
- RFC-231: LoopRail and Rail Exec (Composable Verb Bodies)
- RFC-232: Flat WavePlan Wire Ingest (Semi-Structured, No Nesting)

### 3xx - Protocols

- RFC-300: Context and Memory Architecture Design *(archived 2026-06-16)*
- RFC-301: Protocol Registry
- RFC-302: ContextProtocol Architecture
- RFC-303: MemoryProtocol Architecture
- RFC-304: PlannerProtocol Architecture
- RFC-305: PolicyProtocol Architecture
- RFC-306: DurabilityProtocol Architecture
- RFC-307: IdentityProtocol Architecture

### 4xx - Daemon & Transport

- RFC-401: Event Processing & Filtering
- RFC-403: Unified Event Naming Semantics
- RFC-411: Event Stream Replay & History Reconstruction *(archived 2026-06-16)*
- RFC-412: MCP Management
- RFC-413: Server-Owned Display Card Ledger
- RFC-450: Unified Daemon Communication Protocol
- RFC-452: Unified Thread Management Architecture
- RFC-454: Slash Command Architecture

### 5xx - CLI & TUI

- RFC-500: CLI TUI Architecture Design
- RFC-501: Display & Verbosity
- RFC-502: Unified Presentation Engine
- RFC-503: Loop-First User Experience Architecture
- RFC-504: Loop Management CLI Commands
- RFC-505: Soothe Desktop Client Architecture *(archived)*

### 6xx - Plugin System & Extensions

- RFC-600: Plugin Extension Specification
- RFC-601: Built-in Plugin Agents
- RFC-603: Reasoning Quality & Progressive Actions
- RFC-604: Plan Phase Robustness (Three-Layer Defense)
- RFC-605: Explore Subagent and Parallel Spawning *(archived 2026-06-16)*
- RFC-606: DeepAgents CLI TUI Migration Specification
- RFC-607: Progressive Display Refinements Post-Migration
- RFC-610: SDK Module Structure Refactoring
- RFC-613: Explore Agent — LLM-Orchestrated Iterative Search *(archived)*
- RFC-614: Unified Daemon → Client Streaming Messaging Framework
- RFC-616: Scenario-Driven Goal Completion Synthesis
- RFC-618: Plan Subagent — Structured Planning with Explore Delegation
- RFC-619: Deep Research Subagent
- RFC-620: Unified Channel Architecture
- RFC-621: Workspace Host Convention for Container Deployments
- RFC-622: CoreAgent Clarification Relay
- RFC-623: Veritas Auto-Mode Robustness
- RFC-624: Context Engine
- RFC-625: AutopilotMonitor and ContextEngine Unification
- RFC-626: Entity Model and State Management Consolidation
- RFC-627: Unified LLM Utilities Module
- RFC-628: Cognition Step Card & SubAgent Card Display
- RFC-629: Client Library — Core Upgrade and Appkit Architecture
- RFC-630: Start-Phase LLM Intake and Branch Routing
- RFC-631: Goal-Bound Display Snapshots
- RFC-632: Loop-Scoped Router Profile Override
- RFC-633: Planner Plan Artifact and Human Review

### 7xx - Product & Applications

- RFC-700: Desktop App Product Redesign *(archived)*

### 8xx - Persistence

- RFC-801: SQLite Backend Specification
- RFC-802: Persistence Architecture Refactor
- RFC-803: StrangeLoop Checkpoint Backend Architecture

### 9xx - Process / Deprecation / Sloop

- RFC-900: RFC Deprecation List and Number Segment Reclassification Scheme
- RFC-901: OperationSecurityProtocol for Workspace and Tool Execution
- RFC-902: Same-File Edit Concurrency and Optimization
- RFC-903: Sloop Graph Topology and Node Lifecycle
- RFC-904: Sloop Recursive Step Decomposition

---

This history is auto-generated from RFC metadata. To update:
```bash
python scripts/generate_rfc_history.py
```
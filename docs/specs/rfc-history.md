# RFC History

This document tracks the chronological evolution of RFCs in the Soothe project.

**Last Updated**: 2026-07-27
**Total RFCs**: 82

## Summary Statistics

### By Status

| Status | Count | Percentage |
|--------|-------|------------|
| Draft | 53 | 64.6% |
| Implemented | 16 | 19.5% |
| Archived | 6 | 7.3% |
| Proposed | 2 | 2.2% |
| Accepted | 1 | 1.2% |
| Implemented (Partially Superseded) | 1 | 1.2% |
| Implemented — runtime architecture refined | 1 | 1.2% |
| Unknown | 2 | 2.4% |

### By Kind

| Kind | Count |
|------|-------|
| Architecture Design | 54 |
| Implementation Interface Design | 14 |
| Architecture Design + Implementation Interface Design | 2 |
| Architecture Design / Impl Interface | 1 |

## Recent Changes

### 2026-07-27

- **RFC-413** Phase 4 complete (IG-655): append-oriented DisplayCardStore ledger, live `card.*` via `event`/`custom`, TUI always prefers daemon projection for structural cards; inline tool rows remain live-only on step widgets. Design draft `docs/drafts/2026-07-27-tui-card-replay-source-of-truth-design.md`.
| Conceptual Design | 1 |
| Architecture Design + Protocol Specification | 1 |
| Protocol Specification | 1 |
| Feature Enhancement | 1 |
| Product Specification | 1 |
| Process Specification | 1 |
| Unknown | 2 |

## Chronological Timeline

### Major Changes - 2026-07-24

**SQLite process-scoped Runtime + layout hard cut** (design draft formalized into RFC-801 / RFC-802 / RFC-803)

- Introduce `SqliteStoreRuntime` / `SqliteRuntimeRegistry`: one Runtime per DB file; leased readers; `BEGIN IMMEDIATE` writes; uniform WAL + busy_timeout
- All SQLite purpose files under `$SOOTHE_DATA_DIR/databases/{purpose}.db` (`checkpoints`, `context`, `display`, `cron`, `identity`, `metadata`, `persist`, `vectors`, optional `memory`)
- Hard cut: no migration or legacy path shims
- RFC-803: SQLite checkpoint flush is process-scoped (parity with Postgres `LoopPersistenceWriter` shape); per-manager private pools forbidden

---

### Major Changes - 2026-07-19

**Unified persistence backend** (AGENTS.md §10)

- `persistence.default_backend` is one mode for the whole process (postgresql XOR sqlite); mixing is forbidden
- Display cards, cron jobs, and identity follow the same backend (PostgreSQL → `soothe_metadata`)
- Durability overrides that disagree with `default_backend` raise at daemon configure time

**RFC-413 amendment**: Display card ledger follows `persistence.default_backend`

- When `persistence.default_backend: postgresql`, store card mutations and goal display snapshots in PostgreSQL `soothe_metadata` (same tables as SQLite `display.db`)
- SQLite `display.db` remains the default for local/sqlite backends
- Daemon calls `configure_display_card_store()` after Postgres provisioning at startup

---

### Major Changes - 2026-06-30

**RFC-629**: Client Library — Core Upgrade and Appkit Architecture (Go + TypeScript) — absorbs triarch's hand-rolled adaptation layer into the Go and TypeScript client libraries

- Generalizes the prior Go-only RFC to a cross-language client architecture: Layer 0 (core `Client` transport/lifecycle upgrades), Layer 1 (`appkit` package: `ConnectionPool`/`QueryGate`/`TurnRunner`/`EventClassifier`/`SSEBroadcaster`/`SessionStore`), Layer 2 (application product code)
- Layer 0 folds drop detection, `Reconnect`/`ReattachAndProbe`, readiness retry, and concurrent `(type, id)` multiplexing into the core `Client` so every application gets a safe, reconnect-aware client for free
- Layer 1 extracts the reusable application mechanics (pool, single-flight query gate with cancel-before-context ordering, timeout turn loop, event→deliverable classification keyed on `(namespace, mode, phase)`, SSE fan-out, persistence seam) into a new sibling package per client
- Product decisions (deliverable phase sets, persistence, chat modes, error copy) stay pluggable via configuration and interfaces; the libraries import no application domain types
- Defines language-specific adaptations (Go channels/`context.Context` vs TypeScript `EventEmitter`/`AsyncGenerator`/`AbortSignal`) while holding the contract identical across both
- Extends RFC-450 (client-side transport/lifecycle) and RFC-610 (SDK module structure); implemented by IG-527 (Go) and IG-528 (TypeScript)

**RFC-630**: Start-Phase LLM Intake and Branch Routing — replaces heuristic intent judgment with LLM intake + branch routing

- Replaces the binary `IntentClassifier` LLM + its `_is_likely_agentic` heuristic bypass (len>80 / words>15 / newlines≥2) with a single 4-class intake LLM (`quiz | trivial | simple | complex`)
- Runs the intake LLM `asyncio.gather`-ed with the pre-graph IO cluster (checkpoint load, ContextEngine load, instruction/memory file reads via `to_thread`, git status) so the LLM round-trip is hidden behind IO that must run anyway
- Adds `route_by_intent` conditional edge after `init_or_resume` dispatching by intake+continuation: `quiz`→END, fresh `trivial`→synthetic 1-step plan (no plan LLM), fresh `simple`→lightweight `plan_generate`, continuation `trivial/simple`→`plan_assess` discriminator, `complex`→full existing spine
- Continuation remains a structural overlay from the checkpoint (not an LLM label); clarification remains emergent from the planner (not an intake branch)
- Deletes the `simple_bypass` `"I will complete this goal directly:"` prefix; the `trivial` branch emits the goal itself as the step action; IG-569 replaces the `## Result` execute contract with the Step Deliverable Gate
- Preserves the fresh-loop skip (IG-476), continuation discriminator (RFC-226), and clarification relay (RFC-622) unchanged
- Extends RFC-225 (intent classification taxonomy) and RFC-220 (orchestrator topology); supersedes the IG-518 heuristic-bypass path
- Feature flag `config.agent.loop.intake.branch_routing.enabled` (default `false`) gates rollout

---

### Major Changes - 2026-06-26

**RFC-628**: Cognition Step Card Display — canonical TUI step card spec

- Extracted `cognition_step_activity.py` (classification, activity tree, status lines)
- Unified `_sync_step_card_surface()` refresh pipeline
- Footer and branch Running lines show total tool counts (main + subgraph + orphan)
- Removed obsolete step-card auto-collapse; manual click-to-collapse retained
- Extends RFC-500 § Event Rendering and RFC-501 § 7.3 (supersedes IG-402-centric descriptions for normative design)

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
   - Updated archive/README.md with archival policy
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
  - Status: Draft
  - Kind: Architecture Design

- **2026-06-04**: RFC-700 - Desktop App Product Redesign
  - Status: Proposed
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
  - Status: Draft
  - Kind: Architecture Design
  - Note: Reclassified from 4xx to 3xx per RFC-900

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
  - Status: Draft
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

- RFC-200: Autonomous Goal Management Loop
- RFC-201: StrangeLoop Plan-Execute Loop Architecture (Consolidated Layer 2)
- RFC-203: StrangeLoop State & Memory Architecture
- RFC-204: Autopilot Mode (Layer 3 Extension)
- RFC-206: Hierarchical Prompt Architecture with System/User Separation
- RFC-207: StrangeLoop Thread Management & Goal Context
- RFC-211: Layer 2 Tool Result Optimization
- RFC-213: StrangeLoop Reasoning Quality & Robustness
- RFC-214: Volatility-Tiered Prompt Architecture & Unified Message Ledger
- RFC-803: StrangeLoop Checkpoint Backend Architecture
- RFC-207: StrangeLoop Thread Lifecycle & Goal Context (supersedes RFC-216)
- RFC-217: Goal Context Management for StrangeLoop
- RFC-218: StrangeLoop Checkpoint Tree Architecture
- RFC-219: Goal Completion Module Architecture
- RFC-220: LangGraph Agent Loop Orchestrator
- RFC-221: LoopRunnerProtocol: Unified Subprocess-Isolated Agent Loop Execution
- RFC-222: Autopilot and Goal Engine Architecture (Daemon-Owned)
- RFC-223: Thread Inheritance with LangGraph Checkpoint Forking
- RFC-224: Automatic Context Window Management
- RFC-225: Loop Continuity and Goal Record Enrichment
- RFC-226: Continuation-Aware plan_assess and Post-Execute Fast Exit
- RFC-227: Plan-Assess Prior-Progress Digest
- RFC-228: Autopilot Job IPC Commands for Desktop Integration

### 3xx - Protocols

- RFC-300: Context and Memory Architecture Design
- RFC-301: Protocol Registry

### 4xx - Daemon & Transport

- RFC-302: ContextProtocol: Unbounded Knowledge & Goal-Centric Retrieval
- RFC-401: Event Processing & Filtering
- RFC-303: MemoryProtocol: Cross-Thread Memory & Context Separation
- RFC-403: Unified Event Naming Semantics
- RFC-304: PlannerProtocol: Plan Creation & Two-Phase Implementation Pattern
- RFC-305: PolicyProtocol: Permission Checking & Scope Matching
- RFC-306: DurabilityProtocol: Thread Lifecycle & Metadata Management
- RFC-411: Event Stream Replay & History Reconstruction
- RFC-412: MCP Management
- RFC-413: Server-Owned Display Card Ledger
- RFC-450: Unified Daemon Communication Protocol for WebSocket IPC
- RFC-452: Unified Thread Management Architecture
- RFC-454: Slash Command Architecture

### 5xx - CLI & TUI

- RFC-500: CLI TUI Architecture Design
- RFC-501: Display & Verbosity
- RFC-502: Unified Presentation Engine
- RFC-503: Loop-First User Experience Architecture
- RFC-504: Loop Management CLI Commands
- RFC-505: Soothe Desktop Client Architecture

### 6xx - Plugin System & Extensions

- RFC-600: Plugin Extension Specification
- RFC-601: Built-in Plugin Agents
- RFC-801: SQLite Backend for Persistence, Durability, and Vector Store
- RFC-603: Reasoning Quality & Progressive Actions
- RFC-604: Plan Phase Robustness (Three-Layer Defense)
- RFC-605: Explore Subagent and Parallel Spawning
- RFC-606: DeepAgents CLI TUI Migration
- RFC-607: Progressive Display Refinements Post-Migration
- RFC-610: SDK Module Structure Refactoring
- RFC-802: Persistence Architecture Refactor
- RFC-613: Explore Agent — LLM-Orchestrated Iterative Search
- RFC-614: Unified Daemon → Client Streaming Messaging Framework
- RFC-616: Scenario-Driven Goal Completion Synthesis
- RFC-901: OperationSecurityProtocol: Unified Workspace and Tool Operation Security
- RFC-618: Plan Subagent — Structured Planning with Explore Delegation
- RFC-619: Deep Research Subagent
- RFC-620: Unified Channel Architecture for Extensible Communication Endpoints
- RFC-621: Workspace Host Convention: Path Mapping for Containerized Daemon
- RFC-622: CoreAgent Clarification Relay
- RFC-623: Veritas Auto-Mode Robustness

### 7xx - Product & Applications

- RFC-700: Desktop App Product Redesign

---

This history is auto-generated from RFC metadata. To update:
```bash
python scripts/generate_rfc_history.py
```

# RFC Index

**Last Updated**: 2026-06-26
**Total RFCs**: 80 (6 archived, 7 reclassified, 1 process specification)

This index provides a comprehensive catalog of all RFCs in the Soothe project.

## RFC Status Summary

| Status | Count |
|--------|-------|
| Draft | 50 |
| Implemented | 16 |
| Implemented (Partially Superseded) | 1 |
| Implemented — runtime architecture refined | 1 |
| Archived | 6 |
| Proposed | 2 |
| Accepted | 1 |

## RFC Kind Summary

| Kind | Count |
|------|-------|
| Architecture Design | 53 |
| Implementation Interface Design | 14 |
| Unknown | 2 |
| Architecture Design + Implementation Interface Design | 2 |
| Conceptual Design | 1 |
| Architecture Design / Impl Interface | 1 |
| Protocol Specification | 1 |
| Feature Enhancement | 1 |
| Product Specification | 1 |
| Process Specification | 1 |

---

## RFC Catalog

### Foundation (0xx)

- **RFC-000**: [System Conceptual Design](RFC-000-system-conceptual-design.md)
  - Kind: Conceptual Design
  - Status: Implemented
  - Created: 2026-03-12

- **RFC-001**: [Architecture Design for Core Protocol Modules](RFC-001-core-modules-architecture.md)
  - Kind: Not stated
  - Status: Implemented
  - Created: 2026-03-12

---

### Core Agent (1xx)

- **RFC-100**: [CoreAgent Runtime Architecture](RFC-100-coreagent-runtime.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-03-29

- **RFC-101**: [Tool Interface & Event Naming](RFC-101-tool-interface.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-03-31
  - Supersedes: RFC-0016, RFC-0025
  - Depends on: RFC-100 (CoreAgent Runtime), RFC-401 (Event Processing)
  - Authors: Xiaming Chen

- **RFC-102**: [Secure Filesystem Path Handling and Security Policy](RFC-102-security-filesystem-policy.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-03-18

- **RFC-103**: [Thread-Aware Workspace](RFC-103-thread-aware-workspace.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-03-31

- **RFC-104**: [Dynamic System Context Injection](RFC-104-dynamic-system-context.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-03-31

- **RFC-105**: [Progressive Skill Loading](RFC-105-progressive-skill-loading.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-05-29
  - Authors: Platonic brainstorming session

---

### StrangeLoop & Cognition (2xx)

- **RFC-200**: [Autonomous Goal Management Loop](archive/RFC-200-autonomous-goal-management.md) ⚠️ **ARCHIVED**
  - Kind: Architecture Design
  - Status: Archived
  - Superseded By: RFC-222 (control flow), RFC-625 (GoalEngine architecture)
  - Archived Date: 2026-06-19
  - Created: 2026-03-15

- **RFC-201**: [StrangeLoop Plan-Execute Loop Architecture (Consolidated Layer 2)](RFC-201-strangeloop-plan-execute-loop.md)
  - Kind: Architecture Design
  - Status: Implemented (Partially Superseded)
  - Partially Superseded By: RFC-220 (§loop driver)
  - Created: 2026-04-17

- **RFC-203**: [StrangeLoop State & Memory Architecture](archive/RFC-203-strangeloop-state-memory.md) ⚠️ **ARCHIVED**
  - Kind: Architecture Design / Impl Interface
  - Status: Archived
  - Superseded By: RFC-626
  - Archived Date: 2026-06-19
  - Created: 2026-04-17

- **RFC-204**: [Autopilot Mode (Layer 3 Extension)](RFC-204-autopilot-mode.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-04-03

- **RFC-206**: [Hierarchical Prompt Architecture with System/User Separation](RFC-206-prompt-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-08

- **RFC-207**: [StrangeLoop Thread Management & Goal Context](RFC-207-strangeloop-thread-context-lifecycle.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17

- **RFC-211**: [Layer 2 Tool Result Optimization](RFC-211-layer2-tool-result-optimization.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-10

- **RFC-213**: [StrangeLoop Reasoning Quality & Robustness](RFC-213-strangeloop-reasoning-quality.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17
  - Authors: Claude Code

- **RFC-214**: [Volatility-Tiered Prompt Architecture & Unified Message Ledger](RFC-214-strangeloop-loop-message-surface.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-05-03

- **RFC-216**: [StrangeLoop Multi-Thread Infinite Lifecycle](archive/RFC-216-strangeloop-multithread-lifecycle.md) ⚠️ **ARCHIVED**
  - Kind: Architecture Design
  - Status: Archived
  - Superseded By: RFC-207
  - Archived Date: 2026-06-19
  - Created: 2026-04-16

- **RFC-217**: [Goal Context Management for StrangeLoop](RFC-217-goal-context-management.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17

- **RFC-218**: [StrangeLoop Checkpoint Tree Architecture](RFC-218-strangeloop-checkpoint-tree-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-22

- **RFC-219**: [Goal Completion Module Architecture](RFC-219-goal-completion-module.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-04-28

- **RFC-220**: [LangGraph Agent Loop Orchestrator](RFC-220-langgraph-agent-loop-orchestrator.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-05-05
  - Supersedes: RFC-201 §loop driver (imperative Plan → Execute driver)

- **RFC-221**: [LoopRunnerProtocol: Unified Subprocess-Isolated Agent Loop Execution](RFC-221-loop-runner-protocol-and-ray.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-05-09

- **RFC-222**: [Autopilot and Goal Engine Architecture (Daemon-Owned)](RFC-222-autopilot-goal-engine-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-05-27

- **RFC-223**: [Thread Inheritance with LangGraph Checkpoint Forking](RFC-223-thread-inheritance-checkpoint-forking.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-05-27

- **RFC-224**: [Automatic Context Window Management](RFC-224-automatic-context-window-management.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-05-27

- **RFC-225**: [Loop Continuity and Goal Record Enrichment](RFC-225-loop-continuity-and-goal-record-enrichment.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-05-29
  - Depends on: RFC-201, RFC-214, RFC-207, RFC-218, RFC-220
  - Authors: xiaming

- **RFC-226**: [Continuation-Aware plan_assess and Post-Execute Fast Exit](RFC-226-continuation-aware-plan-assess.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-05-29
  - Depends on: RFC-220, RFC-225
  - Authors: xiaming

- **RFC-227**: [Plan-Assess Prior-Progress Digest](RFC-227-plan-assess-prior-progress-digest.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-06-01
  - Depends on: RFC-214, RFC-220
  - Authors: xiaming

- **RFC-228**: [Autopilot Job IPC Commands for Desktop Integration](RFC-228-autopilot-job-ipc.md)
  - Kind: Protocol Specification
  - Status: Proposed
  - Created: 2026-06-04

---

### Protocols (3xx)

- **RFC-300**: [Context and Memory Architecture Design](archive/RFC-300-context-memory-protocols.md) ⚠️ **ARCHIVED**
  - Kind: Architecture Design
  - Status: Archived
  - Superseded By: RFC-302, RFC-303
  - Archived Date: 2026-06-19
  - Created: 2026-03-14

- **RFC-301**: [Protocol Registry](RFC-301-protocol-registry.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-03-31
  - Depends on: RFC-001 (Core Modules Architecture), RFC-302 (Context Protocol), RFC-303 (Memory Protocol)
  - Authors: Xiaming Chen

- **RFC-302**: [ContextProtocol: Unbounded Knowledge & Goal-Centric Retrieval](RFC-302-context-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17
  - Dependencies: RFC-000, RFC-001
  - Related: RFC-303 (Memory), RFC-306 (Durability)
  - Note: Reclassified from 4xx per RFC-900 series semantics

- **RFC-303**: [MemoryProtocol: Cross-Thread Memory & Context Separation](RFC-303-memory-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17
  - Dependencies: RFC-000, RFC-302
  - Related: RFC-306 (Durability), RFC-625 (AutopilotMonitor and ContextEngine Unification), RFC-626 (Entity Model and State Management Consolidation)
  - Implemented by: CE's EpisodicSubmodule (RFC-625, RFC-626)
  - Note: Reclassified from 4xx per RFC-900 series semantics

- **RFC-304**: [PlannerProtocol: Plan Creation & Two-Phase Implementation Pattern](RFC-304-planner-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17
  - Dependencies: RFC-000, RFC-302
  - Related: RFC-201 (StrangeLoop)
  - Note: Reclassified from 4xx per RFC-900 series semantics

- **RFC-305**: [PolicyProtocol: Permission Checking & Scope Matching](RFC-305-policy-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17
  - Dependencies: RFC-000, RFC-001
  - Related: RFC-100 (CoreAgent)
  - Note: Reclassified from 4xx per RFC-900 series semantics

- **RFC-306**: [DurabilityProtocol: Thread Lifecycle & Metadata Management](RFC-306-durability-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17
  - Dependencies: RFC-000, RFC-001
  - Related: RFC-203 (Checkpoint), RFC-303 (Memory)
  - Note: Reclassified from 4xx per RFC-900 series semantics

- **RFC-307**: [IdentityProtocol: AKSK Authentication & JWT Token Management](RFC-307-identity-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-06-25
  - Dependencies: RFC-000, RFC-001, RFC-305
  - Related: RFC-620 (Channel Architecture), RFC-621 (Workspace Isolation)

---

### Daemon & Transport (4xx)

- **RFC-401**: [Event Processing & Filtering](RFC-401-event-processing.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-03-31
  - Supersedes: RFC-0015, RFC-0019, RFC-0022
  - Depends on: RFC-450 (Daemon Communication), RFC-403 (Unified Event Naming), RFC-500 (CLI/TUI Architecture)
  - Authors: Soothe Team

- **RFC-403**: [Unified Event Naming Semantics](RFC-403-unified-event-naming.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-04-15
  - Authors: Platonic Brainstorming Session

- **RFC-411**: [Event Stream Replay & History Reconstruction](archive/RFC-411-event-stream-replay.md) ⚠️ **ARCHIVED**
  - Kind: Architecture Design
  - Status: Archived
  - Superseded By: RFC-413
  - Archived Date: 2026-06-19
  - Created: 2026-04-22

- **RFC-412**: [MCP Management](RFC-412-mcp-management.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-05-29
  - Authors: Platonic brainstorming session

- **RFC-413**: [Server-Owned Display Card Ledger](RFC-413-server-owned-display-card-ledger.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-06-04
  - Supersedes: RFC-411 (history reconstruction model)
  - Depends on: RFC-401 (Event Processing), RFC-403 (Unified Event Naming), RFC-411 (Event Stream Replay), RFC-503 (Loop-First UX), RFC-505 (Soothe Desktop Client)
  - Authors: xiaming (with Claude)

- **RFC-450**: [Unified Daemon Communication Protocol for WebSocket IPC](RFC-450-daemon-communication-protocol.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-03-19

- **RFC-452**: [Unified Thread Management Architecture](RFC-452-unified-thread-management.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-03-22

- **RFC-454**: [Slash Command Architecture](RFC-454-slash-command-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-16

---

### CLI & TUI (5xx)

- **RFC-500**: [CLI TUI Architecture Design](RFC-500-cli-tui-architecture.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-03-12
  - Related: RFC-628 (step card display spec)

- **RFC-501**: [Display & Verbosity](RFC-501-display-verbosity.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-03-31
  - Supersedes: RFC-0020, RFC-0024
  - Depends on: RFC-500 (CLI/TUI Architecture), RFC-401 (Event Processing)
  - Related: RFC-628 (TUI step card body)
  - Authors: Soothe Team

- **RFC-502**: [Unified Presentation Engine](RFC-502-unified-presentation-engine.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-04-02
  - Depends on: RFC-401 (Event Processing), RFC-501 (Display & Verbosity), RFC-500 (CLI/TUI Architecture)
  - Authors: Soothe Team

- **RFC-503**: [Loop-First User Experience Architecture](RFC-503-loop-first-user-experience.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-22

- **RFC-504**: [Loop Management CLI Commands](RFC-504-loop-management-cli-commands.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-04-22

- **RFC-505**: [Soothe Desktop Client Architecture](RFC-505-soothe-desktop-client.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-06-04

---

### Plugin System & Extensions (6xx)

- **RFC-600**: [Plugin Extension Specification](RFC-600-plugin-extension-system.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-03-23

- **RFC-601**: [Built-in Plugin Agents](RFC-601-built-in-agents.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-03-31
  - Supersedes: RFC-0004, RFC-0005, RFC-0021
  - Depends on: RFC-600 (Plugin Extension System), RFC-301 (Protocol Registry)
  - Authors: Soothe Team

- **RFC-603**: [Reasoning Quality & Progressive Actions](RFC-603-reasoning-quality-progressive-actions.md)
  - Kind: Feature Enhancement
  - Status: Draft
  - Created: 2026-04-09
  - Authors: Claude Code

- **RFC-604**: [Plan Phase Robustness (Three-Layer Defense)](RFC-604-reason-phase-robustness.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-04-11
  - Depends on: RFC-201 (StrangeLoop Plan-Execute Loop)
  - Authors: Claude Sonnet 4.6

- **RFC-605**: [Explore Subagent and Parallel Spawning](archive/RFC-605-explore-subagent-parallel-spawning.md) ⚠️ **ARCHIVED**
  - Kind: Architecture Design
  - Status: Archived
  - Superseded By: RFC-613
  - Archived Date: 2026-06-19
  - Created: 2026-04-13

- **RFC-606**: [DeepAgents CLI TUI Migration](RFC-606-deepagents-cli-tui-migration.md)
  - Kind: Architecture Design + Implementation Interface Design
  - Status: Draft
  - Created: 2026-04-13

- **RFC-607**: [Progressive Display Refinements Post-Migration](RFC-607-progressive-display-refinements.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-04-14
  - Depends on: RFC-606 (DeepAgents CLI TUI Migration), RFC-501 (Display Verbosity), RFC-500 (CLI/TUI Architecture)
  - Authors: Claude Code, Xiaming Chen

- **RFC-610**: [SDK Module Structure Refactoring](RFC-610-sdk-module-structure-refactoring.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17

- **RFC-613**: [Explore Agent — LLM-Orchestrated Iterative Search](RFC-613-explore-agent-llm-orchestrated-search.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-24
  - Supersedes: RFC-605 (explore subagent portion only)
  - Depends on: RFC-000, RFC-001, RFC-100, RFC-600
  - Authors: Platonic Coding Workflow

- **RFC-614**: [Unified Daemon → Client Streaming Messaging Framework](RFC-614-unified-streaming-messaging.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-27
  - Authors: Soothe Team

- **RFC-616**: [Scenario-Driven Goal Completion Synthesis](RFC-616-scenario-driven-synthesis.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-28

- **RFC-618**: [Plan Subagent — Structured Planning with Explore Delegation](RFC-618-plan-subagent-delegation.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-05-11
  - Depends on: RFC-000, RFC-001, RFC-100, RFC-600, RFC-601, RFC-613
  - Authors: Soothe Team

- **RFC-619**: [Tacitus Subagent](RFC-619-tacitus-subagent.md)
  - Kind: Architecture Design
  - Status: Accepted
  - Created: 2026-05-21
  - Supersedes: Research subagent identity and local-source gather paths in RFC-601 §4
  - Depends on: RFC-600 (Plugin Extension System), RFC-601 (Built-in Agents), RFC-403 (Unified Event Naming)
  - Authors: Soothe Team

- **RFC-620**: [Unified Channel Architecture for Extensible Communication Endpoints](RFC-620-channel-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-05-29

- **RFC-621**: [Workspace Host Convention: Path Mapping for Containerized Daemon](RFC-621-workspace-host-convention.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-06-02
  - Authors: Platonic Coding Workflow

- **RFC-622**: [CoreAgent Clarification Relay](RFC-622-coreagent-clarification-relay.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-06-02
  - Supersedes: Empty-answer auto-resume behavior currently encoded in `core/loop/engine/graph_interrupt.py::build_auto_resume_payload` for `type=="ask_user"` interrupts.
  - Depends on: RFC-220 (Agentic Goal Execution / StrangeLoop), RFC-222 (Autopilot Mode), RFC-600 (Plugin Extension System), RFC-601 (Built-in Agents), RFC-403 (Unified Event Naming)
  - Authors: Soothe Team

- **RFC-623**: [Veritas Auto-Mode Robustness](RFC-623-veritas-auto-mode-robustness.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-06-03
  - Depends on: RFC-622 (CoreAgent Clarification Relay), RFC-220 (Agentic Goal Execution / StrangeLoop), RFC-403 (Unified Event Naming)
  - Authors: Soothe Team

- **RFC-624**: [Context Engine — Unified Context Management for Goals, Steps, and Projection](RFC-624-context-engine.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-06-12
  - Updated: 2026-06-15
  - Depends on: RFC-000, RFC-200, RFC-201, RFC-214, RFC-803
  - Authors: Soothe Team

- **RFC-625**: [AutopilotMonitor as ContextEngine Monitor Submodule — GoalEngine Deletion](RFC-625-autopilot-monitor-context-engine-unification.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-06-15
  - Updated: 2026-06-16
  - Depends on: RFC-624, RFC-222, RFC-200
  - Supersedes: RFC-200 (Goal Management) — GoalEngine deleted, features migrated to ContextEngine
  - Authors: Soothe Team

- **RFC-626**: [Entity Model and State Management Consolidation — LoopState Elimination](RFC-626-entity-model-state-consolidation.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-06-16
  - Depends on: RFC-624, RFC-625, RFC-203, RFC-201
  - Extends: RFC-625 — entity model consolidation, LoopState elimination, job abstraction refinement
  - Authors: Soothe Team

- **RFC-628**: [Cognition Step Card Display](RFC-628-step-card-display-refactor.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-06-26
  - Depends on: RFC-500, RFC-501, RFC-607
  - Extends: RFC-500 § Event Rendering, RFC-501 § 7.3
  - Implemented by: IG-512, IG-513, IG-514, IG-515
  - Authors: Xiaming Chen

---

### Product & Applications (7xx)

- **RFC-700**: [Desktop App Product Redesign](RFC-700-desktop-app-product-redesign.md)
  - Kind: Product Specification
  - Status: Proposed
  - Created: 2026-06-04

---

### Persistence & Backends (8xx)

- **RFC-801**: [SQLite Backend for Persistence, Durability, and Vector Store](RFC-801-sqlite-backend.md)
  - Kind: Architecture Design + Implementation Interface Design
  - Status: Draft
  - Created: 2026-04-04
  - Dependencies: RFC-000, RFC-001, RFC-302, RFC-303
  - Related: RFC-200
  - Note: Reclassified from 6xx per RFC-900 series semantics

- **RFC-802**: [Persistence Architecture Refactor](RFC-802-persistence-architecture-refactor.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-22
  - Updated: 2026-04-22
  - Authors: Platonic Coding Workflow
  - Note: Reclassified from 6xx per RFC-900 series semantics

- **RFC-803**: [StrangeLoop Checkpoint Backend Architecture](RFC-803-strangeloop-checkpoint-backend.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-22
  - Updated: 2026-06-19
  - Dependencies: RFC-207 (Thread Lifecycle & Goal Context), RFC-218 (Checkpoint Tree), RFC-503 (Loop-First UX)
  - Authors: Claude Sonnet 4.6
  - Note: Moved from 2xx (RFC-215) per RFC-900 reclassification

---

### Security & Policy (9xx)

- **RFC-900**: [RFC Deprecation List and Number Segment Reclassification Scheme](RFC-900-deprecation-reclassification-scheme.md)
  - Kind: Process Specification
  - Status: Implemented
  - Created: 2026-06-16
  - Implemented: 2026-06-19
  - Authors: Soothe Team

- **RFC-901**: [OperationSecurityProtocol: Unified Workspace and Tool Operation Security](RFC-901-operation-security-protocol.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-30
  - Dependencies: RFC-102, RFC-103, RFC-305, RFC-613
  - Note: Reclassified from 6xx per RFC-900 series semantics

---

## Quick Reference

### Implemented RFCs

| RFC | Title | Date |
|-----|-------|------|
| RFC-000 | System Conceptual Design | 2026-03-12 |
| RFC-001 | Architecture Design for Core Protocol Modules | 2026-03-12 |
| RFC-101 | Tool Interface & Event Naming | 2026-03-31 |
| RFC-102 | Secure Filesystem Path Handling and Security Polic | 2026-03-18 |
| RFC-104 | Dynamic System Context Injection | 2026-03-31 |
| RFC-201 | StrangeLoop Plan-Execute Loop Architecture | 2026-04-17 |
| RFC-204 | Autopilot Mode (Layer 3 Extension) | 2026-04-03 |
| RFC-219 | Goal Completion Module Architecture | 2026-04-28 |
| RFC-301 | Protocol Registry | 2026-03-31 |
| RFC-401 | Event Processing & Filtering | 2026-03-31 |
| RFC-450 | Unified Daemon Communication Protocol for WebSocke | 2026-03-19 |
| RFC-500 | CLI TUI Architecture Design | 2026-03-12 |
| RFC-600 | Plugin Extension Specification | 2026-03-23 |
| RFC-601 | Built-in Plugin Agents | 2026-03-31 |
| RFC-604 | Plan Phase Robustness (Three-Layer Defense) | 2026-04-11 |
| RFC-625 | AutopilotMonitor as ContextEngine Monitor Submodul | 2026-06-15 |
| RFC-900 | RFC Deprecation and Reclassification Scheme | 2026-06-19 |

### Archived RFCs

| RFC | Title | Superseded By | Archive Date |
|-----|-------|---------------|--------------|
| RFC-200 | Autonomous Goal Management Loop | RFC-222, RFC-625 | 2026-06-19 |
| RFC-203 | StrangeLoop State & Memory Architecture | RFC-626 | 2026-06-19 |
| RFC-216 | StrangeLoop Multi-Thread Infinite Lifecycle | RFC-207 | 2026-06-19 |
| RFC-300 | Context and Memory Architecture Design | RFC-302, RFC-303 | 2026-06-19 |
| RFC-411 | Event Stream Replay & History Reconstruction | RFC-413 | 2026-06-19 |
| RFC-605 | Explore Subagent and Parallel Spawning | RFC-613 | 2026-06-19 |

See [archive/README.md](archive/README.md) for archival schedule and process.

### Reclassified RFCs

| RFC | Title | Previous Series | New Series | Reason |
|-----|-------|-----------------|------------|--------|
| RFC-302 | ContextProtocol Architecture | 4xx | 3xx | Protocol specification |
| RFC-303 | MemoryProtocol Architecture | 4xx | 3xx | Protocol specification |
| RFC-304 | PlannerProtocol Architecture | 4xx | 3xx | Protocol specification |
| RFC-305 | PolicyProtocol Architecture | 4xx | 3xx | Protocol specification |
| RFC-306 | DurabilityProtocol Architecture | 4xx | 3xx | Protocol specification |
| RFC-801 | SQLite Backend | 6xx | 8xx | Persistence & backends |
| RFC-802 | Persistence Architecture Refactor | 6xx | 8xx | Persistence & backends |
| RFC-215→803 | StrangeLoop Checkpoint Backend | 2xx | 8xx | Persistence & backends (RFC-215 renamed to RFC-803) |
| RFC-901 | OperationSecurityProtocol | 6xx | 9xx | Security & policy |

See [RFC-900](RFC-900-deprecation-reclassification-scheme.md) for reclassification policy and roadmap.

### Recently Drafted RFCs (Top 10)

| RFC | Title | Status | Created |
|-----|-------|--------|---------|
| RFC-900 | RFC Deprecation and Reclassification Scheme | Proposed | 2026-06-16 |
| RFC-626 | Entity Model and State Management Consolidation | Draft | 2026-06-16 |
| RFC-625 | AutopilotMonitor and ContextEngine Unification | Implemented | 2026-06-15 |
| RFC-624 | Context Engine — Unified Context Management | Draft | 2026-06-12 |
| RFC-228 | Autopilot Job IPC Commands | Proposed | 2026-06-04 |
| RFC-413 | Server-Owned Display Card Ledger | Draft | 2026-06-04 |
| RFC-505 | Soothe Desktop Client Architecture | Draft | 2026-06-04 |
| RFC-700 | Desktop App Product Redesign | Proposed | 2026-06-04 |
| RFC-623 | Veritas Auto-Mode Robustness | Draft | 2026-06-03 |
| RFC-622 | CoreAgent Clarification Relay | Draft | 2026-06-02 |
| RFC-505 | Soothe Desktop Client Architecture | Draft | 2026-06-04 |
| RFC-623 | Veritas Auto-Mode Robustness | Draft | 2026-06-03 |
| RFC-621 | Workspace Host Convention: Path Mapping  | Draft | 2026-06-02 |
| RFC-622 | CoreAgent Clarification Relay | Draft | 2026-06-02 |
| RFC-227 | Plan-Assess Prior-Progress Digest | Draft | 2026-06-01 |
| RFC-105 | Progressive Skill Loading | Draft | 2026-05-29 |

### Supersede Relationships

| New RFC | Supersedes |
|---------|------------|
| RFC-101 | RFC-0016, RFC-0025 |
| RFC-220 | RFC-201 (partial - §loop driver) |
| RFC-401 | RFC-0015, RFC-0019, RFC-0022 |
| RFC-413 | RFC-411 |
| RFC-501 | RFC-0020, RFC-0024 |
| RFC-601 | RFC-0004, RFC-0005, RFC-0021 |
| RFC-613 | RFC-605 |
| RFC-619 | RFC-601 |
| RFC-625 | RFC-200 (GoalEngine deleted, features migrated to CE) |
| RFC-626 | RFC-203 (LoopState eliminated, consolidated into ExecutionState) |

---

## Numbering Ranges

| Range | Category | Count |
|-------|----------|-------|
| 0xx | Foundation | 2 |
| 1xx | Core Agent | 6 |
| 2xx | StrangeLoop & Cognition | 22 |
| 3xx | Protocols | 8 |
| 4xx | Daemon & Transport | 8 |
| 5xx | CLI & TUI | 6 |
| 6xx | Plugin System & Extensions | 20 |
| 7xx | Product & Applications | 1 |
| 8xx | Persistence & Backends | 3 |
| 9xx | Security & Policy | 2 |

---

## Recently Added

- **RFC-628**: Cognition Step Card Display (2026-06-26, Implemented)
- **RFC-626**: Entity Model and State Management Consolidation — LoopState Elimination (2026-06-16)
- **RFC-625**: AutopilotMonitor as ContextEngine Monitor Submodule — GoalEngine Deletion (2026-06-15)
- **RFC-624**: Context Engine — Unified Context Management for Goals, Steps, and Projection (2026-06-12)
- **RFC-228**: Autopilot Job IPC Commands for Desktop Integration (2026-06-04)
- **RFC-413**: Server-Owned Display Card Ledger (2026-06-04)
- **RFC-505**: Soothe Desktop Client Architecture (2026-06-04)
- **RFC-700**: Desktop App Product Redesign (2026-06-04)
- **RFC-623**: Veritas Auto-Mode Robustness (2026-06-03)
- **RFC-621**: Workspace Host Convention: Path Mapping for Containerized Daemon (2026-06-02)
- **RFC-622**: CoreAgent Clarification Relay (2026-06-02)
- **RFC-227**: Plan-Assess Prior-Progress Digest (2026-06-01)
- **RFC-105**: Progressive Skill Loading (2026-05-29)
- **RFC-225**: Loop Continuity and Goal Record Enrichment (2026-05-29)

---

## Related Documents

- [RFC Standard](rfc-standard.md) - RFC process and specification kinds
- [RFC Namings](rfc-namings.md) - Terminology and naming conventions
- [RFC History](rfc-history.md) - Chronological change history

This index is auto-generated from RFC metadata. To update:
```bash
python scripts/generate_rfc_index.py
```

# RFC Index

**Last Updated**: 2026-05-27
**Total RFCs**: 57

This index reflects the canonical RFC set and defines which files are active for architecture and implementation decisions.

---

## RFC Status Summary

| Status | Count |
|--------|-------|
| Draft | 39 |
| Implemented | 18 |

---

## RFC Catalog

### Foundation (0xx)

- **RFC-000**: [System Conceptual Design](RFC-000-system-conceptual-design.md)
  - Kind: Conceptual Design
  - Status: Implemented
  - Created: 2026-03-12

- **RFC-001**: [Core Modules Architecture](RFC-001-core-modules-architecture.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-03-12

### Core Agent (1xx)

- **RFC-100**: [CoreAgent Runtime Architecture](RFC-100-coreagent-runtime.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-03-22

- **RFC-101**: [Tool Interface & Event Naming](RFC-101-tool-interface.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-03-31
  - Supersedes: RFC-0016, RFC-0025

- **RFC-102**: [Secure Filesystem Path Handling and Security Policy](RFC-102-security-filesystem-policy.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-03-22

- **RFC-103**: [Thread-Aware Workspace](RFC-103-thread-aware-workspace.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-04-16

- **RFC-104**: [Dynamic System Context Injection](RFC-104-dynamic-system-context.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-04-09

### AgentLoop & Cognition (2xx)

- **RFC-200**: [Autonomous Goal Management Loop](RFC-200-autonomous-goal-management.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-03-15
  - Supersedes: RFC-0009, RFC-0010, RFC-0011

- **RFC-201**: [AgentLoop Plan-Execute Loop Architecture](RFC-201-agentloop-plan-execute-loop.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-04-17

- **RFC-203**: [AgentLoop State & Memory Architecture](RFC-203-agentloop-state-memory.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17

- **RFC-204**: [Autopilot Mode](RFC-204-autopilot-mode.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-04-03

- **RFC-206**: [Hierarchical Prompt Architecture](RFC-206-prompt-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-08

- **RFC-207**: [AgentLoop Thread Management & Goal Context](RFC-207-agentloop-thread-context-lifecycle.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17

- **RFC-211**: [Tool Result Optimization](RFC-211-layer2-tool-result-optimization.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-10

- **RFC-213**: [AgentLoop Reasoning Quality & Robustness](RFC-213-agentloop-reasoning-quality.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17

- **RFC-214**: [Volatility-Tiered Prompt Architecture & Unified Message Ledger](RFC-214-agentloop-loop-message-surface.md)
  - Kind: Architecture Design
  - Status: Draft
  - Extends: RFC-201, RFC-206, RFC-215
  - Created: 2026-05-03

- **RFC-215**: [AgentLoop Persistence Backend Architecture](RFC-215-agentloop-persistence-backend.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-22
  - Renamed from: RFC-409 (2026-05-03)

- **RFC-216**: [AgentLoop Multi-Thread Lifecycle](RFC-216-agentloop-multithread-lifecycle.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-16
  - Renamed from: RFC-608 (2026-05-03)

- **RFC-217**: [Goal Context Management](RFC-217-goal-context-management.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17
  - Renamed from: RFC-609 (2026-05-03)

- **RFC-218**: [AgentLoop Checkpoint Tree Architecture](RFC-218-agentloop-checkpoint-tree-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-22
  - Renamed from: RFC-611 (2026-05-03)

- **RFC-219**: [Goal Completion Module](RFC-219-goal-completion-module.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-04-28
  - Renamed from: RFC-615 (2026-05-03)

- **RFC-220**: [LangGraph Agent Loop Orchestrator](RFC-220-langgraph-agent-loop-orchestrator.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-05-05
  - Supersedes: RFC-201 imperative driver (Loop Graph cut-over)
  - Renamed from: RFC-620 (renumbered into 2xx)

- **RFC-221**: [Loop Runner Protocol and Subprocess Isolation](RFC-221-loop-runner-protocol-and-ray.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-05-09

- **RFC-222**: [Autopilot and Goal Engine Architecture](RFC-222-autopilot-goal-engine-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-05-27
  - Dependencies: RFC-000, RFC-201, RFC-204

### Protocols (3xx)

- **RFC-300**: [Context and Memory Architecture Design](RFC-300-context-memory-protocols.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-03-14

- **RFC-301**: [Protocol Registry](RFC-301-protocol-registry.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-03-31

### Daemon & Transport (4xx)

- **RFC-400**: [ContextProtocol Architecture](RFC-400-context-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17

- **RFC-401**: [Event Processing & Filtering](RFC-401-event-processing.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-03-31
  - Supersedes: RFC-0015, RFC-0019, RFC-0022

- **RFC-402**: [MemoryProtocol Architecture](RFC-402-memory-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17

- **RFC-403**: [Unified Event Naming Semantics](RFC-403-unified-event-naming.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-04-15

- **RFC-404**: [PlannerProtocol Architecture](RFC-404-planner-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17

- **RFC-406**: [PolicyProtocol Architecture](RFC-406-policy-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17

- **RFC-408**: [DurabilityProtocol Architecture](RFC-408-durability-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17

- **RFC-411**: [Event Stream Replay & History Reconstruction](RFC-411-event-stream-replay.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-24

- **RFC-450**: [Unified Daemon Communication Protocol](RFC-450-daemon-communication-protocol.md)
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

### CLI & TUI (5xx)

- **RFC-500**: [CLI TUI Architecture Design](RFC-500-cli-tui-architecture.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-03-12

- **RFC-501**: [Display & Verbosity](RFC-501-display-verbosity.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-03-31
  - Supersedes: RFC-0020, RFC-0024

- **RFC-502**: [Unified Presentation Engine](RFC-502-unified-presentation-engine.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-04-02

- **RFC-503**: [Loop-First User Experience Architecture](RFC-503-loop-first-user-experience.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-22

- **RFC-504**: [Loop Management CLI Commands](RFC-504-loop-management-cli-commands.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-04-22

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

- **RFC-602**: [SQLite Backend Specification](RFC-602-sqlite-backend.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-04

- **RFC-603**: [Reasoning Quality & Progressive Actions](RFC-603-reasoning-quality-progressive-actions.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-09

- **RFC-604**: [Plan Phase Robustness (Three-Layer Defense)](RFC-604-reason-phase-robustness.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-04-11

- **RFC-605**: [Explore Subagent and Parallel Spawning](RFC-605-explore-subagent-parallel-spawning.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-13

- **RFC-606**: [DeepAgents CLI TUI Migration Specification](RFC-606-deepagents-cli-tui-migration.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-13

- **RFC-607**: [Progressive Display Refinements Post-Migration](RFC-607-progressive-display-refinements.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-04-14

- **RFC-610**: [SDK Module Structure Refactoring](RFC-610-sdk-module-structure-refactoring.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17

- **RFC-612**: [Persistence Architecture Refactor](RFC-612-persistence-architecture-refactor.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-22

- **RFC-613**: [Explore Agent — LLM-Orchestrated Iterative Search](RFC-613-explore-agent-llm-orchestrated-search.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-24
  - Supersedes: RFC-605 explore subagent

- **RFC-614**: [Unified Daemon → Client Streaming Messaging Framework](RFC-614-unified-streaming-messaging.md)
  - Kind: Architecture Design
  - Status: Draft
  - Extends: RFC-450 (Daemon Communication), RFC-401 (Event Processing)
  - Created: 2026-04-27

- **RFC-616**: [Scenario-Driven Goal Completion Synthesis](RFC-616-scenario-driven-synthesis.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-28

- **RFC-617**: [Operation Security Protocol](RFC-617-operation-security-protocol.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-30

- **RFC-618**: [Plan Subagent — Structured Planning with Explore Delegation](RFC-618-plan-subagent-delegation.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-05-11
  - Depends on: RFC-613, RFC-601, RFC-600

---

## Spec Kind Distribution

| Kind | Count |
|------|-------|
| Architecture Design | 37 |
| Implementation Interface Design | 10 |
| Conceptual Design | 1 |
| Not stated / ambiguous | 8 |

---

## Numbering Ranges

| Range | Category | Count |
|-------|----------|-------|
| 0xx | Foundation | 2 |
| 1xx | Core Agent | 5 |
| 2xx | AgentLoop & Cognition | 16 |
| 3xx | Protocols | 2 |
| 4xx | Daemon & Transport | 10 |
| 5xx | CLI & TUI | 5 |
| 6xx | Plugin System & Extensions | 16 |

---

## Recently Added

- **RFC-618**: Plan Subagent — Structured planning delegate with direct explore runnable invokes (2026-05-11)
- **RFC-221**: LoopRunnerProtocol — Unified Subprocess-Isolated Agent Loop Execution (2026-05-09)
- **RFC-220**: LangGraph Agent Loop Orchestrator — Loop Graph keyed by `loop_id` (2026-05-05)
- **RFC-617**: Operation Security Protocol (2026-04-30)
- **RFC-616**: Scenario-Driven Goal Completion Synthesis (2026-04-28)
- **RFC-614**: Unified Daemon → Client Streaming Messaging Framework (2026-04-27)
- **RFC-613**: Explore Agent — LLM-Orchestrated Iterative Search (2026-04-24)
- **RFC-612**: Persistence Architecture Refactor (2026-04-22)
- **RFC-411**: Event Stream Replay & History Reconstruction (2026-04-24)
- **RFC-503**: Loop-First User Experience Architecture (2026-04-22)
- **RFC-504**: Loop Management CLI Commands (2026-04-22)

---

## RFC Lifecycle

| Status | Description |
|--------|-------------|
| Draft | Initial proposal, under review |
| Approved | Accepted for implementation |
| Implemented | Code complete, tests passing |
| Deprecated | Replaced or obsolete |

### Guidelines

1. All RFCs start as **Draft**
2. RFCs transition to **Approved** after design review
3. Implementation creates **IG** (Implementation Guide)
4. Tests must pass before **Implemented** status
5. RFC indices maintained automatically via specs-refine

---

## Related Artifacts

- **Implementation Guides (IG)**: `docs/impl/IG-*.md`
- **Design Drafts**: `docs/drafts/YYYY-MM-DD-*.md`
- **RFC Standard**: `docs/specs/rfc-standard.md`
- **RFC History**: `docs/specs/rfc-history.md`
- **RFC Namings**: `docs/specs/rfc-namings.md`
- **Event Catalog**: `docs/specs/event-catalog.md`

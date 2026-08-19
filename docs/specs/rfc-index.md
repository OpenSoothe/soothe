# RFC Index

**Last Updated**: 2026-08-19
**Total RFCs**: 92 (83 active, 9 archived)

This index provides a comprehensive catalog of all RFCs in the Soothe project.

> **📋 Methodology Guide**: Before authoring a new RFC or transitioning an RFC's
> status, consult the
> [RFC Methodology Guide](../rfc-methodology-guide.md) — a reusable playbook
> synthesizing lifecycle rules and gap-triage scoring.

> **⚠️ Path Restructure Notice (2026-08)**: RFCs written before the 2026-07
> `core/` → flat package restructure retain original design-time paths as
> historical context. Canonical path mappings:
>
> | Old path prefix | Current path |
> |-----------------|-------------|
> | `soothe/core/strange_loop/{core,cognition,state,analysis,utils}/` | `soothe/sloop/{engine,cognition,state,utils}/` |
> | `soothe/core/loop/` | `soothe/sloop/` |
> | `soothe/core/goal_engine/` | `soothe/autopilot/` |
> | `soothe/core/runner/` | `soothe/runner/` |
> | `soothe/core/agent/` | `soothe/coreagent/` |
> | `soothe/core/intention/` | `soothe/sloop/intention/` |
> | `soothe/core/prompts/` | `soothe/prompts/` |
> | `soothe/core/events/` | `soothe/events/` |
> | `soothe/core/middleware/` | `soothe_nano.middleware.*` (PyPI) |
> | `soothe/core/security/` | `soothe/security/` |
> | `soothe/core/resolver/` | `soothe/runner/resolver/` |
> | `soothe_daemon/channels/http_rest.py` | Removed (IG-504) |
> | `soothe_daemon/protocol/errors.py` | `soothe_daemon/protocol/error_codes.py` |
> | `ProtocolError` (daemon) | `RpcProtocolError` |
>
> Explicitly patched RFCs note the correction inline.

## RFC Status Summary

| Status | Count |
|--------|-------|
| Draft | 40 |
| Proposed | 2 |
| Accepted | 1 |
| Implemented | 29 |
| Implemented (partial) | 10 |
| Implemented (Partially Superseded) | 1 |
| Archived | 9 |

> **Note**: Status values follow the lifecycle in `templates/rfc-standard.md`
> (Draft → Proposed → Accepted → Implemented → Deprecated → Archived).
> "Implemented (partial)" and "Implemented (Partially Superseded)" are
> project-specific variants documenting in-progress or partially superseded
> implementations. See individual RFC headers for authoritative per-RFC status.

## RFC Kind Summary

| Kind | Count |
|------|-------|
| Architecture Design | 68 |
| Implementation Interface Design | 15 |
| Architecture Design + Implementation Interface Design | 2 |
| Conceptual Design | 1 |
| Protocol Specification | 1 |
| Architecture Design + Protocol Specification | 1 |
| Architecture Design / Impl Interface | 1 |
| Feature Enhancement | 1 |
| Process Specification | 1 |
| Product Specification | 1 |

---

## RFC Catalog

### Foundation (0xx)

- **RFC-000**: [System Conceptual Design](RFC-000-system-conceptual-design.md)
  - Kind: Conceptual Design
  - Status: Implemented
  - Created: 2026-03-12
  - Updated: 2026-05-26
- **RFC-001**: [Architecture Design for Core Protocol Modules](RFC-001-core-modules-architecture.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-03-12
  - Updated: 2026-04-17 (RFC consolidation; retrieval module canonical in RFC-302)

### Core Agent (1xx)

- **RFC-100**: [CoreAgent Runtime Architecture](RFC-100-coreagent-runtime.md)
  - Kind: Architecture Design
  - Status: Implemented (partial)
  - Created: 2026-03-29
  - Depends on: RFC-000, RFC-001
  - Updated: 2026-05-26
- **RFC-101**: [Tool Interface & Event Naming](RFC-101-tool-interface.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-03-31
  - Depends on: RFC-100 (CoreAgent Runtime), RFC-401 (Event Processing)
  - Supersedes: RFC-0016, RFC-0025
  - Authors: Xiaming Chen
  - Updated: 2026-03-31
- **RFC-102**: [Secure Filesystem Path Handling and Security Policy](RFC-102-security-filesystem-policy.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-03-18
  - Depends on: RFC-001 (Policy System)
  - Authors: System
  - Implemented: 2026-03-18
- **RFC-103**: [Thread-Aware Workspace](RFC-103-thread-aware-workspace.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-03-31
  - Depends on: RFC-102 (Security Filesystem Policy), RFC-450 (Daemon Communication), RFC-452 (Thread Management)
  - Authors: Design brainstorming session
  - Updated: 2026-08-08
- **RFC-104**: [Dynamic System Context Injection](RFC-104-dynamic-system-context.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-03-31
  - Depends on: RFC-100 (CoreAgent Runtime), RFC-101 (Tool Interface), RFC-103 (Thread-Aware Workspace)
  - Authors: Platonic brainstorming session
  - Updated: 2026-08-08
- **RFC-105**: [Progressive Skill Loading](RFC-105-progressive-skill-loading.md)
  - Kind: Implementation Interface Design
  - Status: Implemented (partial)
  - Created: 2026-05-29
  - Depends on: RFC-100 (CoreAgent Runtime), RFC-104 (Dynamic System Context), RFC-214 (StrangeLoop Loop Message Surface), RFC-600 (Plugin Extension System)
  - Authors: Platonic brainstorming session
  - Updated: 2026-07-03

### StrangeLoop & Cognition (2xx)

- **RFC-200**: [Autonomous Goal Management Loop](../archive/specs/RFC-200-autonomous-goal-management.md) ⚠️ **ARCHIVED**
  - Kind: Architecture Design
  - Status: Archived
  - Superseded By: RFC-222 (control flow), RFC-625 (GoalEngine architecture)
  - Archived Date: 2026-06-16
  - Created: 2026-03-15
- **RFC-201**: [StrangeLoop Plan-Execute Loop Architecture](RFC-201-strangeloop-plan-execute-loop.md)
  - Kind: Architecture Design
  - Status: Implemented (Partially Superseded)
  - Created: 2026-04-17
  - Depends on: RFC-000, RFC-001, RFC-100
  - Partially Superseded By: RFC-220 (§loop driver), RFC-222 (GoalEngine daemon-ownership), RFC-225 (loop-centric model), RFC-904 (recursive step decomposition — upfront plan waves)
  - Updated: 2026-08-19
- **RFC-203**: [StrangeLoop State & Memory Architecture](../archive/specs/RFC-203-strangeloop-state-memory.md) ⚠️ **ARCHIVED**
  - Kind: Architecture Design / Impl Interface
  - Status: Archived
  - Superseded By: RFC-626
  - Archived Date: 2026-06-16
  - Created: 2026-04-17
- **RFC-204**: [Autopilot Mode](RFC-204-autopilot-mode.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-04-03
  - Depends on: RFC-200, RFC-201, RFC-203, RFC-222, RFC-450, RFC-500
  - Updated: 2026-08-08
- **RFC-206**: [Hierarchical Prompt Architecture](RFC-206-prompt-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-08
  - Depends on: RFC-200, RFC-100, RFC-214 (Volatility-Tiered Prompt Architecture & Unified Message Ledger)
- **RFC-207**: [StrangeLoop Thread Lifecycle & Goal Context Management](RFC-207-strangeloop-thread-context-lifecycle.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17
  - Depends on: RFC-201, RFC-203
  - Supersedes: RFC-216 (Multi-Thread Infinite Lifecycle)
  - Updated: 2026-06-19
- **RFC-211**: [Layer 2 Tool Result Optimization](RFC-211-layer2-tool-result-optimization.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-10
  - Depends on: RFC-200, RFC-100, RFC-203, RFC-207
  - Updated: 2026-08-08
- **RFC-213**: [StrangeLoop Reasoning Quality & Robustness](RFC-213-strangeloop-reasoning-quality.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17
  - Depends on: RFC-200, RFC-203
  - Partially Superseded By: RFC-904 (per-iteration assess+generate pair → ROOT_EVAL + `decompose_task`)
  - Authors: Claude Code
  - Updated: 2026-08-19
- **RFC-214**: [Volatility-Tiered Prompt Architecture & Unified Message Ledger](RFC-214-strangeloop-loop-message-surface.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-05-03
  - Depends on: RFC-100 (CoreAgent Runtime), RFC-206 (Prompt Architecture), RFC-104 (Dynamic System Context), RFC-207 (Thread Lifecycle & Goal Context), RFC-203 (StrangeLoop State & Memory), RFC-803 (StrangeLoop Checkpoint Backend), RFC-218 (Checkpoint Tree), RFC-217 (Goal Context Management), RFC-624 (Context Engine)
  - Updated: 2026-08-08
- **RFC-216**: [StrangeLoop Multi-Thread Infinite Lifecycle](../archive/specs/RFC-216-strangeloop-multithread-lifecycle.md) ⚠️ **ARCHIVED**
  - Kind: Architecture Design
  - Status: Archived
  - Created: 2026-04-16
- **RFC-217**: [Goal Context Management for StrangeLoop](RFC-217-goal-context-management.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-04-17
  - Depends on: RFC-201 (Agentic Goal Execution), RFC-207 (Thread Lifecycle & Goal Context), RFC-225 (Loop Continuity)
  - Updated: 2026-08-08
- **RFC-218**: [StrangeLoop Checkpoint Tree Architecture](RFC-218-strangeloop-checkpoint-tree-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-22
  - Depends on: RFC-207 (Thread Lifecycle & Goal Context), RFC-803 (StrangeLoop Checkpoint Backend)
  - Authors: Soothe contributors
- **RFC-219**: [Goal Completion Module Architecture](RFC-219-goal-completion-module.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-04-28
  - Depends on: RFC-201, RFC-603
  - Updated: 2026-08-08
- **RFC-220**: [LangGraph Agent Loop Orchestrator](RFC-220-langgraph-agent-loop-orchestrator.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-05-05
  - Depends on: RFC-000, RFC-001, RFC-100, RFC-604, RFC-803, RFC-218, RFC-219
  - Supersedes: RFC-201 §loop driver (imperative Plan → Execute driver)
  - Partially Superseded By: RFC-903 (node lifecycle, node folds, typed route contract); RFC-904 (recursive step decomposition — plan/eval/execute station spine)
  - Implemented: 2026-08-11
- **RFC-221**: [Loop Runner Protocol and Subprocess Isolation](RFC-221-loop-runner-protocol-and-ray.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-05-09
  - Depends on: RFC-001, RFC-220, RFC-450, RFC-452
- **RFC-222**: [Autopilot Daemon Architecture](RFC-222-autopilot-goal-engine-architecture.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-05-27
  - Depends on: RFC-000, RFC-201, RFC-204, RFC-221 (Loop Runner Protocol), RFC-625, RFC-626, RFC-214 (Loop Message Surface)
  - Updated: 2026-08-16
- **RFC-223**: [Thread Inheritance with LangGraph Checkpoint Forking](RFC-223-thread-inheritance-checkpoint-forking.md)
  - Kind: Architecture Design
  - Status: Implemented (partial)
  - Created: 2026-05-27
  - Depends on: RFC-201, RFC-214, RFC-207, RFC-218
  - Updated: 2026-08-08
- **RFC-224**: [Automatic Context Window Management](RFC-224-automatic-context-window-management.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-05-27
  - Depends on: RFC-223, RFC-201, RFC-214
  - Updated: 2026-08-08
- **RFC-225**: [Loop Continuity and Goal Record Enrichment](RFC-225-loop-continuity-and-goal-record-enrichment.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-05-29
  - Depends on: RFC-201, RFC-214, RFC-207, RFC-218, RFC-220
  - Supersedes: ---
  - Authors: xiaming
  - Updated: 2026-08-08
- **RFC-226**: [Continuation-Aware plan_assess and Post-Execute Fast Exit](RFC-226-continuation-aware-plan-assess.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-05-29
  - Depends on: RFC-220, RFC-225
  - Supersedes: ---
  - Authors: xiaming
  - Updated: 2026-05-29
- **RFC-227**: [Plan-Assess Prior-Progress Digest](RFC-227-plan-assess-prior-progress-digest.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-06-01
  - Depends on: RFC-214, RFC-220
  - Supersedes: ---
  - Authors: xiaming
  - Updated: 2026-06-01
- **RFC-228**: [Autopilot Job IPC Commands](RFC-228-autopilot-job-ipc.md)
  - Kind: Protocol Specification
  - Status: Implemented (partial)
  - Created: 2026-06-04
  - Depends on: RFC-222 (Autopilot and Goal Engine Architecture), RFC-450 (Daemon Communication Protocol)
  - Updated: 2026-08-08
- **RFC-229**: [Cron Service for Autopilot](RFC-229-cron-service.md)
  - Kind: Architecture Design
  - Status: Implemented (partial)
  - Created: 2026-06-24
  - Depends on: RFC-204 (Autopilot Mode), RFC-222 (Autopilot and Goal Engine Architecture), RFC-802 (Persistence Architecture)
  - Updated: 2026-07-03
- **RFC-230**: [Job Maturity Assessment for Autopilot Rails](RFC-230-job-maturity-assessment.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-08-05
  - Depends on: RFC-204, RFC-222, RFC-228, RFC-624, RFC-625, RFC-630
  - Authors: Soothe Team
  - Updated: 2026-08-08
- **RFC-231**: [LoopRail and Rail Exec (Composable Verb Bodies)](RFC-231-looprail-rail-exec.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-08-07
  - Depends on: RFC-204, RFC-222, RFC-228, RFC-230, RFC-625, RFC-626, RFC-630
  - Authors: Soothe Team
  - Updated: 2026-08-08
- **RFC-232**: [Flat WavePlan Wire Ingest (Semi-Structured, No Nesting)](RFC-232-waveplan-flat-semistructured-ingest.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-08-07
  - Depends on: RFC-231, RFC-204, RFC-222, RFC-625, RFC-630
  - Authors: Soothe Team
  - Updated: 2026-08-08

### Protocol Architecture (3xx)

- **RFC-300**: [Context and Memory Architecture Design](../archive/specs/RFC-300-context-memory-protocols.md) ⚠️ **ARCHIVED**
  - Kind: Architecture Design
  - Status: Archived
  - Superseded By: RFC-302 (ContextProtocol Architecture), RFC-303 (MemoryProtocol Architecture)
  - Archived Date: 2026-06-16
  - Created: 2026-03-14
- **RFC-301**: [Protocol Registry](RFC-301-protocol-registry.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-03-31
  - Depends on: RFC-001 (Core Modules Architecture), RFC-302 (Context Protocol), RFC-303 (Memory Protocol)
  - Authors: Xiaming Chen
  - Updated: 2026-03-31
- **RFC-302**: [ContextProtocol Architecture](RFC-302-context-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17
  - Depends on: RFC-000, RFC-001
- **RFC-303**: [MemoryProtocol Architecture](RFC-303-memory-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17
  - Depends on: RFC-000, RFC-302
- **RFC-304**: [PlannerProtocol Architecture](RFC-304-planner-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17
  - Depends on: RFC-000, RFC-302
  - Updated: 2026-08-08
- **RFC-305**: [PolicyProtocol Architecture](RFC-305-policy-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17
  - Depends on: RFC-000, RFC-001
  - Updated: 2026-08-08
- **RFC-306**: [DurabilityProtocol Architecture](RFC-306-durability-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-17
  - Depends on: RFC-000, RFC-001
- **RFC-307**: [IdentityProtocol Architecture](RFC-307-identity-protocol-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-06-25
  - Depends on: RFC-000, RFC-001, RFC-305

### Event & Daemon (4xx)

- **RFC-401**: [Event Processing & Filtering](RFC-401-event-processing.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-03-31
  - Depends on: RFC-450 (Daemon Communication), RFC-403 (Unified Event Naming), RFC-500 (CLI/TUI Architecture)
  - Supersedes: RFC-0015, RFC-0019, RFC-0022
  - Authors: Soothe Team
  - Updated: 2026-04-29
- **RFC-403**: [Unified Event Naming Semantics](RFC-403-unified-event-naming.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-04-15
  - Authors: Platonic Brainstorming Session
  - Updated: 2026-05-01
- **RFC-411**: [Event Stream Replay & History Reconstruction](../archive/specs/RFC-411-event-stream-replay.md) ⚠️ **ARCHIVED**
  - Kind: Architecture Design
  - Status: Archived
  - Superseded By: RFC-413
  - Archived Date: 2026-06-16
  - Created: 2026-04-22
- **RFC-412**: [MCP Management](RFC-412-mcp-management.md)
  - Kind: Implementation Interface Design
  - Status: Implemented (partial)
  - Created: 2026-05-29
  - Depends on: RFC-100 (CoreAgent Runtime), RFC-101 (Tool Interface), RFC-105 (Progressive Skill Loading), RFC-305 (Policy Protocol Architecture), RFC-600 (Plugin Extension System)
  - Authors: Platonic brainstorming session
  - Updated: 2026-07-11
- **RFC-413**: [Server-Owned Display Card Ledger](RFC-413-server-owned-display-card-ledger.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-06-04
  - Depends on: RFC-225 (Goal Record Enrichment), RFC-401 (Event Processing), RFC-403 (Unified Event Naming), RFC-411 (Event Stream Replay), RFC-503 (Loop-First UX), RFC-631 (Goal Display Snapshots)
  - Supersedes: RFC-411 (history reconstruction model)
  - Authors: xiaming (with Claude)
  - Updated: 2026-08-08
- **RFC-450**: [Unified Daemon Communication Protocol](RFC-450-daemon-communication-protocol.md)
  - Kind: Architecture Design + Protocol Specification
  - Status: Draft
  - Created: 2026-03-19
  - Depends on: RFC-000, RFC-001, RFC-500, RFC-614, RFC-403, RFC-900
  - Updated: 2026-06-28
- **RFC-452**: [Unified Thread Management Architecture](RFC-452-unified-thread-management.md)
  - Kind: Architecture Design
  - Status: Implemented (partial)
  - Created: 2026-03-22
  - Depends on: RFC-000, RFC-001, RFC-201, RFC-450, RFC-101
- **RFC-454**: [Slash Command Architecture](RFC-454-slash-command-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-16
  - Authors: Soothe contributors
  - Updated: 2026-08-08

### CLI / TUI (5xx)

- **RFC-500**: [CLI TUI Architecture Design](RFC-500-cli-tui-architecture.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-03-12
  - Updated: 2026-07-02
- **RFC-501**: [Display & Verbosity](RFC-501-display-verbosity.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-03-31
  - Depends on: RFC-500 (CLI/TUI Architecture), RFC-401 (Event Processing)
  - Supersedes: RFC-0020, RFC-0024
  - Authors: Soothe Team
  - Updated: 2026-08-08
- **RFC-502**: [Unified Presentation Engine](RFC-502-unified-presentation-engine.md)
  - Kind: Implementation Interface Design
  - Status: Implemented (partial)
  - Created: 2026-04-02
  - Depends on: RFC-401 (Event Processing), RFC-501 (Display & Verbosity), RFC-500 (CLI/TUI Architecture)
  - Authors: Soothe Team
- **RFC-503**: [Loop-First User Experience Architecture](RFC-503-loop-first-user-experience.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-22
  - Depends on: RFC-207 (Thread Lifecycle & Goal Context), RFC-450 (Daemon Communication), RFC-500 (CLI/TUI), RFC-454 (Slash Commands)
  - Authors: Claude Sonnet 4.6
- **RFC-504**: [Loop Management CLI Commands](RFC-504-loop-management-cli-commands.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-04-22
  - Depends on: RFC-503 (Loop-First UX), RFC-218 (Checkpoint Tree), RFC-454 (Slash Commands), RFC-450 (Daemon Communication Protocol)
  - Authors: Soothe contributors
- **RFC-505**: [Soothe Desktop Client Architecture](../archive/specs/RFC-505-soothe-desktop-client.md) ⚠️ **ARCHIVED**
  - Kind: Architecture Design
  - Status: Archived
  - Created: 2026-06-04

### Agent / Presentation Enhancements (6xx)

- **RFC-600**: [Plugin Extension Specification](RFC-600-plugin-extension-system.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-03-23
  - Depends on: RFC-000, RFC-001, RFC-200, RFC-302
  - Updated: 2026-03-27
- **RFC-601**: [Built-in Plugin Agents](RFC-601-built-in-agents.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-03-31
  - Depends on: RFC-600 (Plugin Extension System), RFC-301 (Protocol Registry)
  - Supersedes: RFC-0004, RFC-0005, RFC-0021
  - Authors: Soothe Team
  - Updated: 2026-04-05
- **RFC-603**: [Reasoning Quality & Progressive Actions](RFC-603-reasoning-quality-progressive-actions.md)
  - Kind: Feature Enhancement
  - Status: Draft
  - Created: 2026-04-09
  - Authors: Claude Code
  - Updated: 2026-05-04
- **RFC-604**: [Plan Phase Robustness (Three-Layer Defense)](RFC-604-reason-phase-robustness.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-04-11
  - Depends on: RFC-201 (StrangeLoop Plan-Execute Loop)
  - Authors: Claude Sonnet 4.6
  - Updated: 2026-05-05
- **RFC-605**: [Explore Subagent and Parallel Spawning](../archive/specs/RFC-605-explore-subagent-parallel-spawning.md) ⚠️ **ARCHIVED**
  - Kind: Architecture Design
  - Status: Archived
  - Superseded By: RFC-613
  - Archived Date: 2026-06-16
  - Created: 2026-04-13
- **RFC-606**: [DeepAgents CLI TUI Migration Specification](RFC-606-deepagents-cli-tui-migration.md)
  - Kind: Architecture Design + Implementation Interface Design
  - Status: Draft
  - Created: 2026-04-13
  - Depends on: RFC-000, RFC-001, RFC-302, RFC-500, RFC-501, RFC-203, RFC-303
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
  - Depends on: RFC-600, RFC-302
- **RFC-613**: [Explore Agent — LLM-Orchestrated Iterative Search](../archive/specs/RFC-613-explore-agent-llm-orchestrated-search.md) ⚠️ **ARCHIVED**
  - Kind: Architecture Design
  - Status: Archived
  - Created: 2026-04-24
- **RFC-614**: [Unified Daemon → Client Streaming Messaging Framework](RFC-614-unified-streaming-messaging.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-04-27
  - Depends on: RFC-000, RFC-001, RFC-450, RFC-401, RFC-403
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
  - Updated: 2026-07-28
- **RFC-619**: [Deep Research Subagent](RFC-619-deep-research-subagent.md)
  - Kind: Architecture Design
  - Status: Accepted
  - Created: 2026-05-21
  - Depends on: RFC-600 (Plugin Extension System), RFC-601 (Built-in Agents), RFC-403 (Unified Event Naming), RFC-616 (Scenario-Driven Synthesis)
  - Supersedes: Deep Research subagent identity (prior RFC-619 revision), Research section identity in RFC-601 §4
  - Authors: Soothe Team
  - Updated: 2026-07-07
- **RFC-620**: [Unified Channel Architecture](RFC-620-channel-architecture.md)
  - Kind: Architecture Design
  - Status: Implemented (partial)
  - Created: 2026-05-29
  - Depends on: RFC-450, RFC-0015, RFC-000
  - Authors: Xiaming Chen
  - Updated: 2026-08-11
- **RFC-621**: [Workspace Host Convention for Container Deployments](RFC-621-workspace-host-convention.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-06-02
  - Depends on: RFC-103, RFC-450
  - Authors: Platonic Coding Workflow
  - Updated: 2026-06-02
- **RFC-622**: [CoreAgent Clarification Relay](RFC-622-coreagent-clarification-relay.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-06-02
  - Depends on: RFC-220 (Agentic Goal Execution / StrangeLoop), RFC-222 (Autopilot Mode), RFC-600 (Plugin Extension System), RFC-601 (Built-in Agents), RFC-403 (Unified Event Naming)
  - Supersedes: Empty-answer auto-resume behavior currently encoded in `sloop/engine/graph_interrupt.py::build_auto_resume_payload` for `type=="ask_user"` interrupts.
  - Authors: Soothe Team
- **RFC-623**: [Veritas Auto-Mode Robustness](RFC-623-veritas-auto-mode-robustness.md)
  - Kind: Implementation Interface Design
  - Status: Draft
  - Created: 2026-06-03
  - Depends on: RFC-622 (CoreAgent Clarification Relay), RFC-220 (Agentic Goal Execution / StrangeLoop), RFC-403 (Unified Event Naming)
  - Supersedes: ---
  - Authors: Soothe Team
  - Updated: 2026-06-03
- **RFC-624**: [Context Engine](RFC-624-context-engine.md)
  - Kind: Architecture Design
  - Status: Implemented (partial)
  - Created: 2026-06-12
  - Depends on: RFC-000 (System Conceptual Design), RFC-200 (Autonomous Goal Management), RFC-201 (StrangeLoop Plan-Execute Loop), RFC-214 (Loop Message Surface), RFC-803 (Persistence Backend)
  - Updated: 2026-08-19 (RFC-904 StepDAG reconcile / status extensions)
- **RFC-625**: [AutopilotMonitor and ContextEngine Unification](RFC-625-autopilot-monitor-context-engine-unification.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-06-15
  - Depends on: RFC-624 (Context Engine), RFC-222 (Autopilot and Goal Engine Architecture), RFC-200 (Autonomous Goal Management)
  - Supersedes: RFC-200 (Goal Management) — GoalEngine deleted, features migrated to ContextEngine
  - Updated: 2026-08-11
- **RFC-626**: [Entity Model and State Management Consolidation](RFC-626-entity-model-state-consolidation.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-06-16
  - Depends on: RFC-624 (Context Engine), RFC-625 (AutopilotMonitor and ContextEngine Unification), RFC-203 (StrangeLoop State & Memory), RFC-201 (StrangeLoop Plan-Execute Loop)
  - Updated: 2026-08-11
- **RFC-627**: [Unified LLM Utilities Module](RFC-627-unified-llm-utilities.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-06-17
  - Depends on: RFC-000 (System Conceptual Design), RFC-104 (Model Knowledge Cutoff)
  - Updated: 2026-06-17
- **RFC-628**: [Cognition Step Card & SubAgent Card Display](RFC-628-step-card-display-refactor.md)
  - Kind: Implementation Interface Design
  - Status: Implemented
  - Created: 2026-06-26
  - Depends on: RFC-500 (CLI/TUI Architecture), RFC-501 (Display Verbosity), RFC-607 (Progressive Display Refinements), RFC-630 (intake-only wire stream contract for Part III)
  - Authors: Xiaming Chen
  - Updated: 2026-07-15
- **RFC-629**: [Client Library — Core Upgrade and Appkit Architecture](RFC-629-client-appkit-architecture.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-06-30
  - Depends on: RFC-450, RFC-614, RFC-403
  - Authors: Xiaming Chen
  - Updated: 2026-07-29
- **RFC-630**: [Start-Phase LLM Intake and Branch Routing](RFC-630-start-phase-llm-intake-and-branch-routing.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-06-30
  - Depends on: RFC-220, RFC-225, RFC-226, RFC-503
  - Supersedes: The `_is_likely_agentic` heuristic bypass and `simple_bypass` string-prefix detection introduced by IG-518
  - Partially Superseded By: RFC-904 (Pass 2 scope classification and complexity-tiered plan routes removed; Pass 1 retained)
  - Authors: Xiaming Chen
  - Updated: 2026-08-19
- **RFC-631**: [Goal-Bound Display Snapshots](RFC-631-goal-display-snapshots.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-07-05
  - Depends on: RFC-225 (Goal Record Enrichment), RFC-413 (Display Card Ledger), RFC-450 (Daemon Protocol), RFC-503 (Loop-First UX)
  - Authors: xiaming (with Claude)
- **RFC-632**: [Loop-Scoped Router Profile Override](RFC-632-loop-scoped-router-profile-override.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-07-14
  - Depends on: RFC-450 (Daemon Protocol — `input` / turn overrides), RFC-454 (Slash Command Architecture), RFC-500 (CLI TUI), RFC-503 (Loop-First UX), RFC-627 (LLM Utilities / ModelRouter)
  - Authors: xiaming (with Cursor)
- **RFC-633**: [Planner Plan Artifact and Human Review](RFC-633-planner-plan-artifact-and-human-review.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-07-28
  - Depends on: RFC-618, RFC-622, RFC-630, RFC-656 (IG-656 intake-only planner)
  - Authors: Soothe Team

### Product & Applications (7xx)

- **RFC-700**: [Desktop App Product Redesign](../archive/specs/RFC-700-desktop-app-product-redesign.md) ⚠️ **ARCHIVED**
  - Kind: Product Specification
  - Status: Archived
  - Superseded By: RFC-629 (client library architecture)
  - Archived Date: 2026-06-19
  - Created: 2026-04-10

### Persistence (8xx)

- **RFC-801**: [SQLite Backend Specification](RFC-801-sqlite-backend.md)
  - Kind: Architecture Design + Implementation Interface Design
  - Status: Draft
  - Created: 2026-04-04
  - Depends on: RFC-000, RFC-001, RFC-302, RFC-303, RFC-802
  - Updated: 2026-07-24
- **RFC-802**: [Persistence Architecture Refactor](RFC-802-persistence-architecture-refactor.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-22
  - Authors: Platonic Coding Workflow
  - Updated: 2026-07-24
- **RFC-803**: [StrangeLoop Checkpoint Backend Architecture](RFC-803-strangeloop-checkpoint-backend.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-04-22
  - Depends on: RFC-207 (Thread Lifecycle & Goal Context), RFC-218 (Checkpoint Tree), RFC-503 (Loop-First UX), RFC-801 (SQLite Runtime), RFC-802 (Persistence Architecture)
  - Authors: Claude Sonnet 4.6
  - Updated: 2026-07-24

### Process / Deprecation / Sloop (9xx)

- **RFC-900**: [RFC Deprecation List and Number Segment Reclassification Scheme](RFC-900-deprecation-reclassification-scheme.md)
  - Kind: Process Specification
  - Status: Implemented
  - Created: 2026-06-16
  - Authors: Soothe Team
  - Implemented: 2026-06-19
- **RFC-901**: [OperationSecurityProtocol for Workspace and Tool Execution](RFC-901-operation-security-protocol.md)
  - Kind: Architecture Design
  - Status: Implemented
  - Created: 2026-04-30
  - Depends on: RFC-102, RFC-103, RFC-305, RFC-613
- **RFC-902**: [Same-File Edit Concurrency and Optimization](RFC-902-same-file-edit-optimization.md)
  - Kind: Architecture Design
  - Status: Draft
  - Created: 2026-06-28
  - Depends on: RFC-101 (tool interface), RFC-102 (security filesystem policy), RFC-222 (autopilot goal engine)
- **RFC-903**: [Sloop Graph Topology and Node Lifecycle](RFC-903-sloop-graph-topology.md)
  - Kind: Architecture Design
  - Status: Proposed
  - Created: 2026-08-18
  - Depends on: RFC-220, RFC-604, RFC-622, RFC-633, RFC-803
- **RFC-904**: [Sloop Recursive Step Decomposition](RFC-904-sloop-recursive-decomposition.md)
  - Kind: Architecture Design
  - Status: Proposed
  - Created: 2026-08-19
  - Depends on: RFC-220, RFC-624, RFC-630, RFC-903, RFC-622, RFC-219, RFC-803

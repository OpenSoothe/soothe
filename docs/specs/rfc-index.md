# RFC Index

**Last Updated**: 2026-05-05
**Total RFCs**: 47

This index reflects the canonical RFC set and defines which files are active for architecture and implementation decisions.

---

## RFC Status Summary

| Status | Count |
|--------|-------|
| Draft | 30 |
| Implemented | 16 |

---

## RFC Catalog

### Foundation

- **RFC-000**: [System Conceptual Design](RFC-000*.md)
  - Status: Implemented
  - Created: 2026-03-12

- **RFC-001**: [Architecture Design for Core Protocol Modules](RFC-001*.md)
  - Status: Implemented
  - Created: 2026-03-12

### Core Architecture

- **RFC-200**: [Layer 3 - Autonomous Goal Management Loop](RFC-200*.md)
  - Status: Implemented
  - Created: 2026-03-15

- **RFC-201**: [AgentLoop Plan-Execute Loop Architecture](RFC-201*.md)
  - Status: Implemented
  - Created: 2026-04-17

- **RFC-203**: [AgentLoop State & Memory Architecture](RFC-203*.md)
  - Status: Draft
  - Created: 2026-04-17

- **RFC-204**: [Autopilot Mode](RFC-204*.md)
  - Status: Implemented
  - Created: 2026-04-03

- **RFC-206**: [Hierarchical Prompt Architecture](RFC-206*.md)
  - Status: Draft
  - Created: 2026-04-08

- **RFC-207**: [AgentLoop Thread Management & Goal Context](RFC-207*.md)
  - Status: Draft
  - Created: 2026-04-17

- **RFC-211**: [Layer 2 Tool Result Optimization](RFC-211*.md)
  - Status: Draft
  - Created: 2026-04-10

- **RFC-213**: [AgentLoop Reasoning Quality & Robustness](RFC-213*.md)
  - Status: Draft
  - Created: 2026-04-17

- **RFC-214**: [AgentLoop Loop Message Surface and Plan Context](RFC-214*.md)
  - Status: Draft
  - Extends: RFC-201, RFC-206, RFC-215
  - Created: 2026-05-03

- **RFC-215**: [AgentLoop Persistence Backend Architecture](RFC-215*.md)
  - Status: Draft
  - Created: 2026-04-22
  - Renamed from: RFC-409 (2026-05-03)

- **RFC-216**: [AgentLoop Multi-Thread Lifecycle](RFC-216*.md)
  - Status: Draft
  - Created: 2026-04-16
  - Renamed from: RFC-608 (2026-05-03)

- **RFC-217**: [Goal Context Management](RFC-217*.md)
  - Status: Draft
  - Created: 2026-04-17
  - Renamed from: RFC-609 (2026-05-03)

- **RFC-218**: [AgentLoop Checkpoint Tree Architecture](RFC-218*.md)
  - Status: Draft
  - Created: 2026-04-22
  - Renamed from: RFC-611 (2026-05-03)

- **RFC-219**: [Goal Completion Module](RFC-219*.md)
  - Status: Implemented
  - Created: 2026-04-28
  - Renamed from: RFC-615 (2026-05-03)

- **RFC-220**: [LangGraph Agent Loop Orchestrator](RFC-220*.md)
  - Status: Draft
  - Kind: Architecture Design — Layer 2 Loop Graph (cut-over; supersedes RFC-201 imperative driver)
  - Created: 2026-05-05
  - Supersedes draft id: RFC-620 (renumbered into 2xx AgentLoop series)

### Agent Behavior

- **RFC-300**: [Context and Memory Architecture Design](RFC-300*.md)
  - Status: Implemented
  - Created: 2026-03-14

- **RFC-301**: [Protocol Registry](RFC-301*.md)
  - Status: Implemented
  - Created: 2026-03-31

### Persistence & Durability

- **RFC-400**: [ContextProtocol Architecture](RFC-400*.md)
  - Status: Draft
  - Created: 2026-04-17

- **RFC-401**: [Event Processing & Filtering](RFC-401*.md)
  - Status: Implemented
  - Created: 2026-03-31

- **RFC-402**: [MemoryProtocol Architecture](RFC-402*.md)
  - Status: Draft
  - Created: 2026-04-17

- **RFC-403**: [Unified Event Naming Semantics](RFC-403*.md)
  - Status: Draft
  - Created: 2026-04-15

- **RFC-404**: [PlannerProtocol Architecture](RFC-404*.md)
  - Status: Draft
  - Created: 2026-04-17

- **RFC-406**: [PolicyProtocol Architecture](RFC-406*.md)
  - Status: Draft
  - Created: 2026-04-17

- **RFC-408**: [DurabilityProtocol Architecture](RFC-408*.md)
  - Status: Draft
  - Created: 2026-04-17


- **RFC-450**: [Unified Daemon Communication Protocol](RFC-450*.md)
  - Status: Implemented
  - Created: 2026-03-19

- **RFC-452**: [Unified Thread Management Architecture](RFC-452*.md)
  - Status: Draft
  - Created: 2026-03-22

- **RFC-454**: [Slash Command Architecture](RFC-454*.md)
  - Status: Draft
  - Created: 2026-04-16

- **RFC-614**: [Unified Daemon → Client Streaming Messaging Framework](RFC-614*.md)
  - Status: Draft
  - Extends: RFC-450 (Daemon Communication), RFC-401 (Event Processing)
  - See also: [IG-355](../impl/IG-355-subagent-completion-wire.md) (delegate finals / headless wire parity)
  - Created: 2026-04-27

### Daemon & Transport

- **RFC-500**: [CLI TUI Architecture Design](RFC-500*.md)
  - Status: Implemented
  - Created: 2026-03-12

- **RFC-501**: [Display & Verbosity](RFC-501*.md)
  - Status: Draft
  - Created: 2026-03-31

- **RFC-502**: [Unified Presentation Engine](RFC-502*.md)
  - Status: Draft
  - Created: 2026-04-02

- **RFC-600**: [Plugin Extension Specification](RFC-600*.md)
  - Status: Implemented
  - Created: 2026-03-23

- **RFC-601**: [Built-in Plugin Agents](RFC-601*.md)
  - Status: Implemented
  - Created: 2026-03-31

- **RFC-602**: [SQLite Backend Specification](RFC-602*.md)
  - Status: Draft
  - Created: 2026-04-04

- **RFC-603**: [Reasoning Quality & Progressive Actions](RFC-603*.md)
  - Status: Draft
  - Created: 2026-04-09

- **RFC-604**: [Plan Phase Robustness (Three-Layer Defense)](RFC-604*.md)
  - Status: Implemented
  - Created: 2026-04-11

- **RFC-605**: [Explore Subagent and Parallel Spawning](RFC-605*.md)
  - Status: Draft
  - Created: 2026-04-13

- **RFC-606**: [DeepAgents CLI TUI Migration Specification](RFC-606*.md)
  - Status: Draft
  - Created: 2026-04-13

- **RFC-607**: [Progressive Display Refinements Post-Migration: Progressive Display Refinements Post-Migration](RFC-607*.md)
  - Status: Draft
  - Scope: DisplayLine dataclass in CLI stream pipeline
  - Created: 2026-04-14

- **RFC-610**: [SDK Module Structure Refactoring](RFC-610*.md)
  - Status: Draft
  - Created: 2026-04-17

- **RFC-612**: [Persistence Architecture Refactor](RFC-612*.md)
  - Status: Draft
  - Scope: Backend storage unification, mode-based validation, in-memory removal
  - Created: 2026-04-22

---

## Recently Added

- RFC-220: LangGraph Agent Loop Orchestrator (2026-05-05; Loop Graph keyed by `loop_id`, evidence-bound plan steps, no backward compat with imperative loop; renumbered from RFC-620)
- RFC-214: AgentLoop Loop Message Surface and Plan Context (2026-05-03; plan human `Execute iteration` — 2026-05-04)
- RFC-215: AgentLoop Persistence Backend Architecture (renamed from RFC-409, 2026-05-03)
- RFC-216: AgentLoop Multi-Thread Lifecycle (renamed from RFC-608, 2026-05-03)
- RFC-217: Goal Context Management (renamed from RFC-609, 2026-05-03)
- RFC-218: AgentLoop Checkpoint Tree Architecture (renamed from RFC-611, 2026-05-03)
- RFC-219: Goal Completion Module (renamed from RFC-615, 2026-05-03)
- RFC-603: Reasoning Quality & Progressive Actions (2026-04-09)
- RFC-604: Plan Phase Robustness (Three-Layer Defense) (2026-04-11)
- RFC-605: Explore Subagent and Parallel Spawning (2026-04-13)
- RFC-606: DeepAgents CLI TUI Migration Specification (2026-04-13)
- RFC-607: Progressive Display Refinements Post-Migration: Progressive Display Refinements Post-Migration (2026-04-14)
- RFC-610: SDK Module Structure Refactoring (2026-04-17)
- RFC-612: Persistence Architecture Refactor (2026-04-22)
- RFC-614: Unified Daemon → Client Streaming Messaging Framework (2026-04-27)

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
- **RFC Template**: `docs/specs/rfc-template.md`


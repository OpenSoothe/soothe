# RFC Index

This document provides an index of all RFCs in this project.

## RFC List

### Conceptual Design

| RFC | Title | Status | Layer | Dependencies |
|-----|-------|--------|-------|--------------|
| [RFC-0001](./RFC-0001-system-conceptual-design.md) | System Conceptual Design | Draft | Foundation | - |

### Architecture Design

| RFC | Title | Status | Layer | Dependencies |
|-----|-------|--------|-------|--------------|
| [RFC-0002](./RFC-0002-core-modules-architecture.md) | Core Modules Architecture Design | Implemented | Foundation | RFC-0001 |
| [RFC-0003](./RFC-0003-cli-tui-architecture.md) | CLI TUI Architecture Design | Implemented | Foundation | RFC-0001, RFC-0002 |
| [RFC-0004](./RFC-0004-skillify-agent-architecture.md) | Skillify Agent Architecture Design | Implemented | Foundation | RFC-0001, RFC-0002, RFC-0003 |
| [RFC-0005](./RFC-0005-weaver-agent-architecture.md) | Weaver Agent Architecture Design | Implemented | Foundation | RFC-0001, RFC-0002, RFC-0003, RFC-0004 |
| [RFC-0006](./RFC-0006-context-memory-architecture.md) | Context and Memory Architecture Design | Implemented | Foundation | RFC-0001, RFC-0002, RFC-0003 |
| [RFC-0007](./RFC-0007-autonomous-goal-management-loop.md) | Layer 3: Autonomous Goal Management Loop | Revised | **Layer 3** | RFC-0001, RFC-0002, RFC-0003, RFC-0008 |
| [RFC-0008](./RFC-0008-agentic-goal-execution-loop.md) | Layer 2: Agentic Goal Execution Loop | Revised | **Layer 2** | RFC-0001, RFC-0002, RFC-0007, RFC-0023 |
| [RFC-0009](./RFC-0009-dag-based-execution.md) | DAG-Based Execution and Unified Concurrency | Draft | Foundation | RFC-0001, RFC-0002, RFC-0007 |
| [RFC-0010](./RFC-0010-failure-recovery-persistence.md) | Failure Recovery, Progressive Persistence, and Artifact Storage | Draft | Foundation | RFC-0001, RFC-0002, RFC-0007, RFC-0009 |
| [RFC-0013](./RFC-0013-daemon-communication-protocol.md) | Unified Daemon Communication Protocol for WebSocket IPC | Implemented | Foundation | RFC-0001, RFC-0002, RFC-0003 |
| [RFC-0015](./RFC-0015-progress-event-protocol.md) | Progress Event Protocol | Implemented | Foundation | RFC-0003, RFC-0013 |
| [RFC-0018](./RFC-0018-plugin-extension-system.md) | Plugin Extension Specification | Implemented | Foundation | RFC-0001, RFC-0002, RFC-0008, RFC-0013 |
| [RFC-0019](./RFC-0019-unified-event-processing.md) | Unified Event Processing Architecture | Implemented | Foundation | RFC-0003, RFC-0015 |
| [RFC-0020](./RFC-0020-event-display-architecture.md) | Event Display Architecture | Draft | Foundation | RFC-0001, RFC-0002, RFC-0003, RFC-0013, RFC-0015 |
| [RFC-0021](./RFC-0021-research-subagent.md) | Research Subagent | Implemented | Foundation | RFC-0018, RFC-0019 |
| [RFC-0022](./RFC-0022-daemon-side-event-filtering.md) | Daemon-Side Event Filtering Protocol | Implemented | Foundation | RFC-0013, RFC-0015 |
| [RFC-0023](./RFC-0023-coreagent-runtime.md) | Layer 1: CoreAgent Runtime Architecture | Draft | **Layer 1** | RFC-0001, RFC-0002 |
| [RFC-0024](./RFC-0024-verbosity-tier-unification.md) | VerbosityTier Unification | Draft | Foundation | RFC-0015 |
| [RFC-0025](./RFC-0025-tool-event-naming-unification.md) | Tool Event Naming Unification | Draft | Foundation | RFC-0015 |

### Implementation Interface Design

| RFC | Title | Status | Layer | Dependencies |
|-----|-------|--------|-------|--------------|
| [RFC-0012](./RFC-0012-secure-filesystem-policy.md) | Secure Filesystem Path Handling and Security Policy | Implemented | Foundation | RFC-0002 |
| [RFC-0016](./RFC-0016-tool-interface-optimization.md) | Tool Interface Optimization Implementation Guide | Implemented | Foundation | RFC-0001, RFC-0002, RFC-0008 |

## Reference Documents

| Document | Purpose | Lines |
|----------|---------|-------|
| [event-catalog.md](./event-catalog.md) | Complete event type registry with VerbosityTier classification | 228 |
| [rest-api-spec.md](./rest-api-spec.md) | HTTP REST API specification extracted from RFC-0013 | 453 |

## Dependency Graph

```
RFC-0001 (System Conceptual Design)
├── RFC-0002 (Core Modules)
│   ├── RFC-0003 (CLI TUI)
│   │   ├── RFC-0004 (Skillify)
│   │   │   └── RFC-0005 (Weaver)
│   │   ├── RFC-0006 (Context & Memory)
│   │   ├── RFC-0013 (Unified Daemon Protocol)
│   │   └── RFC-0019 (Unified Event Processing) [depends on RFC-0015]
│   ├── RFC-0015 (Progress Event Protocol) [depends on RFC-0003, RFC-0013]
│   │   ├── RFC-0020 (Event Display Architecture) [depends on RFC-0013]
│   │   ├── RFC-0024 (VerbosityTier Unification)
│   │   └── RFC-0025 (Tool Event Naming Unification)
│   ├── RFC-0016 (Tool Interface Optimization)
│   ├── RFC-0007 (Layer 3: Autonomous Goal Management) [Layer 3 foundation]
│   │   ├── RFC-0008 (Layer 2: Agentic Goal Execution) [Layer 2 foundation]
│   │   │   └── RFC-0023 (Layer 1: CoreAgent Runtime) [Layer 1 foundation]
│   │   ├── RFC-0009 (DAG Execution)
│   │   │   └── RFC-0010 (Failure Recovery)
│   └── RFC-0012 (Secure Filesystem) [Policy System]
└── RFC-0018 (Plugin Extension System) [depends on RFC-0008]
```

## Three-Layer Architecture Foundation

**Layer 3: Autonomous Goal Management** (RFC-0007)
- Manages goal DAGs for long-running complex workflows
- Delegates to Layer 2 for single-goal execution

**Layer 2: Agentic Goal Execution** (RFC-0008)
- Executes single goals through PLAN → ACT → JUDGE loop
- Delegates to Layer 1 for step execution

**Layer 1: CoreAgent Runtime** (RFC-0023)
- Provides execution runtime for tools/subagents
- Built on `create_soothe_agent()` → CompiledStateGraph

## RFC Status Summary

- **Total RFCs**: 23
- **Implemented**: 16
- **Revised**: 2 (RFC-0007, RFC-0008)
- **Draft**: 6 (RFC-0009, RFC-0010, RFC-0020, RFC-0023, RFC-0024, RFC-0025)
- **Deprecated**: 0 (RFC-0011 merged into RFC-0007 and removed)

## Line Count Summary (After Compaction)

All RFCs are now under the target limits:
- **Architectural RFCs**: All < 600 lines ✅
- **Specification RFCs**: All < 400 lines ✅
- **Largest RFC**: RFC-0018 at 1189 lines (needs additional work)
- **Average size**: ~378 lines

## Navigation

- [RFC Standard](./rfc-standard.md) - Specification kinds and process
- [RFC History](./rfc-history.md) - Change history
- [Terminology](./rfc-namings.md) - Naming conventions
- [RFC Optimization Strategies](/.claude/skills/platonic-coding/references/SPECS/rfc-optimization-strategies.md) - Compaction patterns

## Recent Changes (2026-03-30)

- Created RFC-0025 (Tool Event Naming Unification)
  - Establishes naming convention: atomic ops use simple verbs, async ops use started/completed/failed triplets
  - Renames `backup_created` → `backup` in file_ops tool
  - Aligns event naming with atomic verb pattern

## Recent Changes (2026-03-29)

- Updated RFC-0013 (Daemon Communication Protocol)
  - **BREAKING**: Removed Unix domain socket transport
  - Simplified to WebSocket-only bidirectional streaming
  - HTTP REST retained for health checks and CRUD operations
  - Eliminated stale socket file cleanup logic
  - Updated architecture diagram and all examples
- Created RFC-0024 (VerbosityTier Unification)
  - Replaces two-layer classification with unified VerbosityTier enum
  - Eliminates ProgressCategory and EventCategory duplicate enums
  - Simplifies classification from ~117 lines to ~25 lines
  - Uses integer comparison (`tier <= verbosity`) instead of set membership
- Updated RFC-0015 to reference RFC-0024 VerbosityTier
  - EventMeta.verbosity now uses VerbosityTier enum
  - Domain defaults use tier values (QUIET, NORMAL, DETAILED, DEBUG, INTERNAL)
- Updated RFC-0020 to use VerbosityTier classification
  - Event registration examples now use VerbosityTier values
  - Verbosity behavior tables updated to tier-based visibility
- Updated RFC-0022 daemon-side filtering to use VerbosityTier
  - VerbosityLevel values changed: `minimal` → `quiet`
  - Import paths updated to verbosity_tier.py
- Updated event-catalog.md to use VerbosityTier column headers
- Established three-layer architecture foundation
- Revised RFC-0007 (Layer 3: Autonomous Goal Management Loop)
- Revised RFC-0008 (Layer 2: Agentic Goal Execution Loop)
  - Added execution hints integration with Layer 1 (§3.2)
  - Fixed RFC-0023 dependency reference
- Created RFC-0023 (Layer 1: CoreAgent Runtime Architecture)
  - Added Layer 2 integration contract with execution hints specification (§4)
  - Added ExecutionHintsMiddleware documentation (§3)
- Removed RFC-0011 (merged into RFC-0007, content in §5.4-5.6)
- Updated RFC-0001 with three-layer principle
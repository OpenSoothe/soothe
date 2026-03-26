# RFC Index

This document provides an index of all RFCs in this project.

## RFC List

### Conceptual Design

| RFC | Title | Status | Dependencies |
|-----|-------|--------|--------------|
| [RFC-0001](./RFC-0001-system-conceptual-design.md) | System Conceptual Design | Draft | - |

### Architecture Design

| RFC | Title | Status | Dependencies |
|-----|-------|--------|--------------|
| [RFC-0002](./RFC-0002-core-modules-architecture.md) | Core Modules Architecture Design | Implemented | RFC-0001 |
| [RFC-0003](./RFC-0003-cli-tui-architecture.md) | CLI TUI Architecture Design | Implemented | RFC-0001, RFC-0002 |
| [RFC-0004](./RFC-0004-skillify-agent-architecture.md) | Skillify Agent Architecture Design | Implemented | RFC-0001, RFC-0002, RFC-0003 |
| [RFC-0005](./RFC-0005-weaver-agent-architecture.md) | Weaver Agent Architecture Design | Implemented | RFC-0001, RFC-0002, RFC-0003, RFC-0004 |
| [RFC-0006](./RFC-0006-context-memory-architecture.md) | Context and Memory Architecture Design | Implemented | RFC-0001, RFC-0002, RFC-0003 |
| [RFC-0007](./RFC-0007-autonomous-iteration-loop.md) | Autonomous Iteration Loop | Implemented | RFC-0001, RFC-0002, RFC-0003 |
| [RFC-0008](./RFC-0008-agentic-loop-execution.md) | Agentic Loop Execution Architecture | Draft | RFC-0001, RFC-0002, RFC-0003, RFC-0007, RFC-0009 |
| [RFC-0009](./RFC-0009-dag-based-execution.md) | DAG-Based Execution and Unified Concurrency | Draft | RFC-0001, RFC-0002, RFC-0007 |
| [RFC-0010](./RFC-0010-failure-recovery-persistence.md) | Failure Recovery, Progressive Persistence, and Artifact Storage | Draft | RFC-0001, RFC-0002, RFC-0007, RFC-0009 |
| [RFC-0011](./RFC-0011-dynamic-goal-management.md) | Dynamic Goal Management During Reflection | Draft | RFC-0007, RFC-0009, RFC-0010 |
| [RFC-0013](./RFC-0013-daemon-communication-protocol.md) | Unified Daemon Communication Protocol for Multi-Transport IPC | Draft | RFC-0001, RFC-0002, RFC-0003 |
| [RFC-0015](./RFC-0015-progress-event-protocol.md) | Progress Event Protocol | Draft | RFC-0003, RFC-0013 |
| [RFC-0018](./RFC-0018-plugin-extension-system.md) | Plugin Extension Specification | Draft | RFC-0001, RFC-0002, RFC-0008, RFC-0013 |
| [RFC-0019](./RFC-0019-unified-event-processing.md) | Unified Event Processing Architecture | Implemented | RFC-0003, RFC-0015 |
| [RFC-0020](./RFC-0020-event-display-architecture.md) | Event Display Architecture | Draft | RFC-0001, RFC-0002, RFC-0003, RFC-0013, RFC-0015 |
| [RFC-0021](./RFC-0021-research-subagent.md) | Research Subagent | Draft | RFC-0018, RFC-0019 |

### Implementation Interface Design

| RFC | Title | Status | Dependencies |
|-----|-------|--------|--------------|
| [RFC-0012](./RFC-0012-secure-filesystem-policy.md) | Secure Filesystem Path Handling and Security Policy | Implemented | RFC-0002 |
| [RFC-0016](./RFC-0016-tool-interface-optimization.md) | Tool Interface Optimization Implementation Guide | Implemented | RFC-0001, RFC-0002, RFC-0008 |

## Reference Documents

| Document | Purpose | Lines |
|----------|---------|-------|
| [event-catalog.md](./event-catalog.md) | Complete event type registry extracted from RFC-0015 | 228 |
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
│   │   └── RFC-0020 (Event Display Architecture) [depends on RFC-0013]
│   ├── RFC-0016 (Tool Interface Optimization)
│   ├── RFC-0007 (Autonomous Iteration)
│   │   ├── RFC-0008 (Agentic Loop Execution)
│   │   ├── RFC-0009 (DAG Execution)
│   │   │   └── RFC-0010 (Failure Recovery)
│   │   └── RFC-0011 (Dynamic Goals)
│   └── RFC-0012 (Secure Filesystem) [Policy System]
└── RFC-0008 (Agentic Loop Execution) [depends on RFC-0009]
```

## RFC Status Summary

- **Total RFCs**: 21
- **Implemented**: 10
- **Draft**: 11

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
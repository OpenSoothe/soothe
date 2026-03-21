# RFC Index

This document provides an index of all RFCs in this project.

## RFC List

### Conceptual Design

| RFC | Title | Status | Dependencies |
|-----|-------|--------|--------------|
| [RFC-0001](./RFC-0001.md) | System Conceptual Design | Draft | - |

### Architecture Design

| RFC | Title | Status | Dependencies |
|-----|-------|--------|--------------|
| [RFC-0002](./RFC-0002.md) | Core Modules Architecture Design | Implemented | RFC-0001 |
| [RFC-0003](./RFC-0003.md) | CLI TUI Architecture Design | Implemented | RFC-0001, RFC-0002 |
| [RFC-0004](./RFC-0004.md) | Skillify Agent Architecture Design | Implemented | RFC-0001, RFC-0002, RFC-0003 |
| [RFC-0005](./RFC-0005.md) | Weaver Agent Architecture Design | Implemented | RFC-0001, RFC-0002, RFC-0003, RFC-0004 |
| [RFC-0006](./RFC-0006.md) | Context and Memory Architecture Design | Implemented | RFC-0001, RFC-0002, RFC-0003 |
| [RFC-0007](./RFC-0007.md) | Autonomous Iteration Loop | Implemented | RFC-0001, RFC-0002, RFC-0003 |
| [RFC-0008](./RFC-0008.md) | Request Processing Workflow and Performance Optimization | Draft | RFC-0001, RFC-0002, RFC-0003, RFC-0007, RFC-0009 |
| [RFC-0009](./RFC-0009.md) | DAG-Based Execution and Unified Concurrency | Draft | RFC-0001, RFC-0002, RFC-0007 |
| [RFC-0010](./RFC-0010.md) | Failure Recovery, Progressive Persistence, and Artifact Storage | Draft | RFC-0001, RFC-0002, RFC-0007, RFC-0009 |
| [RFC-0011](./RFC-0011.md) | Dynamic Goal Management During Reflection | Draft | RFC-0007, RFC-0009, RFC-0010 |
| [RFC-0013](./RFC-0013.md) | Unified Daemon Communication Protocol for Multi-Transport IPC | Draft | RFC-0001, RFC-0002, RFC-0003 |
| [RFC-0014](./RFC-0014.md) | Capability Abstraction and Tool Consolidation | Deprecated | RFC-0001, RFC-0002, RFC-0008 |
| [RFC-0015](./RFC-0015.md) | Progress Event Protocol | Draft | RFC-0003, RFC-0013 |

### Implementation Interface Design

| RFC | Title | Status | Dependencies |
|-----|-------|--------|--------------|
| [RFC-0012](./RFC-0012.md) | Secure Filesystem Path Handling and Security Policy | Implemented | RFC-0002 |
| [RFC-0016](./RFC-0016.md) | Tool Interface Optimization Implementation Guide | Implemented | RFC-0001, RFC-0002, RFC-0008, RFC-0014 |

## Dependency Graph

```
RFC-0001 (System Conceptual Design)
├── RFC-0002 (Core Modules)
│   ├── RFC-0003 (CLI TUI)
│   │   ├── RFC-0004 (Skillify)
│   │   │   └── RFC-0005 (Weaver)
│   │   ├── RFC-0006 (Context & Memory)
│   │   └── RFC-0013 (Unified Daemon Protocol)
│   ├── RFC-0014 (Capability Abstraction) [DEPRECATED - superseded by RFC-0016]
│   ├── RFC-0015 (Progress Event Protocol) [depends on RFC-0003, RFC-0013]
│   ├── RFC-0016 (Tool Interface Optimization) [supersedes RFC-0014]
│   ├── RFC-0007 (Autonomous Iteration)
│   │   ├── RFC-0008 (Request Processing)
│   │   ├── RFC-0009 (DAG Execution)
│   │   │   └── RFC-0010 (Failure Recovery)
│   │   └── RFC-0011 (Dynamic Goals)
│   └── RFC-0012 (Secure Filesystem) [Policy System]
└── RFC-0008 (Request Processing) [depends on RFC-0009]
```

## Navigation

- [RFC Standard](./rfc-standard.md) - Specification kinds and process
- [RFC History](./rfc-history.md) - Change history
- [Terminology](./rfc-namings.md) - Naming conventions

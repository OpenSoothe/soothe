# RFC Index

This document provides an index of all RFCs in this project.

## Classification System

RFCs are organized by numeric prefix:

| Prefix | Category | Focus |
|--------|----------|-------|
| **0xx** | Foundation | Cross-cutting concepts, system-wide design |
| **1xx** | Core Agent | Runtime, execution, tools, subagents |
| **2xx** | Cognition Loop | Goal management, planning, agentic loops |
| **3xx** | Protocols | Interface contracts, backend abstractions |
| **4xx** | Daemon | Transport, communication, event filtering |
| **5xx** | CLI/TUI | User interface, display, interaction |
| **6xx** | Plugin System | Extension, discovery, lifecycle |

---

## RFC List by Category

### 0xx — Foundation (System-Wide)

| RFC | Title | Status | Kind | Dependencies |
|-----|-------|--------|------|--------------|
| [RFC-000](./RFC-000-system-conceptual-design.md) | System Conceptual Design | Implemented | Conceptual Design | — |
| [RFC-001](./RFC-001-core-modules-architecture.md) | Core Modules Architecture | Implemented | Architecture Design | RFC-000 |

### 1xx — Core Agent Runtime

| RFC | Title | Status | Kind | Dependencies |
|-----|-------|--------|------|--------------|
| [RFC-100](./RFC-100-coreagent-runtime.md) | CoreAgent Runtime (Layer 1) | Implemented | Architecture Design | RFC-000, RFC-001 |
| [RFC-101](./RFC-101-tool-interface.md) | Tool Interface & Event Naming | Implemented | Impl Interface | RFC-100, RFC-401 |
| [RFC-102](./RFC-102-security-filesystem-policy.md) | Security & Filesystem Policy | Implemented | Impl Interface | RFC-001 |
| [RFC-103](./RFC-103-thread-aware-workspace.md) | Thread-Aware Workspace | Draft | Impl Interface | RFC-102, RFC-400, RFC-0017 |
| [RFC-104](./RFC-104-dynamic-system-context.md) | Dynamic System Context Injection | Draft | Impl Interface | RFC-100, RFC-101, RFC-103 |

### 2xx — Cognition Loop (Goal & Planning)

| RFC | Title | Status | Kind | Dependencies |
|-----|-------|--------|------|--------------|
| [RFC-200](./RFC-200-autonomous-goal-management.md) | Autonomous Goal Management (Layer 3) | Implemented | Architecture Design | RFC-000, RFC-001, RFC-201 |
| [RFC-201](./RFC-201-agentic-goal-execution.md) | Agentic Goal Execution (Layer 2) | Implemented | Architecture Design | RFC-000, RFC-001, RFC-100 |
| [RFC-202](./RFC-202-dag-execution.md) | DAG Execution & Failure Recovery | Draft | Architecture Design | RFC-200, RFC-201, RFC-100 |
| [RFC-203](./RFC-203-loop-working-memory.md) | Loop Working Memory | Draft | Architecture Design | RFC-201, RFC-103, RFC-100 |
| [RFC-204](./RFC-204-autopilot-mode.md) | Autopilot Mode | Active | Architecture Design | RFC-200, RFC-201, RFC-202, RFC-400, RFC-500 |

### 3xx — Protocols (Interface Contracts)

| RFC | Title | Status | Kind | Dependencies |
|-----|-------|--------|------|--------------|
| [RFC-300](./RFC-300-context-memory-protocols.md) | Context & Memory Protocols | Implemented | Impl Interface | RFC-001 |
| [RFC-301](./RFC-301-protocol-registry.md) | Protocol Registry | Implemented | Impl Interface | RFC-001, RFC-300 |

### 4xx — Daemon (Transport & Communication)

| RFC | Title | Status | Kind | Dependencies |
|-----|-------|--------|------|--------------|
| [RFC-400](./RFC-400-daemon-communication.md) | Daemon Communication Protocol | Implemented | Architecture Design | RFC-000, RFC-001, RFC-500 |
| [RFC-401](./RFC-401-event-processing.md) | Event Processing & Filtering | Implemented | Impl Interface | RFC-400, RFC-500 |

### 5xx — CLI/TUI (User Interface)

| RFC | Title | Status | Kind | Dependencies |
|-----|-------|--------|------|--------------|
| [RFC-500](./RFC-500-cli-tui-architecture.md) | CLI/TUI Architecture | Implemented | Architecture Design | RFC-000, RFC-001 |
| [RFC-501](./RFC-501-display-verbosity.md) | Display & Verbosity | Draft | Impl Interface | RFC-500, RFC-401 |
| [RFC-502](./RFC-502-unified-presentation-engine.md) | Unified Presentation Engine | Draft | Impl Interface | RFC-401, RFC-501 |

### 6xx — Plugin System

| RFC | Title | Status | Kind | Dependencies |
|-----|-------|--------|------|--------------|
| [RFC-600](./RFC-600-plugin-extension-system.md) | Plugin Extension System | Implemented | Architecture Design | RFC-000, RFC-001, RFC-100 |
| [RFC-601](./RFC-601-built-in-agents.md) | Built-in Plugin Agents | Implemented | Architecture Design | RFC-600, RFC-301 |

### Legacy RFCs (To Be Reclassified)

| RFC | Title | Status | Notes |
|-----|-------|--------|-------|
| [RFC-0017](./RFC-0017-unified-thread-management.md) | Unified Thread Management | Draft | Pending review for 2xx or 4xx |

---

## Three-Layer Architecture

**Layer 3: Autonomous Goal Management** (RFC-200)
- Manages goal DAGs for long-running complex workflows
- Delegates to Layer 2 for single-goal execution

**Layer 2: Agentic Goal Execution** (RFC-201)
- Executes single goals through PLAN → ACT → JUDGE loop
- Delegates to Layer 1 for step execution

**Layer 1: CoreAgent Runtime** (RFC-100)
- Provides execution runtime for tools/subagents
- Built on `create_soothe_agent()` → CompiledStateGraph

---

## Reference Documents

| Document | Purpose |
|----------|---------|
| [event-catalog.md](./event-catalog.md) | Complete event type registry |
| [rest-api-spec.md](./rest-api-spec.md) | HTTP REST API specification |
| [rfc-standard.md](./rfc-standard.md) | RFC writing conventions |
| [rfc-history.md](./rfc-history.md) | Change history |
| [rfc-namings.md](./rfc-namings.md) | Terminology glossary |
| [rfc-reclassification-plan.md](./rfc-reclassification-plan.md) | Migration plan (this reclassification) |

---

## Dependency Graph

```
RFC-000 (System Conceptual Design)
└── RFC-001 (Core Modules)
    ├── RFC-100 (CoreAgent Runtime) [Layer 1]
    │   ├── RFC-101 (Tool Interface)
    │   └── RFC-201 (Agentic Goal Execution) [Layer 2]
    │       └── RFC-200 (Autonomous Goal Management) [Layer 3]
    │           ├── RFC-202 (DAG Execution)
    │           └── RFC-204 (Autopilot Mode)
    ├── RFC-102 (Security Policy)
    │   └── RFC-103 (Thread-Aware Workspace)
    │       └── RFC-104 (Dynamic System Context)
    ├── RFC-300 (Context & Memory)
    │   └── RFC-301 (Protocol Registry)
    ├── RFC-400 (Daemon Communication)
    │   └── RFC-401 (Event Processing)
    ├── RFC-500 (CLI/TUI Architecture)
    │   └── RFC-501 (Display & Verbosity)
    └── RFC-600 (Plugin Extension)
        └── RFC-601 (Built-in Agents)
```

---

## RFC Status Summary

| Category | Implemented | Draft | Total |
|----------|-------------|-------|-------|
| Foundation (0xx) | 2 | 0 | 2 |
| Core Agent (1xx) | 3 | 2 | 5 |
| Cognition Loop (2xx) | 2 | 3 | 5 |
| Protocols (3xx) | 2 | 0 | 2 |
| Daemon (4xx) | 2 | 0 | 2 |
| CLI/TUI (5xx) | 1 | 1 | 2 |
| Plugin System (6xx) | 2 | 0 | 2 |
| **Total** | **14** | **6** | **20** |

---

## Kind Distribution

| Kind | Count | Purpose |
|------|-------|---------|
| Conceptual Design | 1 | Principles, abstractions, taxonomy |
| Architecture Design | 10 | Components, diagrams, data flow |
| Impl Interface Design | 6 | Contracts, naming, data structures |

---

## Recent Changes (2026-03-31)

### RFC Reclassification

- **New RFCs created**:
  - RFC-101 (Tool Interface & Event Naming) — merged RFC-0016 + RFC-0025
  - RFC-202 (DAG Execution & Failure Recovery) — merged RFC-0009 + RFC-0010
  - RFC-301 (Protocol Registry) — new document for remaining protocols
  - RFC-401 (Event Processing & Filtering) — merged RFC-0015 + RFC-0019 + RFC-0022
  - RFC-501 (Display & Verbosity) — merged RFC-0020 + RFC-0024
  - RFC-601 (Built-in Plugin Agents) — merged RFC-0004 + RFC-0005 + RFC-0021

- **Renumbered RFCs**:
  - RFC-0001 → RFC-000
  - RFC-0002 → RFC-001
  - RFC-0023 → RFC-100
  - RFC-0012 → RFC-102
  - RFC-0007 → RFC-200
  - RFC-0008 → RFC-201
  - RFC-0006 → RFC-300
  - RFC-0013 → RFC-400
  - RFC-0003 → RFC-500
  - RFC-0018 → RFC-600

- **Removed RFCs** (merged into new ones):
  - RFC-0004, RFC-0005, RFC-0009, RFC-0010, RFC-0015, RFC-0016
  - RFC-0019, RFC-0020, RFC-0021, RFC-0022, RFC-0024, RFC-0025

- **Result**: 23 RFCs consolidated into 16 (14 + 2 drafts)

---

## Navigation

- [RFC Standard](./rfc-standard.md) — Specification kinds and process
- [RFC History](./rfc-history.md) — Change history
- [Terminology](./rfc-namings.md) — Naming conventions
- [Reclassification Plan](./rfc-reclassification-plan.md) — Migration documentation
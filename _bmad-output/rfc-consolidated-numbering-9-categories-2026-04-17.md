# Proposed RFC Numbering Scheme - Consolidated (≤9 Categories)

**Objective**: Reduce from 13 categories to ≤9 while maintaining layer-based architectural clarity
**Principle**: Merge related categories while preserving three-layer architecture integrity

---

## Consolidated RFC Category Structure (9 Categories)

### 0XX: Foundation & Conceptual

**Purpose**: System-wide conceptual design, principles, terminology, protocol registry

```
RFC-000: System Conceptual Design
RFC-001: Architectural Principles & Core Abstractions
RFC-002: Protocol Registry & Resolution
RFC-003: Terminology & Taxonomy
RFC-004: RFC Standard & Lifecycle
```

---

### 1XX: Layer 1 - CoreAgent Runtime

**Purpose**: CoreAgent foundation, tool execution, message handling, workspace isolation

```
RFC-100: CoreAgent Runtime Foundation
RFC-101: Tool Interface & Execution
RFC-102: Tool Context Injection Middleware
RFC-103: Thread-Aware Workspace
RFC-104: Dynamic System Context (AGENTS.md)
RFC-105: Message Optimization & Compression
RFC-106: Message Type Separation
RFC-107: Executor Thread Isolation (LangGraph Native)
RFC-108: CoreAgent Checkpoint Integration
```

---

### 2XX: Layer 2 - AgentLoop (Agentic Goal Execution)

**Purpose**: AgentLoop Plan-Execute loop, working memory, state management, thread lifecycle

```
RFC-200: AgentLoop Plan-Execute Loop (Core)
RFC-201: AgentDecision & Batch Execution
RFC-202: PlanResult & Goal-Directed Evaluation
RFC-203: Loop Working Memory (Bounded Scratchpad)
RFC-204: Loop State & Wave Metrics
RFC-205: Loop Unified State Checkpoint
RFC-206: Prompt Architecture (Plan/Execute Prompts)
RFC-207: Thread Lifecycle & Multi-Thread Spanning
RFC-208: Goal Context Manager
RFC-209: Thread Relationship Module
RFC-210: Executor Thread Coordination
RFC-211: Tool Result Optimization & Evidence Flow
RFC-212: Subagent Parallel Spawning
RFC-213: Reasoning Quality Progressive Actions
RFC-214: Reason Phase Robustness (Two-Phase Plan)
```

---

### 3XX: Layer 3 - GoalEngine (Autonomous Goal Management)

**Purpose**: GoalEngine DAG management, backoff reasoning, autopilot, goal scheduling

```
RFC-300: GoalEngine Goal DAG Management
RFC-301: GoalDirective Dynamic Restructuring
RFC-302: GoalBackoffReasoner (LLM-Driven Backoff)
RFC-303: Goal Scheduling & DAG Dependencies
RFC-304: Autopilot Mode & Goal Discovery
RFC-305: Goal File Format (GOAL.md)
RFC-306: Goal Status Tracking
RFC-307: Goal Safety Mechanisms (Cycle Detection, Depth Limits)
```

---

### 4XX: Core Protocols

**Purpose**: All core protocols (Context, Memory, Planner, Policy, Durability, RemoteAgent) in unified category

**Rationale**: Protocols are architectural building blocks used across all layers. Consolidation enables unified protocol registry and cross-layer protocol references.

```
RFC-400: ContextProtocol (Unbounded Knowledge Accumulator)
RFC-401: ContextRetrievalModule (Goal-Centric Retrieval)
RFC-402: MemoryProtocol (Cross-Thread Long-Term Memory)
RFC-403: Context vs Memory Separation Principles
RFC-404: PlannerProtocol (Plan Creation & Revision)
RFC-405: Two-Phase Plan Architecture (StatusAssessment + PlanGeneration)
RFC-406: PolicyProtocol (Permission Checking)
RFC-407: Permission Structure & Scope Matching
RFC-408: DurabilityProtocol (Thread Lifecycle Persistence)
RFC-409: CheckpointEnvelope (Progressive Persistence)
RFC-410: RemoteAgentProtocol (Remote Invocation)
RFC-411: LangGraphRemoteAgent Implementation
RFC-412: ACP Remote Agent (Planned)
RFC-413: A2A Remote Agent (Planned)
```

**Protocol Module Integration**: RFC-001 currently contains 8 protocol modules. Consolidation distributes them across 4XX range while maintaining modular structure.

---

### 5XX: Concurrency & Execution Control

**Purpose**: Concurrency management, DAG execution, step scheduling, execution bounds

```
RFC-500: ConcurrencyController (Hierarchical Semaphore)
RFC-501: StepScheduler (DAG-Based Step Execution)
RFC-502: ConcurrencyPolicy Configuration
RFC-503: DAG Execution Flow (Step & Goal Parallelism)
RFC-504: Execution Bounds & Circuit Breakers
RFC-505: RunArtifactStore (Structured Run Directory)
```

---

### 6XX: Plugin & Event System

**Purpose**: Plugin architecture, event registration, skills, built-in agents

**Rationale**: Plugins and events are tightly coupled (events registered by plugins). Consolidation simplifies extension system architecture.

```
RFC-600: Plugin Extension System
RFC-601: Event Registration API
RFC-602: Event Processing & Filtering
RFC-603: Unified Event Naming
RFC-604: Event Catalog & Stream Definitions
RFC-605: Tool Plugin Architecture
RFC-606: Subagent Plugin Architecture
RFC-607: Skills Middleware & SKILL.md Discovery
RFC-608: Built-in Agents & Skills
```

---

### 7XX: Daemon & Communication

**Purpose**: Daemon server, multi-transport communication, WebSocket, lifecycle commands

```
RFC-700: Daemon Communication Protocol
RFC-701: Multi-Transport Server (Unix Socket, WebSocket, HTTP REST)
RFC-702: WebSocket Keepalive & Connection Management
RFC-703: Daemon-CLI Lifecycle Commands (start/stop/status/doctor)
RFC-704: Message Router & Request Handling
```

---

### 8XX: CLI/TUI Interface

**Purpose**: CLI/TUI architecture, display engine, slash commands, user interaction

**Rationale**: CLI/TUI and slash commands are user-facing interface layers. Consolidation provides unified interface category.

```
RFC-800: CLI/TUI Architecture
RFC-801: Display Verbosity Levels
RFC-802: Unified Presentation Engine
RFC-803: Progressive Display Refinements
RFC-804: TUI Step Tree Display & Visualization
RFC-805: Deepagents CLI/TUI Migration
RFC-806: Slash Command Architecture
RFC-807: Command Routing & Integration
```

---

## Category Summary (9 Total)

| Category | Range | Focus | RFC Count Estimate |
|----------|-------|-------|--------------------|
| **Foundation** | 0XX | Conceptual, principles, registry | 5 |
| **Layer 1** | 1XX | CoreAgent runtime | 9 |
| **Layer 2** | 2XX | AgentLoop execution | 15 |
| **Layer 3** | 3XX | GoalEngine management | 8 |
| **Core Protocols** | 4XX | Cross-layer protocol building blocks | 14 |
| **Concurrency** | 5XX | Execution control, DAG scheduling | 6 |
| **Plugin & Events** | 6XX | Extension system, event registration | 9 |
| **Daemon** | 7XX | Server, communication, transports | 5 |
| **CLI/TUI** | 8XX | User interface, commands, display | 8 |

**Total Categories**: 9
**Total RFCs Estimate**: ~75

---

## Consolidation Decisions

### Merged Categories

| Original Categories | Consolidated Into | Rationale |
|--------------------|-------------------|-----------|
| 5XX (Context & Memory) + 6XX (Planning & Policy) + 7XX (Durability) + 8XX (Remote) | **4XX Core Protocols** | Protocols are architectural primitives used across layers. Unified protocol registry simplifies cross-references. |
| 9XX (Plugin) + 10XX (Events) | **6XX Plugin & Events** | Plugins register events; tight coupling. Single extension system category. |
| 12XX (CLI/TUI) + 13XX (Slash Commands) | **8XX CLI/TUI Interface** | User-facing interface layer. Commands integrate with CLI/TUI display. |

### Preserved Categories

| Category | Reason for Preservation |
|----------|------------------------|
| **0XX Foundation** | Essential conceptual layer, system-wide scope |
| **1XX Layer 1** | CoreAgent runtime, distinct architectural layer |
| **2XX Layer 2** | AgentLoop, distinct architectural layer, most complex |
| **3XX Layer 3** | GoalEngine, distinct architectural layer |
| **4XX Core Protocols** | Unified protocol primitives, cross-layer foundation |
| **5XX Concurrency** | Execution control distinct from layers and protocols |
| **7XX Daemon** | Server infrastructure distinct from user interface |

---

## Benefits of Consolidated Scheme

### ✅ Architectural Clarity

- **Layer ranges preserved**: 1XX (L1), 2XX (L2), 3XX (L3)
- **Protocol unity**: All protocols in 4XX range (cross-layer building blocks)
- **Infrastructure grouping**: Concurrency (5XX), Daemon (7XX), Plugin/Events (6XX)
- **Interface layer**: CLI/TUI + Commands unified in 8XX

### ✅ Category Reduction

- **From 13 → 9 categories** (30% reduction)
- **Simplified navigation**: Fewer categories to search
- **Logical grouping**: Related RFCs co-located

### ✅ Protocol Consolidation Benefits

- **Unified protocol registry**: All protocols searchable in 4XX
- **Cross-layer clarity**: Protocols span all layers (4XX indicates cross-layer)
- **Modular RFC-001 resolution**: Split RFC-001 into 4XX protocol RFCs systematically

---

## Current-to-New RFC Mapping (Consolidated)

### Foundation (0XX) - Unchanged

| Current | New | Action |
|---------|-----|--------|
| RFC-000 | RFC-000 | ✅ Unchanged |
| RFC-001 (part) | RFC-001-004 | ✅ Split conceptual content |

### Layer 1 (1XX) - Unchanged

| Current | New | Action |
|---------|-----|--------|
| RFC-100 | RFC-100 | ✅ Unchanged |
| RFC-101-104 | RFC-101-104 | ✅ Unchanged |

### Layer 2 (2XX) - Renumbered from scattered

| Current | New | Action |
|---------|-----|--------|
| RFC-201 | RFC-200 | ✅ Renumbered (AgentLoop core) |
| RFC-203 | RFC-203 | ✅ Unchanged |
| RFC-205 | RFC-205 | ✅ Unchanged |
| RFC-603-604 | RFC-213-214 | ✅ Renumbered |
| RFC-608-609 | RFC-207-209 | ✅ Renumbered |

### Layer 3 (3XX) - Renumbered

| Current | New | Action |
|---------|-----|--------|
| RFC-200 | RFC-300 | ✅ Renumbered (GoalEngine core) |
| RFC-204 | RFC-304 | ✅ Renumbered |

### Core Protocols (4XX) - Extracted from RFC-001

| Current | New | Protocol Module |
|---------|-----|-----------------|
| RFC-001 Module 1 | RFC-400-401 | ContextProtocol + RetrievalModule |
| RFC-001 Module 2 | RFC-402-403 | MemoryProtocol + Separation |
| RFC-001 Module 3 | RFC-404-405 | PlannerProtocol + Two-Phase |
| RFC-001 Module 4 | RFC-406-407 | PolicyProtocol + Permissions |
| RFC-001 Module 5 | RFC-408-409 | DurabilityProtocol + CheckpointEnvelope |
| RFC-001 Module 6 | RFC-410-413 | RemoteAgentProtocol + Implementations |
| RFC-001 Module 8 | RFC-505 | VectorStoreProtocol (moved to Concurrency) |
| RFC-001 Module 9 | - | PersistStore (implementation detail) |

### Concurrency (5XX) - Renumbered/Split

| Current | New | Action |
|---------|-----|--------|
| RFC-202 (ConcurrencyController) | RFC-500 | ✅ Renumbered |
| RFC-202 (StepScheduler) | RFC-501 | ✅ Split |
| RFC-202 (RunArtifactStore) | RFC-505 | ✅ Split |
| RFC-001 Module 8 | RFC-506 | VectorStoreProtocol |

### Plugin & Events (6XX) - Renumbered/Consolidated

| Current | New | Action |
|---------|-----|--------|
| RFC-600 | RFC-600 | ✅ Unchanged (Plugin core) |
| RFC-401 (Events) | RFC-602 | ✅ Renumbered |
| RFC-403 (Event Naming) | RFC-603 | ✅ Renumbered |
| RFC-601 | RFC-608 | ✅ Renumbered |
| RFC-605-608 | RFC-605-608 | ✅ Unchanged/renumbered |

### Daemon (7XX) - Renumbered

| Current | New | Action |
|---------|-----|--------|
| RFC-400 | RFC-700 | ✅ Renumbered |
| RFC-602 | RFC-702 | ✅ Renumbered |
| RFC-606-607 | RFC-703-704 | ✅ Renumbered |

### CLI/TUI (8XX) - Renumbered/Consolidated

| Current | New | Action |
|---------|-----|--------|
| RFC-500 | RFC-800 | ✅ Renumbered |
| RFC-501-502 | RFC-801-802 | ✅ Renumbered |
| RFC-607 | RFC-803 | ✅ Renumbered |
| RFC-404 | RFC-806 | Slash Commands |

---

## Migration Strategy (No Breaking Changes)

### Phase 1: Create Aliases (Preserve Current Numbers)

For each renumbered RFC, create alias:

```markdown
# RFC-201 (Alias)

**Status**: Alias - See RFC-200 for current version
**Redirect**: Renumbered to RFC-200 (AgentLoop Plan-Execute Loop)
**Reason**: Layer-based categorization consolidation

See: [RFC-200: AgentLoop Plan-Execute Loop](./RFC-200-agentloop-plan-execute-loop.md)
```

### Phase 2: Update Cross-References

- Update RFC-000 dependencies
- Update all RFC text references
- Update IG implementation guide references

### Phase 3: Update Index Documents

- `rfc-index.md`: Add both current and new numbers
- `rfc-history.md`: Document reorganization
- `rfc-namings.md`: Update terminology

### Phase 4: Deprecate Aliases

Mark aliases as "Alias - Superseded" after migration complete.

---

## Comparison: Original vs Consolidated

### Original Proposal (13 Categories)

| Category | Range | RFCs |
|----------|-------|------|
| Foundation | 0XX | 5 |
| Layer 1 | 1XX | 9 |
| Layer 2 | 2XX | 15 |
| Layer 3 | 3XX | 8 |
| Concurrency | 4XX | 6 |
| Context & Memory | 5XX | 6 |
| Planning & Policy | 6XX | 6 |
| Durability | 7XX | 6 |
| Remote Agents | 8XX | 5 |
| Plugin | 9XX | 6 |
| Events | 10XX | 4 |
| Daemon | 11XX | 4 |
| CLI/TUI | 12XX | 6 |
| Commands | 13XX | 2 |

**Total**: 13 categories, ~82 RFCs

### Consolidated Proposal (9 Categories)

| Category | Range | RFCs | Reduction |
|----------|-------|------|-----------|
| Foundation | 0XX | 5 | Unchanged |
| Layer 1 | 1XX | 9 | Unchanged |
| Layer 2 | 2XX | 15 | Unchanged |
| Layer 3 | 3XX | 8 | Unchanged |
| **Core Protocols** | 4XX | 14 | Merged 5XX-8XX protocols |
| Concurrency | 5XX | 6 | Unchanged |
| **Plugin & Events** | 6XX | 9 | Merged 9XX-10XX |
| Daemon | 7XX | 5 | Renumbered 11XX |
| **CLI/TUI Interface** | 8XX | 8 | Merged 12XX-13XX |

**Total**: 9 categories, ~75 RFCs
**Reduction**: 4 categories eliminated (30% reduction)

---

## Recommendation

**Use Consolidated 9-Category Scheme**:

✅ **Architectural clarity**: Layer ranges preserved (1XX-3XX)
✅ **Protocol unity**: Unified 4XX protocol primitives
✅ **Infrastructure grouping**: Logical merges (Plugin+Events, CLI+Commands)
✅ **Simplified navigation**: Fewer categories, clearer grouping
✅ **Scalability**: Room for future RFCs in each range

**Next Action**: Update `architecture-review-report-2026-04-17.md` with consolidated scheme.

---

## Summary

**Original**: 13 categories (0XX-13XX)
**Consolidated**: 9 categories (0XX-8XX)
**Reduction**: 4 categories merged
**Preserved**: Three-layer architecture (1XX-3XX)
**Unified**: Core Protocols (4XX), Plugin & Events (6XX), CLI/TUI Interface (8XX)

Ready to proceed with consolidated numbering scheme.
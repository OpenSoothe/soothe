# RFC to Architecture Mapping

**Generated**: 2026-06-16  
**Total RFCs**: 76  
**Implemented**: 16  
**Draft**: 54  
**Proposed**: 2  
**Superseded**: 2  
**Deprecated**: 1  
**Accepted**: 1  

---

## Executive Summary

This document maps all RFCs in the Soothe project to their corresponding implementation modules, identifies gaps between specifications and current code, and assesses implementation priority for draft RFCs.

### Key Findings

1. **Strong foundation**: Core RFCs (RFC-000, 001, 200, 201, 600, 601) are fully implemented with clear code mapping
2. **Active evolution**: RFCs 624-626 represent the current ContextEngine consolidation effort
3. **Protocol maturity**: All major protocols (Planner, Memory, Durability, Policy) have implementations
4. **Gap areas**: Several StrangeLoop refinement RFCs (203, 206, 211-218) remain draft despite active code evolution
5. **Recent focus**: Desktop client (RFC-505, 700), unification (RFC-625), and state consolidation (RFC-626)

---

## RFC Domain Classification

| Domain | RFC Series | Count | Implemented |
|--------|-----------|-------|-------------|
| **Foundation** | 0xx | 8 | 4 |
| **Core Agent** | 1xx | 6 | 3 |
| **StrangeLoop & Cognition** | 2xx | 22 | 3 |
| **Protocols** | 3xx | 2 | 1 |
| **Daemon & Transport** | 4xx | 12 | 2 |
| **CLI & TUI** | 5xx | 6 | 1 |
| **Plugin System & Extensions** | 6xx | 19 | 5 |
| **Product & Applications** | 7xx | 1 | 0 |

---

## Implemented RFCs → Code Mapping

### Foundation (0xx)

#### RFC-000: System Conceptual Design ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-03-12  
**Code Mapping**:
- `packages/soothe/src/soothe/foundation/core/agent/` - CoreAgent runtime
- `packages/soothe/src/soothe/foundation/loop/` - StrangeLoop Layer 2
- `packages/soothe/src/soothe/foundation/autopilot/` - GoalEngine Layer 3
- `packages/soothe/src/soothe/protocols/` - Protocol definitions

**Implementation Evidence**: Three-layer architecture clearly visible in codebase structure. Layer 1 (CoreAgent), Layer 2 (StrangeLoop), Layer 3 (Autopilot) are implemented with proper delegation.

---

#### RFC-001: Core Protocol Modules Architecture ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-03-12  
**Code Mapping**:
- `packages/soothe/src/soothe/protocols/planner.py` - PlannerProtocol
- `packages/soothe/src/soothe/protocols/memory.py` - MemoryProtocol
- `packages/soothe/src/soothe/protocols/durability.py` - DurabilityProtocol
- `packages/soothe/src/soothe/protocols/policy.py` - PolicyProtocol
- `packages/soothe/src/soothe/protocols/strange_loop.py` - StrangeLoopProtocol

**Implementation Evidence**: All five core protocols defined and integrated.

---

### Core Agent (1xx)

#### RFC-101: Tool Interface & Event Naming ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-03-31  
**Code Mapping**:
- `packages/soothe/src/soothe/foundation/events/catalog.py` - Event registry
- `packages/soothe/src/soothe/foundation/events/constants.py` - Event type constants
- `packages/soothe/src/soothe/toolkits/` - Tool implementations
- `packages/soothe/src/soothe/protocols/toolkit.py` - ToolkitProtocol

**Implementation Evidence**: Event registry provides O(1) lookup, 4-segment naming convention adopted.

---

#### RFC-102: Secure Filesystem Path Handling ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-03-18  
**Code Mapping**:
- `packages/soothe/src/soothe/foundation/core/security/` - Security policies
- `packages/soothe/src/soothe/foundation/core/filesystem/` - Path handling
- `packages/soothe/src/soothe/protocols/operation_security.py` - OperationSecurityProtocol

**Implementation Evidence**: Sandbox path validation, operation security protocol implemented.

---

#### RFC-104: Dynamic System Context Injection ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-03-31  
**Code Mapping**:
- `packages/soothe/src/soothe/middleware/workspace_context.py` - Workspace context middleware
- `packages/soothe/src/soothe/middleware/system_prompt.py` - System prompt injection

**Implementation Evidence**: Dynamic context injection via middleware pattern.

---

### StrangeLoop & Cognition (2xx)

#### RFC-200: Autonomous Goal Management Loop ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-03-15  
**Code Mapping**:
- `packages/soothe/src/soothe/foundation/autopilot/engine/` - GoalEngine implementation
- `packages/soothe/src/soothe/foundation/autopilot/monitor/` - AutopilotMonitor
- `packages/soothe/src/soothe/protocols/autopilot.py` - AutopilotProtocol

**Implementation Evidence**: Goal DAG management, scheduling, backoff reasoning implemented.

**Note**: RFC-625 supersedes portions related to GoalEngine. GoalEngine deleted, features migrated to ContextEngine.

---

#### RFC-201: StrangeLoop Plan-Execute Loop Architecture ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-04-17  
**Code Mapping**:
- `packages/soothe/src/soothe/foundation/loop/engine/strange_loop.py` - Main loop implementation
- `packages/soothe/src/soothe/foundation/loop/engine/executor.py` - Step execution
- `packages/soothe/src/soothe/foundation/loop/planning/` - Plan generation
- `packages/soothe/src/soothe/foundation/loop/state/schemas.py` - PlanResult model

**Implementation Evidence**: Plan → Execute loop with PlanResult structured output, iteration tracking, evidence accumulation.

**Note**: RFC-220 proposes migration to LangGraph StateGraph orchestrator (draft, not yet implemented).

---

#### RFC-204: Autopilot Mode (Layer 3 Extension) ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-04-03  
**Code Mapping**:
- `packages/soothe/src/soothe/foundation/autopilot/service/` - Autopilot service layer
- `packages/soothe/src/soothe/foundation/autopilot/engine/` - Goal lifecycle management

**Implementation Evidence**: Autonomous goal scheduling, multi-thread execution, daemon-owned autopilot service.

---

#### RFC-219: Goal Completion Module ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-04-28  
**Code Mapping**:
- `packages/soothe/src/soothe/foundation/loop/engine/synthesis.py` - Goal completion synthesis
- `packages/soothe/src/soothe/foundation/loop/engine/scenario_classifier.py` - Scenario classification
- `packages/soothe/src/soothe/foundation/loop/engine/synthesis_projection.py` - Evidence projection

**Implementation Evidence**: Evidence-based goal completion with scenario classification.

---

### Protocols (3xx)

#### RFC-301: Protocol Registry ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-03-31  
**Code Mapping**:
- `packages/soothe/src/soothe/config/settings.py` - Protocol resolution in SootheConfig
- `packages/soothe/src/soothe/protocols/__init__.py` - Protocol exports

**Implementation Evidence**: Protocol registry pattern with runtime resolution.

---

### Daemon & Transport (4xx)

#### RFC-401: Event Processing & Filtering ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-03-31  
**Code Mapping**:
- `packages/soothe/src/soothe/foundation/events/catalog.py` - Event models and registry
- `packages/soothe/src/soothe/foundation/events/internal_bus.py` - Event bus
- `packages/soothe/src/soothe/foundation/events/visibility.py` - Verbosity filtering
- `packages/soothe-daemon/src/soothe_daemon/display/` - Display card filtering

**Implementation Evidence**: Typed event protocol, O(1) dispatch, daemon-side filtering.

---

#### RFC-450: Unified Daemon Communication Protocol ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-03-19  
**Code Mapping**:
- `packages/soothe-daemon/src/soothe_daemon/server/core.py` - WebSocket server
- `packages/soothe-daemon/src/soothe_daemon/server/handlers.py` - Message handlers
- `packages/soothe-daemon/src/soothe_daemon/server/session.py` - Session management
- `packages/soothe-daemon/src/soothe_daemon/protocol/` - Protocol definitions

**Implementation Evidence**: WebSocket-based IPC, JSON message format, health checks via HTTP REST.

---

### CLI & TUI (5xx)

#### RFC-500: CLI TUI Architecture ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-03-12  
**Code Mapping**:
- `packages/soothe-cli/src/soothe_cli/cli/` - CLI commands
- `packages/soothe-cli/src/soothe_cli/tui/` - TUI implementation
- `packages/soothe-cli/src/soothe_cli/runtime/` - Runtime integration

**Implementation Evidence**: Typer-based CLI, Textual TUI, unified architecture.

---

### Plugin System (6xx)

#### RFC-600: Plugin Extension Specification ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-03-23  
**Code Mapping**:
- `packages/soothe/src/soothe/plugin/` - Plugin loader and registry
- `packages/soothe-sdk/src/soothe_sdk/plugin/` - Plugin decorators (@plugin, @tool, @subagent)
- `packages/soothe-plugins/src/soothe_plugins/` - Sample plugins

**Implementation Evidence**: Decorator-based API, lifecycle hooks, priority-based discovery, configuration integration.

---

#### RFC-601: Built-in Plugin Agents ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-03-31  
**Code Mapping**:
- `packages/soothe/src/soothe/subagents/` - Built-in subagents (explore, plan, etc.)
- `packages/soothe-plugins/src/soothe_plugins/` - Plugin templates

**Implementation Evidence**: Explore subagent, plan subagent, research subagent implemented.

---

#### RFC-604: Plan Phase Robustness ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-04-11  
**Code Mapping**:
- `packages/soothe/src/soothe/foundation/loop/planning/` - Plan validation
- `packages/soothe/src/soothe/foundation/loop/engine/executor.py` - Three-layer defense

**Implementation Evidence**: Plan validation, repair cycles, evidence grounding.

---

#### RFC-625: ContextEngine and AutopilotMonitor Unification ✅ IMPLEMENTED
**Status**: Implemented  
**Created**: 2026-06-15  
**Code Mapping**:
- `packages/soothe/src/soothe/foundation/context/engine.py` - ContextEngine
- `packages/soothe/src/soothe/foundation/context/` - Context models and projection
- `packages/soothe/src/soothe/foundation/autopilot/monitor/` - Monitor integration

**Implementation Evidence**: GoalEngine deleted, features migrated to ContextEngine. AutopilotMonitor is now a submodule of ContextEngine.

---

## Draft RFCs - Implementation Priority Assessment

### High Priority (Critical Path)

#### RFC-220: LangGraph Agent Loop Orchestrator 🔴 HIGH
**Status**: Draft  
**Created**: 2026-05-05  
**Dependencies**: RFC-000, RFC-001, RFC-100, RFC-604, RFC-215, RFC-218, RFC-219  
**Supersedes**: RFC-201 §loop driver

**Relevance**: Critical architectural shift from imperative loop to LangGraph StateGraph. Required for reliable checkpointing, interrupt handling, and state management.

**Implementation Gap**: Current StrangeLoop uses imperative `while` loop. Migration to compiled StateGraph needed.

**Code Impact**: `packages/soothe/src/soothe/foundation/loop/engine/strange_loop.py`

**Priority**: 🔴 HIGH - Enables robust state management and interrupt semantics

---

#### RFC-624: Context Engine 🟠 HIGH
**Status**: Draft  
**Created**: 2026-06-12  
**Dependencies**: RFC-000, RFC-200, RFC-201, RFC-214, RFC-215  

**Relevance**: Core consolidation effort. Phase 1 complete, Phase 2-4 in progress.

**Implementation Gap**: 
- Phase 1 (standalone module): Done ✅
- Phase 2 (wire into GoalEngine): In progress
- Phase 3 (wire into StrangeLoop): Pending
- Phase 4 (sole data source): Pending

**Code Mapping**: `packages/soothe/src/soothe/foundation/context/`

**Priority**: 🟠 HIGH - Ongoing active development

---

#### RFC-626: Entity Model and State Consolidation 🟠 HIGH
**Status**: Draft  
**Created**: 2026-06-16  
**Dependencies**: RFC-624, RFC-625, RFC-203, RFC-201  

**Relevance**: Completes state management unification. Eliminates LoopState duplication.

**Implementation Gap**: LoopState still exists in code. Job abstraction refinement needed.

**Priority**: 🟠 HIGH - Part of current consolidation wave

---

#### RFC-413: Server-Owned Display Card Ledger 🟠 HIGH
**Status**: Draft  
**Created**: 2026-06-04  
**Dependencies**: RFC-401, RFC-403, RFC-411, RFC-503, RFC-505  
**Supersedes**: RFC-411

**Relevance**: Critical for desktop client and TUI reliability. Enables history reconstruction.

**Implementation Gap**: Current display cards are client-managed. Server-side ledger needed.

**Code Impact**: `packages/soothe-daemon/src/soothe_daemon/display/`

**Priority**: 🟠 HIGH - Enables robust desktop experience

---

### Medium Priority (Architecture Refinement)

#### RFC-203: StrangeLoop State & Memory 🟡 MEDIUM
**Status**: Draft  
**Created**: 2026-04-17  

**Relevance**: State management architecture. Partially implemented through ContextEngine work.

**Implementation Gap**: State model needs alignment with RFC-624/626 consolidation.

**Priority**: 🟡 MEDIUM - May be subsumed by RFC-624/626

---

#### RFC-214: Volatility-Tiered Prompt Architecture 🟡 MEDIUM
**Status**: Draft  
**Created**: 2026-05-03  

**Relevance**: Message ledger management for prompt optimization.

**Implementation Gap**: Current implementation needs volatility tiering.

**Priority**: 🟡 MEDIUM - Performance optimization

---

#### RFC-215: StrangeLoop Persistence Backend 🟡 MEDIUM
**Status**: Draft  
**Created**: 2026-04-22  

**Relevance**: Persistence strategy for StrangeLoop state.

**Implementation Gap**: Partial implementation via backends/persistence/.

**Code Mapping**: `packages/soothe/src/soothe/backends/persistence/`

**Priority**: 🟡 MEDIUM - Required for long-running reliability

---

#### RFC-218: Checkpoint Tree Architecture 🟡 MEDIUM
**Status**: Draft  
**Created**: 2026-04-22  

**Relevance**: Enables thread inheritance and forking.

**Implementation Gap**: Basic checkpointing exists, tree structure not implemented.

**Priority**: 🟡 MEDIUM - Required for branch/merge workflows

---

#### RFC-503: Loop-First User Experience 🟡 MEDIUM
**Status**: Draft  
**Created**: 2026-04-22  

**Relevance**: UX for goal-oriented interactions.

**Implementation Gap**: Partial implementation in TUI.

**Priority**: 🟡 MEDIUM - User experience enhancement

---

#### RFC-505: Soothe Desktop Client 🟡 MEDIUM
**Status**: Draft  
**Created**: 2026-06-04  

**Relevance**: Desktop application architecture.

**Implementation Gap**: Desktop client in early development.

**Priority**: 🟡 MEDIUM - Product roadmap

---

### Lower Priority (Future Work)

#### RFC-216: Multi-Thread Infinite Lifecycle 🟢 LOWER
**Status**: Draft  
**Created**: 2026-04-16  

**Relevance**: Automatic thread switching for long-running goals.

**Priority**: 🟢 LOWER - Advanced feature

---

#### RFC-221: LoopRunnerProtocol with Ray 🟢 LOWER
**Status**: Draft  
**Created**: 2026-05-09  

**Relevance**: Subprocess-isolated agent loop execution.

**Priority**: 🟢 LOWER - Performance optimization

---

#### RFC-603: Reasoning Quality & Progressive Actions 🟢 LOWER
**Status**: Draft  
**Created**: 2026-04-09  

**Relevance**: Progressive action mechanisms.

**Priority**: 🟢 LOWER - Quality improvement

---

#### RFC-700: Desktop App Product Redesign 🟢 LOWER
**Status**: Proposed  
**Created**: 2026-06-04  

**Relevance**: Product specification for desktop app.

**Priority**: 🟢 LOWER - Product planning

---

## Gaps Between Specification and Implementation

### Critical Gaps

1. **RFC-220 (LangGraph Orchestrator) vs Current Implementation**
   - **Specification**: Compiled LangGraph StateGraph with explicit routing
   - **Implementation**: Imperative while-loop in `strange_loop.py`
   - **Impact**: Checkpointing, interrupts, and state management are fragile
   - **Action**: Migration required for robust long-running goals

2. **RFC-624/626 (Context Engine) State Consolidation**
   - **Specification**: Single entity model under ContextEngine
   - **Implementation**: Split state between LoopState, GoalEngine, ContextEngine
   - **Impact**: State duplication, recovery complexity
   - **Action**: Ongoing consolidation work

3. **RFC-413 (Display Card Ledger)**
   - **Specification**: Server-owned ledger with full history
   - **Implementation**: Client-managed display, limited history
   - **Impact**: Desktop client cannot reconstruct history reliably
   - **Action**: Implement server-side ledger

### Moderate Gaps

1. **RFC-203 (StrangeLoop State)**
   - LoopState fields partially migrated to ContextEngine
   - Remaining fields need migration to ExecutionState facade

2. **RFC-214 (Volatility-Tiered Prompts)**
   - Prompt pipeline exists but lacks volatility tiering
   - Bounding strategies are ad-hoc

3. **RFC-215 (Persistence Backend)**
   - Basic persistence exists
   - Full checkpointing strategy not implemented

4. **RFC-218 (Checkpoint Tree)**
   - Basic checkpointing via LangGraph
   - Tree structure for thread forking not implemented

### Minor Gaps

1. **RFC-216 (Multi-Thread Lifecycle)**: Thread switching policy defined, not automated
2. **RFC-217 (Goal Context Management)**: Partially implemented through ContextEngine
3. **RFC-221 (LoopRunner with Ray)**: Architecture defined, subprocess isolation not implemented
4. **RFC-223 (Thread Inheritance)**: LangGraph forking exists, explicit API not exposed

---

## RFC Dependency Graph

```
RFC-000 (Conceptual Design) ─────────────────────────────────────────────────┐
  │                                                                           │
  ├─→ RFC-001 (Core Modules) ─→ RFC-301 (Protocol Registry)                   │
  │         │                                                                 │
  │         ├─→ RFC-100 (CoreAgent) ─→ RFC-101 (Tool Interface)               │
  │         │                    │                                            │
  │         │                    └─→ RFC-104 (Dynamic Context)                │
  │         │                                                                 │
  │         └─→ RFC-102 (Security Policy)                                     │
  │                                                                           │
  ├─→ RFC-200 (Autopilot/GoalEngine) ─→ RFC-204 (Autopilot Mode)              │
  │         │                                    │                           │
  │         │                                    └─→ RFC-222 (Autopilot)    │
  │         │                                                │               │
  │         │                                                └─→ RFC-625 ──┐│
  │         │                                                              ││
  │         └─→ [Superseded by RFC-625]                                    ││
  │                                                                       ││
  ├─→ RFC-201 (StrangeLoop) ─→ RFC-203 (State/Memory)                     ││
  │         │                    │                                         ││
  │         │                    ├─→ RFC-207 (Thread Context)             ││
  │         │                    │                                         ││
  │         │                    └─→ RFC-214 (Volatility-Tiered)           ││
  │         │                                                               ││
  │         ├─→ RFC-218 (Checkpoint Tree)                                  ││
  │         │                                                               ││
  │         ├─→ RFC-219 (Goal Completion) ─→ RFC-616 (Synthesis)           ││
  │         │                                                               ││
  │         └─→ RFC-220 (LangGraph Orchestrator) ◀─┐                       ││
  │                  ▲                             │                       ││
  │                  └─ Supersedes imperative loop  │                       ││
  │                                                │                       ││
  ├─→ RFC-450 (Daemon Protocol) ─→ RFC-401 (Event Processing)              ││
  │                                     │                                   ││
  │                                     └─→ RFC-403 (Unified Event Naming) ││
  │                                                                           │
  ├─→ RFC-500 (CLI/TUI) ─→ RFC-501 (Display Verbosity)                       │
  │         │                                                                 │
  │         └─→ RFC-502 (Presentation Engine)                                │
  │                                                                           │
  ├─→ RFC-600 (Plugin System) ─→ RFC-601 (Built-in Agents)                   │
  │         │                                                                 │
  │         └─→ RFC-619 (Tacitus Subagent)                                   │
  │                                                                           │
  └─→ RFC-624 (Context Engine) ─→ RFC-625 ───────────────────────────────────┘
                │
                └─→ RFC-626 (Entity Consolidation)
```

---

## Implementation Recommendations

### Immediate Actions (Next Sprint)

1. **Complete RFC-220 Migration**
   - Create LangGraph StateGraph orchestrator
   - Migrate imperative loop to graph nodes
   - Validate checkpoint behavior

2. **Complete RFC-624/626 Consolidation**
   - Finish Phase 3 (StrangeLoop wiring)
   - Begin Phase 4 (sole data source)
   - Eliminate LoopState duplication

3. **Implement RFC-413 Display Ledger**
   - Server-side card storage
   - History reconstruction API
   - Desktop client integration

### Near-Term Actions (Next Quarter)

1. **RFC-214/215/218 StrangeLoop Enhancements**
   - Volatility-tiered prompts
   - Persistence backend improvements
   - Checkpoint tree API

2. **RFC-503/505 Desktop Experience**
   - Loop-first UX patterns
   - Desktop client MVP

3. **RFC-603/604 Quality Improvements**
   - Progressive actions
   - Plan phase robustness refinements

### Long-Term Actions

1. **RFC-221 (LoopRunner with Ray)** - Subprocess isolation for reliability
2. **RFC-216 (Multi-Thread Lifecycle)** - Automatic thread switching
3. **RFC-700 (Desktop Product)** - Full product redesign

---

## Appendix: Code Module Index

### Foundation Modules

| Module | Path | Related RFCs |
|--------|------|--------------|
| CoreAgent | `packages/soothe/src/soothe/foundation/core/agent/` | RFC-100, RFC-101 |
| Security | `packages/soothe/src/soothe/foundation/core/security/` | RFC-102 |
| Filesystem | `packages/soothe/src/soothe/foundation/core/filesystem/` | RFC-102, RFC-103 |
| Context | `packages/soothe/src/soothe/foundation/context/` | RFC-624, RFC-625, RFC-626 |
| Events | `packages/soothe/src/soothe/foundation/events/` | RFC-401, RFC-403 |
| Autopilot | `packages/soothe/src/soothe/foundation/autopilot/` | RFC-200, RFC-204, RFC-222 |
| Loop | `packages/soothe/src/soothe/foundation/loop/` | RFC-201, RFC-203, RFC-220 |
| Persistence | `packages/soothe/src/soothe/foundation/persistence/` | RFC-215, RFC-801 |

### Protocol Modules

| Protocol | Path | RFC |
|----------|------|-----|
| PlannerProtocol | `packages/soothe/src/soothe/protocols/planner.py` | RFC-001 |
| MemoryProtocol | `packages/soothe/src/soothe/protocols/memory.py` | RFC-001 |
| DurabilityProtocol | `packages/soothe/src/soothe/protocols/durability.py` | RFC-001, RFC-306 |
| PolicyProtocol | `packages/soothe/src/soothe/protocols/policy.py` | RFC-001, RFC-305 |
| AutopilotProtocol | `packages/soothe/src/soothe/protocols/autopilot.py` | RFC-200 |
| StrangeLoopProtocol | `packages/soothe/src/soothe/protocols/strange_loop.py` | RFC-201 |
| ToolkitProtocol | `packages/soothe/src/soothe/protocols/toolkit.py` | RFC-101 |
| OperationSecurityProtocol | `packages/soothe/src/soothe/protocols/operation_security.py` | RFC-102, RFC-901 |

### Daemon Modules

| Module | Path | Related RFCs |
|--------|------|--------------|
| Server | `packages/soothe-daemon/src/soothe_daemon/server/` | RFC-450 |
| Protocol | `packages/soothe-daemon/src/soothe_daemon/protocol/` | RFC-450 |
| Display | `packages/soothe-daemon/src/soothe_daemon/display/` | RFC-401, RFC-413 |
| Channels | `packages/soothe-daemon/src/soothe_daemon/channels/` | RFC-450, RFC-620 |
| Persistence | `packages/soothe-daemon/src/soothe_daemon/persistence/` | RFC-801 |

### CLI/TUI Modules

| Module | Path | Related RFCs |
|--------|------|--------------|
| CLI | `packages/soothe-cli/src/soothe_cli/cli/` | RFC-500, RFC-504 |
| TUI | `packages/soothe-cli/src/soothe_cli/tui/` | RFC-500, RFC-501 |
| Runtime | `packages/soothe-cli/src/soothe_cli/runtime/` | RFC-500 |

### Plugin Modules

| Module | Path | Related RFCs |
|--------|------|--------------|
| Plugin System | `packages/soothe/src/soothe/plugin/` | RFC-600 |
| SDK Plugin API | `packages/soothe-sdk/src/soothe_sdk/plugin/` | RFC-600 |
| Built-in Plugins | `packages/soothe-plugins/src/soothe_plugins/` | RFC-601 |

---

## Appendix: RFC Status Summary

| Status | Count | RFCs |
|--------|-------|------|
| **Implemented** | 16 | RFC-000, RFC-001, RFC-101, RFC-102, RFC-104, RFC-200, RFC-201, RFC-204, RFC-219, RFC-301, RFC-401, RFC-450, RFC-500, RFC-600, RFC-601, RFC-604, RFC-625 |
| **Draft** | 54 | RFC-100, RFC-103, RFC-105, RFC-203, RFC-206, RFC-207, RFC-211, RFC-213-218, RFC-220-228, RFC-300, RFC-302, RFC-303, RFC-403, RFC-304, RFC-305, RFC-306, RFC-412, RFC-413, RFC-452, RFC-454, RFC-501-505, RFC-801-603, RFC-605-624, RFC-626 |
| **Proposed** | 2 | RFC-228, RFC-700 |
| **Superseded** | 2 | RFC-300, RFC-605 |
| **Deprecated** | 1 | RFC-411 |
| **Accepted** | 1 | RFC-619 |

---

*This mapping was generated on 2026-06-16 and reflects the codebase state at that time.*
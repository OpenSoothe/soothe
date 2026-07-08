---
title: Architecture
parent: Wiki
has_children: true
nav_order: 3
description: >-
  System design, three-level execution model, and design principles.
permalink: /wiki/architecture/
---

# Architecture Overview

**Soothe** is a goal-driven orchestration framework for 24/7 autonomous agents. It extends [deepagents](https://github.com/mirasoth/deepagents) with planning, context engineering, security policy, durability, and remote agent interop.

Soothe does not implement domain logic. It composes capabilities from others — langchain tools, MCP servers, deepagents subagents, ACP/A2A remote agents — and adds orchestration: wiring, delegation, lifecycle management, and context continuity.

---

## Three-Level Execution

Soothe operates through a hierarchical execution model with three tiers. Each tier delegates downward:

| Tier | Scope | Loop Pattern | Delegates To | RFC |
|------|-------|--------------|--------------|-----|
| **ContextEngine** | Long-running multi-goal DAGs | Goal → PLAN → PERFORM → REFLECT → Update | StrangeLoop | RFC-624/625 |
| **StrangeLoop** | Single-goal iterative refinement | Plan → Execute (max ~8 iterations) | CoreAgent | RFC-201 |
| **CoreAgent** | Model → Tools → Model turn loop | LangGraph native execution | langgraph | RFC-100 |

ContextEngine manages the goal DAG (priorities, dependencies, decomposition). StrangeLoop executes a single goal through iterative Plan-Execute cycles. CoreAgent is the pure execution runtime — no goal awareness, just prompts and tools.

---

## Framework Stack

```
+------------------------------------------------------+
|  Soothe (orchestration framework)                    |
|  - ContextEngine: Autonomous Goal Management         |
|  - StrangeLoop: Agentic Goal Execution               |
|  - CoreAgent: Runtime                                |
|  - MemoryProtocol, PlannerProtocol,                  |
|    PolicyProtocol, DurabilityProtocol                |
+------------------------------------------------------+
|  deepagents (agent framework)                        |
|  - BackendProtocol, AgentMiddleware,                 |
|    SubAgent/CompiledSubAgent, SummarizationMiddleware|
+------------------------------------------------------+
|  langchain / langgraph (runtime)                     |
|  - BaseChatModel, BaseTool, StateGraph,              |
|    Checkpointer, BaseStore, RemoteGraph              |
+------------------------------------------------------+
```

### Stack Responsibilities

| Tier | Components | Responsibility |
|------|------------|----------------|
| **Soothe** | ContextEngine, StrangeLoop, CoreAgent, Protocols | Orchestration, planning, durability, policy |
| **deepagents** | SubAgent, Middleware, Backend | Agent construction, summarization, backends |
| **langchain/langgraph** | Models, Tools, StateGraph | Runtime execution, state management |

---

## Module Map

**Packages**: `soothe` (core library), `soothe-daemon` (server), `soothe-cli` (CLI/TUI), `soothe-sdk` (plugin SDK), `soothe-plugins` (community plugins).

| Package | Purpose | Key Modules |
|---------|---------|-------------|
| **foundation/** | Core runtime | `core/agent` (CoreAgent), `sloop` (StrangeLoop), `context` (ContextEngine), `workspace`, `events`, `persistence`, `identity`, `cron`, `autopilot` |
| **runner/** | Execution coordinator | SootheRunner, resolver (protocol wiring), mixins |
| **protocols/** | Protocol definitions | memory, planner, policy, durability, vector_store, loop_planner, loop_working_memory, core_agent, operation_security |
| **backends/** | Protocol implementations | memory, durability, vector_store, persistence |
| **middleware/** | Soothe middleware stack | identity, policy, system_prompt, llm_rate_limit, workspace_context, per_turn_model, filesystem, code_interpreter, mcp_tool_search, tool_timeout |
| **subagents/** | Built-in subagents | planner, deep_research, academic_research, browser_use, veritas |
| **foundation/skillify/** | Daemon-shared skill search | SkillifyService indexer + retriever |
| **skills/** | Agent skills | builtin_skills, registry, budget |
| **mcp/** | MCP integration | server management, tool discovery |
| **config/** | Configuration | SootheConfig, model routing |

---

## Protocol Architecture

Soothe follows a **protocol-first, runtime-second** design. Every module is defined as a protocol (abstract interface). Default implementations use langchain/langgraph, but protocols carry no runtime dependency.

### Core Protocols

| Protocol | Purpose | RFC |
|----------|---------|-----|
| **MemoryProtocol** | Memory management (keyword, vector) | [RFC-300](../../specs/archive/RFC-300-context-memory-protocols.md) (archived), RFC-303 |
| **PlannerProtocol** | Planning and goal decomposition | RFC-304 |
| **PolicyProtocol** | Security policy enforcement | RFC-305 |
| **DurabilityProtocol** | State persistence and recovery | RFC-306 |
| **VectorStoreProtocol** | Vector database abstraction | RFC-301 |
| **LoopWorkingMemoryProtocol** | Working memory for StrangeLoop | RFC-224 |
| **LoopPlannerProtocol** | Planning within StrangeLoop | RFC-226 |
| **CoreAgentProtocol** | CoreAgent runtime contract | RFC-100 |
| **OperationSecurityProtocol** | Operation-level security | RFC-901 |

> **Note**: `ContextProtocol` (RFC-302 draft) was never implemented. Context management is handled by `ContextEngine` (`soothe.foundation.context`) directly, not via a protocol abstraction.

### Protocol Hierarchy

```
Protocol (ABC)
    ├── MemoryProtocol
    ├── PlannerProtocol
    ├── PolicyProtocol
    ├── DurabilityProtocol
    ├── VectorStoreProtocol
    ├── LoopWorkingMemoryProtocol
    ├── LoopPlannerProtocol
    ├── CoreAgentProtocol
    └── OperationSecurityProtocol
```

---

## Data Flow

**Query processing**: User → CLI/Daemon → Thread Manager → StrangeLoop (Plan → Execute loop) → CoreAgent (Model → Tools → Model) → Tool Execution → Response Stream → User.

**Event flow**: Tool Execution → `soothe.*` Event → Middleware Processing → Event Emitter → Daemon → WebSocket → CLI/TUI.

---

## Design Principles

1. **Protocol-First, Runtime-Second** — Every module is a protocol (abstract interface). Default implementations use langchain/langgraph, but protocols carry no runtime dependency.
2. **Extend deepagents, Don't Fork It** — Soothe adds protocols deepagents lacks (context, memory, planning, security, durability, remote agents). Everything deepagents provides is used as-is.
3. **Orchestration is the Product** — Soothe composes capabilities from others (wiring, delegation, lifecycle management, context continuity). No domain logic.
4. **Unbounded Context, Bounded Projection** — The orchestrator accumulates knowledge without limit; projection injects a token-budget-aware subset into prompts.
5. **Durable by Default** — Agent state is persistable and resumable. Crashes recover from the last checkpoint.
6. **Plan-Driven Execution** — Complex goals decompose into steps via two-phase planning (status assessment → plan generation). Simple queries bypass planning.
7. **Least-Privilege Delegation** — Every tool/subagent call passes through PolicyProtocol. Subagents inherit narrower permissions than their parent.
8. **Controlled Concurrency** — Plan steps declare dependencies (DAG); independent steps run in parallel within configurable limits.
9. **Uniform Delegation Envelope** — Local subagents, MCP tools, ACP endpoints, A2A peers, and LangGraph remote graphs all use the same `SubAgent`/`CompiledSubAgent` interface.

---

## Related RFCs

| RFC | Title |
|-----|-------|
| [RFC-000](../../specs/RFC-000-system-conceptual-design.md) | System Conceptual Design |
| [RFC-001](../../specs/RFC-001-core-modules-architecture.md) | Core Modules Architecture |
| [RFC-100](../../specs/RFC-100-coreagent-runtime.md) | CoreAgent Runtime |
| [RFC-101](../../specs/RFC-101-tool-interface.md) | Tool Interface & Event Naming |
| [RFC-102](../../specs/RFC-102-security-filesystem-policy.md) | Secure Filesystem Path Handling |
| [RFC-103](../../specs/RFC-103-thread-aware-workspace.md) | Thread-Aware Workspace |
| [RFC-104](../../specs/RFC-104-dynamic-system-context.md) | Dynamic System Context |
| [RFC-105](../../specs/RFC-105-progressive-skill-loading.md) | Progressive Skill Loading |
| [RFC-200](../../specs/archive/RFC-200-autonomous-goal-management.md) | Autonomous Goal Management (archived → RFC-624/625) |
| [RFC-201](../../specs/RFC-201-strangeloop-plan-execute-loop.md) | StrangeLoop Plan-Execute Loop |
| [RFC-203](../../specs/archive/RFC-203-strangeloop-state-memory.md) | StrangeLoop State Memory (archived) |
| [RFC-204](../../specs/RFC-204-autopilot-mode.md) | Autopilot Mode |
| [RFC-206](../../specs/RFC-206-prompt-architecture.md) | Prompt Architecture |
| [RFC-217](../../specs/RFC-217-goal-context-management.md) | Goal Context Management |
| [RFC-220](../../specs/RFC-220-langgraph-agent-loop-orchestrator.md) | LangGraph Agent Loop Orchestrator |
| [RFC-624](../../specs/RFC-624-context-engine.md) | Context Engine |
| [RFC-625](../../specs/RFC-625-autopilot-monitor-context-engine-unification.md) | Autopilot-Monitor-ContextEngine Unification |
| [RFC-300](../../specs/archive/RFC-300-context-memory-protocols.md) | Context & Memory Protocols (archived) |
| [RFC-301](../../specs/RFC-301-protocol-registry.md) | Protocol Registry |
| [RFC-303](../../specs/RFC-303-memory-protocol-architecture.md) | Memory Protocol Architecture |
| [RFC-304](../../specs/RFC-304-planner-protocol-architecture.md) | Planner Protocol Architecture |
| [RFC-305](../../specs/RFC-305-policy-protocol-architecture.md) | Policy Protocol Architecture |
| [RFC-306](../../specs/RFC-306-durability-protocol-architecture.md) | Durability Protocol Architecture |
| [RFC-450](../../specs/RFC-450-daemon-communication-protocol.md) | Daemon Communication Protocol |
| [RFC-401](../../specs/RFC-401-event-processing.md) | Event Processing |
| [RFC-403](../../specs/RFC-403-unified-event-naming.md) | Unified Event Naming |
| [RFC-600](../../specs/RFC-600-plugin-extension-system.md) | Plugin Extension System |
| [RFC-601](../../specs/RFC-601-built-in-agents.md) | Built-in Agents |

> See the [full RFC index](../../specs/rfc-index.md) for the complete catalog.

---

## See Also

- **[Core Module Overview](../core/index.md)** — Core module architecture details
- **[RFC Index](../../specs/rfc-index.md)** — Complete RFC catalog
- **[Implementation Guides](../../impl/)** — Implementation tracking
- **[User Guides](../user-guides/index.md)** — End-user documentation
- **[Debugging Guide](../howto_debug.md)** — Debug and diagnostics

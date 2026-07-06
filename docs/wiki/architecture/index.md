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

> **Soothe Architecture** - Goal-driven orchestration framework for 24/7 autonomous agents

This document provides a comprehensive overview of Soothe's architecture, design principles, and module organization.

---

## Table of Contents

1. [System Concept](#system-concept)
2. [Three-Level Execution](#three-level-execution)
3. [Framework Stack](#framework-stack)
4. [Module Map](#module-map)
5. [Protocol Architecture](#protocol-architecture)
6. [Data Flow](#data-flow)
7. [Design Principles](#design-principles)
8. [Related RFCs](#related-rfcs)

---

## System Concept

**Soothe** is a Goal-driven orchestration framework for building 24/7 long-running autonomous agents. It extends [deepagents](https://github.com/mirasoth/deepagents) with planning, context engineering, security policy, durability, and remote agent interop while remaining runtime-agnostic and langchain-ecosystem-friendly.

### Core Value Proposition

Soothe does not implement domain logic. It composes capabilities provided by others:
- **langchain tools** - File operations, web search, etc.
- **MCP servers** - Model Context Protocol integrations
- **deepagents subagents** - Specialized AI agents
- **Remote agents** - ACP/A2A protocol endpoints

**The value is in orchestration** - wiring, delegation, lifecycle management, and cognitive context continuity.

### Vision

A 24/7 long-running autonomous agent whose core strength is **orchestration**:
- Harnessing AI subagents, tools, and protocols
- Accomplishing complex, evolving goals
- Maintaining context across long-running sessions
- Delegating to specialized agents when appropriate

---

## Three-Level Execution

Soothe operates through a hierarchical execution model with three distinct levels:

```
┌─────────────────────────────────────────────────────────────┐
│ ContextEngine: Autonomous Goal Management (RFC-200)        │
│ • Scope: Long-running complex workflows, multi-goal DAGs   │
│ • Loop: Goal/Goals → PLAN → PERFORM → REFLECT → Update     │
│ • Delegation: PERFORM invokes StrangeLoop's full loop       │
└─────────────────────────────────────────────────────────────┘
                          ↓ PERFORM (full delegation)
┌─────────────────────────────────────────────────────────────┐
│ StrangeLoop: Agentic Goal Execution (RFC-201)                 │
│ • Scope: Single-goal execution through iterative refinement │
│ • Loop: Plan → Execute (max iterations: ~8)               │
│ • Delegation: EXECUTE invokes CoreAgent for execution       │
└─────────────────────────────────────────────────────────────┘
                          ↓ EXECUTE (step execution)
┌─────────────────────────────────────────────────────────────┐
│ CoreAgent: Runtime (RFC-100)                                │
│ • Foundation: create_soothe_agent() → CompiledStateGraph   │
│ • Execution: Model → Tools → Model loop (LangGraph native)  │
└─────────────────────────────────────────────────────────────┘
```

### Level Responsibilities

| Level | Responsibility | Delegates To |
|-------|---------------|--------------|
| **ContextEngine** | Goal DAG management, multi-goal coordination | StrangeLoop |
| **StrangeLoop** | Single-goal execution, plan-execute iteration | CoreAgent |
| **CoreAgent** | Tool/subagent execution, LLM interaction | langgraph |

### Level Interactions

```
ContextEngine
    │
    ├─ Receives: User goals, scheduled tasks, autonomous proposals
    ├─ Manages: Goal DAG, priorities, dependencies
    └─ Delegates: Single goals to StrangeLoop
    
StrangeLoop
    │
    ├─ Receives: Single goal from ContextEngine
    ├─ Manages: Plan → Execute iterations (max ~8)
    └─ Delegates: Individual steps to CoreAgent
    
CoreAgent
    │
    ├─ Receives: Step execution from StrangeLoop
    ├─ Manages: Model → Tools → Model loop
    └─ Returns: Tool results, model responses
```

---

## Framework Stack

```
+------------------------------------------------------+
|  Soothe (orchestration framework)                    |
|  - ContextEngine: Autonomous Goal Management         |
|  - StrangeLoop: Agentic Goal Execution                 │
|  - CoreAgent: Runtime                                │
|  - ContextProtocol, MemoryProtocol,                  │
|    PlannerProtocol, PolicyProtocol,                  │
|    DurabilityProtocol                                │
+------------------------------------------------------+
|  deepagents (agent framework)                        |
|  - BackendProtocol, AgentMiddleware,                 |
|    SubAgent/CompiledSubAgent, SummarizationMiddleware|
+------------------------------------------------------+
|  langchain / langgraph (runtime layer)               │
|  - BaseChatModel, BaseTool, StateGraph,              │
|    Checkpointer, BaseStore, RemoteGraph              │
+------------------------------------------------------+
```

### Stack Responsibilities

| Layer | Components | Responsibility |
|-------|------------|----------------|
| **Soothe** | ContextEngine, StrangeLoop, Protocols | Orchestration, planning, durability, policy |
| **deepagents** | SubAgent, Middleware, Backend | Agent construction, summarization, backends |
| **langchain/langgraph** | Models, Tools, StateGraph | Runtime execution, state management |

---

## Module Map

### Package Structure

```
packages/
├── soothe-sdk/        # Plugin SDK (decorators, types, utilities)
├── soothe-cli/        # CLI client (Typer CLI + Textual TUI)
├── soothe-daemon/     # Background daemon server (transports, lifecycle)
├── soothe-plugins/    # Community plugins (e.g. weaver subagent)
└── soothe/            # Agent core (library)
```

### soothe Package (Core Framework)

| Package | Purpose | Key Modules |
|---------|---------|-------------|
| **core/** | Framework orchestration | agent, runner, events, workspace, context, scheduling, persistence, middleware |
| **protocols/** | Protocol definitions | context, memory, planner, policy, durability, vector_store |
| **backends/** | Protocol implementations | memory, durability, vector_store, persistence |
| **subagents/** | Built-in subagents | plan, tacitus, browser_use, skillify, veritas |
| **skills/** | Agent skills | builtin_skills, registry, budget |
| **middleware/** | Event processing | system_prompt, policy, workspace_context, execution_hints |
| **mcp/** | MCP integration | server management, tool discovery |
| **daemon/** | Daemon server | multi-transport, thread lifecycle, authentication |
| **cli/** | CLI commands | main, TUI, commands |
| **config/** | Configuration | SootheConfig, model routing |
| **logging/** | Logging infrastructure | shared primitives |
| **utils/** | Shared utilities | helpers |

### Core Module Details

```
core/
├── agent/           # CoreAgent wraps deepagents
├── runner/          # StrangeLoop orchestration, mixins
├── loop/            # Plan-execute loop (RFC-201)
├── context/        # Autonomous goal lifecycle (RFC-200, RFC-624)
├── events/          # Event system, registry
├── workspace/       # Workspace resolution, backends
├── context/         # Tool context, triggers
├── scheduling/      # Concurrency control, DAG scheduler
├── persistence/     # Artifact store, policy
├── middleware/      # 5-middleware stack
├── resolver/        # Protocol wiring
└── prompts/         # System prompt building
```

---

## Protocol Architecture

Soothe follows a **protocol-first, runtime-second** design. Every module is defined as a protocol (abstract interface). Default implementations use langchain/langgraph, but protocols carry no runtime dependency.

### Core Protocols

| Protocol | Purpose | RFC |
|----------|---------|-----|
| **ContextProtocol** | Context management (keyword, vector) | RFC-300, RFC-302 |
| **MemoryProtocol** | Memory management (keyword, vector) | RFC-300, RFC-303 |
| **PlannerProtocol** | Planning and goal decomposition | RFC-304 |
| **PolicyProtocol** | Security policy enforcement | RFC-305 |
| **DurabilityProtocol** | State persistence and recovery | RFC-306 |
| **VectorStoreProtocol** | Vector database abstraction | RFC-301 |
| **LoopWorkingMemory** | Working memory for StrangeLoop | RFC-224 |
| **LoopPlanner** | Planning within StrangeLoop | RFC-226 |
| **RemoteProtocol** | Remote agent communication | RFC-450 |

### Protocol Hierarchy

```
Protocol (ABC)
    ├── ContextProtocol
    │   ├── KeywordContext
    │   └── VectorContext
    ├── MemoryProtocol
    │   ├── KeywordMemory
    │   └── VectorMemory
    ├── PlannerProtocol
    │   ├── SimplePlanner
    │   ├── LLMPlanner
    │   └── SubagentPlanner
    ├── PolicyProtocol
    │   └── ConfigDrivenPolicy
    ├── DurabilityProtocol
    │   ├── JsonDurability
    │   ├── RocksDBDurability
    │   └── PostgresDurability
    └── VectorStoreProtocol
        ├── PGVectorStore
        ├── WeaviateVectorStore
        └── InMemoryStore
```

---

## Data Flow

### Query Processing Flow

```
User Query
    ↓
CLI/Daemon
    ↓
Thread Manager (create/resume thread)
    ↓
StrangeLoop.runner
    ↓
┌─────────────────────────────────────┐
│ Plan-Execute Loop                    │
│                                      │
│  ┌──────────┐      ┌──────────┐     │
│  │  PLAN    │─────→│ EXECUTE  │     │
│  └──────────┘      └──────────┘     │
│       ↑                  │           │
│       └──────────────────┘           │
│       (iterate if needed)            │
└─────────────────────────────────────┘
    ↓
CoreAgent (deepagents)
    ↓
Model → Tools → Model Loop
    ↓
Tool Execution (filesystem, web, etc.)
    ↓
Response Stream
    ↓
CLI/Daemon → User
```

### Event Flow

```
Tool Execution
    ↓
Tool Event ( soothe.tool.execution.* )
    ↓
Middleware Processing
    ↓
Event Emitter → Event Stream
    ↓
Daemon → WebSocket → CLI
    ↓
TUI Display
```

---

## Design Principles

### 1. Protocol-First, Runtime-Second

Every Soothe module is defined as a protocol (abstract interface). Default implementations use langchain/langgraph, but the protocols themselves carry no runtime dependency. Alternative runtimes can provide their own implementations.

### 2. Extend deepagents, Don't Fork It

Soothe adds protocols that deepagents does not cover:
- Context management
- Memory systems
- Planning
- Security policy
- Durability
- Remote agents

For everything deepagents provides (subagents, middleware, backends, summarization, tools), Soothe uses it as-is.

### 3. Orchestration is the Product

Soothe composes capabilities provided by others. It does not implement domain logic. The value is in:
- **Wiring** - Connecting tools, subagents, and protocols
- **Delegation** - Deciding who does what
- **Lifecycle management** - Managing long-running sessions
- **Context continuity** - Maintaining knowledge across sessions

### 4. Unbounded Context, Bounded Projection

The orchestrator accumulates knowledge without limit in a context ledger. When reasoning or delegating, it projects a relevant, token-budget-aware subset into the LLM's context window. The global context is theoretically unlimited; only the projection is bounded.

### 5. Durable by Default

Agent state is persistable and resumable. Crashes recover from the last persisted state. The durability protocol abstracts over the persistence backend (could be LangGraph Checkpointer, a database, or a file).

### 6. Plan-Driven Execution

Complex goals are decomposed into plans with steps. The planner (`LLMPlanner`) uses two-phase architecture:
1. **Status Assessment** - Evaluate current state
2. **Plan Generation** - Create steps (if needed)

Simple queries bypass planning entirely for sub-second responses.

### 7. Least-Privilege Delegation

Every tool invocation and subagent spawn passes through a policy protocol. Permissions are structured:
- **Category** - File, network, system, etc.
- **Action** - Read, write, execute, etc.
- **Scope** - Specific paths, domains, commands

Subagents inherit a narrower permission set than their parent.

### 8. Controlled Concurrency

The orchestrator manages parallel execution of plan steps, subagents, and tools. Plan steps declare dependencies (DAG); independent steps run in parallel within configurable limits.

### 9. Uniform Delegation Envelope

Local subagents, MCP tools, ACP endpoints, A2A peers, and LangGraph remote graphs are all accessed through the same deepagents `SubAgent`/`CompiledSubAgent` interface. The caller does not know or care where the work happens.

---

## Related RFCs

### Foundation

- **[RFC-000](../../specs/RFC-000-system-conceptual-design.md)** - System Conceptual Design
- **[RFC-001](../../specs/RFC-001-core-modules-architecture.md)** - Core Modules Architecture

### Core Agent (1xx)

- **[RFC-100](../../specs/RFC-100-coreagent-runtime.md)** - CoreAgent Runtime Architecture
- **[RFC-101](../../specs/RFC-101-tool-interface.md)** - Tool Interface & Event Naming
- **[RFC-102](../../specs/RFC-102-security-filesystem-policy.md)** - Secure Filesystem Path Handling
- **[RFC-103](../../specs/RFC-103-thread-aware-workspace.md)** - Thread-Aware Workspace
- **[RFC-104](../../specs/RFC-104-dynamic-system-context.md)** - Dynamic System Context Injection
- **[RFC-105](../../specs/RFC-105-progressive-skill-loading.md)** - Progressive Skill Loading

### StrangeLoop & Cognition (2xx)

- **[RFC-200](../../specs/archive/RFC-200-autonomous-goal-management.md)** - Autonomous Goal Management Loop (archived)
- **[RFC-201](../../specs/RFC-201-strangeloop-plan-execute-loop.md)** - StrangeLoop Plan-Execute Loop
- **[RFC-203](../../specs/RFC-203-strangeloop-state-memory.md)** - StrangeLoop State Memory
- **[RFC-204](../../specs/RFC-204-autopilot-mode.md)** - Autopilot Mode
- **[RFC-206](../../specs/RFC-206-prompt-architecture.md)** - Prompt Architecture
- **[RFC-217](../../specs/RFC-217-goal-context-management.md)** - Goal Context Management
- **[RFC-220](../../specs/RFC-220-langgraph-agent-loop-orchestrator.md)** - LangGraph Agent Loop Orchestrator

### Protocols (3xx)

- **[RFC-300](../../specs/archive/RFC-300-context-memory-protocols.md)** - Context & Memory Protocols (archived)
- **[RFC-301](../../specs/RFC-301-protocol-registry.md)** - Protocol Registry
- **[RFC-302](../../specs/RFC-302-context-protocol-architecture.md)** - Context Protocol Architecture
- **[RFC-303](../../specs/RFC-303-memory-protocol-architecture.md)** - Memory Protocol Architecture
- **[RFC-304](../../specs/RFC-304-planner-protocol-architecture.md)** - Planner Protocol Architecture
- **[RFC-305](../../specs/RFC-305-policy-protocol-architecture.md)** - Policy Protocol Architecture
- **[RFC-306](../../specs/RFC-306-durability-protocol-architecture.md)** - Durability Protocol Architecture

### Plugin System (6xx)

- **[RFC-600](../../specs/RFC-600-plugin-extension-system.md)** - Plugin Extension System
- **[RFC-601](../../specs/RFC-601-built-in-agents.md)** - Built-in Agents
- **[RFC-613](../../specs/RFC-613-explore-agent-llm-orchestrated-search.md)** - Explore Agent

### Daemon & Communication (4xx)

- **[RFC-450](../../specs/RFC-450-daemon-communication-protocol.md)** - Daemon Communication Protocol
- **[RFC-401](../../specs/RFC-401-event-processing.md)** - Event Processing
- **[RFC-403](../../specs/RFC-403-unified-event-naming.md)** - Unified Event Naming

---

## See Also

- **[Core Module Overview](../core/index.md)** - Core module architecture details
- **[RFC Index](../../specs/rfc-index.md)** - Complete RFC catalog (73 RFCs)
- **[Implementation Guides](../../impl/)** - Implementation tracking
- **[User Guide](../user_guide.md)** - End-user documentation
- **[Debugging Guide](../howto_debug.md)** - Debug and diagnostics
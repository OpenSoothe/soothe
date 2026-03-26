# RFC-0001: System Conceptual Design

**RFC**: RFC-0001
**Title**: System Conceptual Design
**Status**: Draft
**Kind**: Conceptual Design
**Created**: 2026-03-12
**Dependencies**: -

## Overview

This document defines the conceptual design for **Soothe**, a protocol-driven orchestration framework for building 24/7 long-running autonomous agents. Soothe sits at the same abstraction level as deepagents -- above langchain and langgraph -- and extends deepagents with planning, context engineering, security policy, durability, and remote agent interop.

## Vision

A 24/7 long-running autonomous agent whose core strength is **orchestration** -- harnessing AI subagents, tools, and protocols (MCP, A2A, ACP) to accomplish complex, evolving goals. Soothe is a protocol-driven orchestration framework that extends deepagents with capabilities the ecosystem does not provide, while remaining runtime-agnostic and langchain-ecosystem-friendly.

Soothe does not implement domain logic. It composes capabilities provided by others: langchain tools, MCP servers, deepagents subagents, and remote agents via ACP/A2A. The value is in the wiring, delegation, lifecycle management, and cognitive context continuity.

## Architectural Level

```
+------------------------------------------------------+
|  Soothe (orchestration framework)                    |
|  - ContextProtocol, MemoryProtocol,                  |
|    PlannerProtocol, PolicyProtocol,                  |
|    DurabilityProtocol, RemoteAgentProtocol           |
|  - create_soothe_agent() wires everything together   |
+------------------------------------------------------+
|  deepagents (agent framework)                        |
|  - BackendProtocol, AgentMiddleware,                 |
|    SubAgent/CompiledSubAgent, SummarizationMiddleware|
|  - create_deep_agent()                               |
+------------------------------------------------------+
|  langchain / langgraph (runtime layer)               |
|  - BaseChatModel, BaseTool, StateGraph,              |
|    Checkpointer, BaseStore, RemoteGraph              |
+------------------------------------------------------+
```

## Guiding Principles

1. **Protocol-first, runtime-second** -- Every Soothe module is defined as a protocol (abstract interface). Default implementations use langchain/langgraph, but the protocols themselves carry no runtime dependency. Alternative runtimes can provide their own implementations.

2. **Extend deepagents, don't fork it** -- Soothe adds protocols that deepagents does not cover (context, memory, planning, policy, durability, remote agents). For everything deepagents already provides (subagents, middleware, backends, summarization, tools), use it as-is.

3. **Orchestration is the product** -- Soothe composes capabilities provided by others (tools, MCP servers, subagents, remote agents). It does not implement domain logic. The value is in the wiring, delegation, and lifecycle management.

4. **Unbounded context, bounded projection** -- The orchestrator accumulates knowledge without limit in a context ledger. When reasoning or delegating, it projects a relevant, token-budget-aware subset into the LLM's context window. The global context is theoretically unlimited; only the projection is bounded.

5. **Durable by default** -- Agent state is persistable and resumable. Crashes recover from the last persisted state. The durability protocol abstracts over the persistence backend (could be LangGraph Checkpointer, a database, or a file).

6. **Plan-driven execution** -- Complex goals are decomposed into plans with steps. Two planner tiers: `DirectPlanner` (single LLM call for simple tasks) and `SubagentPlanner` (multi-turn reasoning for complex tasks). Both satisfy `PlannerProtocol`. Simple queries bypass planning entirely.

7. **Least-privilege delegation** -- Every tool invocation and subagent spawn passes through a policy protocol. Permissions are structured (category + action + scope), enabling fine-grained control down to individual shell commands or file paths. Subagents inherit a narrower permission set than their parent.

8. **Controlled concurrency** -- The orchestrator manages parallel execution of plan steps, subagents, and tools. Plan steps declare dependencies (DAG); independent steps can run in parallel within configurable limits. Prevents rate-limit exhaustion and resource contention.

9. **Uniform delegation envelope** -- Local subagents, MCP tools, ACP endpoints, A2A peers, and LangGraph remote graphs are all accessed through the same deepagents `SubAgent`/`CompiledSubAgent` interface. The caller does not know or care where the work happens.

10. **Graceful degradation** -- Step-level failure handling (mark failed, try next, revise plan), LLM content-policy fallbacks, and configurable retry. Partial results over hard failure.

## Core Abstractions

All new abstractions are **protocols** at the deepagents abstraction level. No runtime types (LangGraph, langchain) appear in protocol signatures.

### Orchestrator

The top-level agent created by `create_soothe_agent()`. Wires together all protocols and delegates to deepagents' `create_deep_agent()` for the underlying agent loop. The orchestrator's runtime implementation MAY be a LangGraph graph, or any other runtime that supports the deepagents contract.

### Context (`ContextProtocol`)

The orchestrator's cognitive knowledge ledger. An unbounded, append-only accumulator of findings from tool results, subagent results, and reflections. Projects relevant subsets into bounded token windows on demand -- for the orchestrator's own reasoning, or as a focused briefing for a subagent. Persisted across turns and restarts via `DurabilityProtocol`.

Key property: the context ledger is theoretically unlimited. Only projections are bounded by the target LLM's context window.

### Memory (`MemoryProtocol`)

Cross-thread long-term memory. Stores important knowledge that should survive beyond a single thread. Queryable by semantic relevance. Separate from deepagents' `MemoryMiddleware` (which loads static AGENTS.md instructions) and separate from `ContextProtocol` (which is within-thread).

### Planner (`PlannerProtocol`)

Creates and revises plans for complex goals. A plan is a Pydantic data model (goal + steps + statuses + dependency graph + concurrency policy). The protocol is runtime-agnostic; two default implementations serve different complexity tiers.

### Policy (`PolicyProtocol`)

Checks whether a given action (tool call, subagent spawn, MCP connect) is permitted under the current permission set. Returns allow/deny/need-approval. Permissions are structured with category, action, and scope for fine-grained control. Enforcement is wired via deepagents `AgentMiddleware`.

### Durability (`DurabilityProtocol`)

Persists and restores agent state including thread lifecycle management (create/resume/suspend/archive). The protocol is backend-agnostic; the default implementation uses LangGraph Checkpointer + BaseStore.

### Remote Agent (`RemoteAgentProtocol`)

Invokes a remote agent and returns results. Implementations for ACP, A2A, and LangGraph RemoteGraph. Each is wrapped as a deepagents `CompiledSubAgent` for uniform access via the `task` tool.

### Plan (data model)

A Pydantic data model (not a service). Contains goal, ordered steps with execution hints, dependency graph, and concurrency policy. Carried in agent state; checkpointed automatically.

### Permission (data model)

A structured permission with category (`fs`, `shell`, `net`, `mcp`, `subagent`), action (`read`, `write`, `execute`, `connect`, `spawn`), and scope (glob pattern, command name, or `*`). Enables fine-grained control. Collected into a `PermissionSet` with scope-aware matching logic.

### Concurrency Policy (data model)

Controls parallel execution of plan steps, subagents, and tools. Steps declare dependencies forming a DAG; the orchestrator schedules independent steps in parallel within configured limits.

## Terminology

| Term | Definition |
|------|------------|
| Protocol | A Python `Protocol` or abstract base class defining an interface. NOT a network protocol. |
| Orchestrator | The Soothe agent instance created by `create_soothe_agent()`. Wraps deepagents' agent with planning, policy, context, and durability. |
| Plan / Step | A structured decomposition of a goal. Steps have execution hints (tool, subagent, remote) and statuses (pending, in_progress, completed, failed). |
| Context Ledger | The orchestrator's unbounded, append-only accumulation of `ContextEntry` items. Persisted via `DurabilityProtocol`. Distinct from conversation history. |
| Context Projection | A bounded, purpose-scoped view of the context ledger, assembled by `ContextProtocol.project()` to fit within a token budget. |
| Long-Term Memory | Cross-thread persistent knowledge managed by `MemoryProtocol`. Explicitly populated, semantically queryable. |
| Thread | One continuous agent conversation/execution. Has a unique ID, persistable state, and metadata. |
| Policy Profile | A named configuration of permitted actions (e.g., `readonly`, `standard`, `privileged`). |
| Permission Set | A collection of structured `Permission` objects with scope-aware matching. |
| Delegation | Routing work to a subagent (local or remote) via deepagents' `task` tool. |
| Concurrency Policy | Configuration controlling parallel execution limits for steps, subagents, and tools. |

## System Invariants

1. All Soothe-added modules are defined as protocols; no runtime types in protocol signatures.
2. The orchestrator's cognitive context (`ContextProtocol`) is theoretically unbounded; only projections are bounded by token budgets.
3. Subagents receive a context projection scoped to their goal, NOT the orchestrator's full context. Subagents return results only; the orchestrator ingests them.
4. Long-term memory (`MemoryProtocol`) is explicitly populated -- not every finding is auto-memorized.
5. Every tool call and subagent spawn passes through `PolicyProtocol` before execution.
6. Agent state (including context ledger) is persistable via `DurabilityProtocol`; production deployments MUST enable persistence.
7. Subagents receive a permission set that is a subset of their parent's.
8. Remote agents are indistinguishable from local subagents at the delegation interface.
9. `PlannerProtocol` is optional -- simple queries bypass it and use deepagents' standard agent loop.
10. Conversation history compression is handled by deepagents' `SummarizationMiddleware`; cognitive context accumulation is handled by `ContextProtocol`. These are complementary, not overlapping.
11. MCP session lifecycle is managed alongside thread lifecycle (created on thread start, cleaned up on suspend/archive).
12. Plan state and context ledger survive thread suspend/resume via `DurabilityProtocol`.
13. All protocol implementations are swappable via `SootheConfig`.

## Boundaries

### In Scope

- Protocol definitions for context, memory, planning, policy, durability, remote agents, and concurrency
- Default implementations using the langchain ecosystem
- Wiring into deepagents' middleware and subagent system
- Configuration model extensions to `SootheConfig`
- CLI extensions for thread management

### Out of Scope

- Domain-specific tools (use langchain/community)
- LLM training or fine-tuning
- Full cron/scheduler (use external triggers)
- UI/frontend
- Reimplementing anything deepagents or langchain already provides

## Dependencies

This is the foundational Conceptual Design spec. All subsequent Architecture Design and Implementation Interface Design specs depend on this document.

## Related Documents

- [RFC Standard](./rfc-standard.md) - Specification kinds and process
- [RFC Index](./rfc-index.md) - All RFCs
- [RFC-0002](./RFC-0002.md) - Core Modules Architecture Design
- [RFC-0009](./RFC-0009.md) - DAG-Based Execution and Unified Concurrency

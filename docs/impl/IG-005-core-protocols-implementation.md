# Core Protocols Implementation Guide

**Guide**: IG-005  
**Title**: Core Protocols Implementation  
**Created**: 2026-03-12  
**Related RFCs**: RFC-000, RFC-001

## Overview

This guide covers the implementation of Soothe's seven core modules defined in RFC-001:
ContextProtocol, MemoryProtocol, PlannerProtocol, PolicyProtocol, DurabilityProtocol,
RemoteAgentProtocol, and ConcurrencyPolicy.

## Prerequisites

- [x] RFC-000 accepted (System Conceptual Design)
- [x] RFC-001 accepted (Core Modules Architecture Design)
- [x] IG-004 completed (Ecosystem Capability Analysis)
- [x] Development environment setup (deepagents >= 0.4.10, langgraph >= 1.1.1)

## File Structure

```
src/soothe/
├── __init__.py                          # Add new exports
├── agent.py                             # Extend create_soothe_agent() wiring
├── config.py                            # Extend SootheConfig with new fields
├── protocols/                           # NEW: protocol definitions
│   ├── __init__.py
│   ├── context.py                       # ContextProtocol + data models
│   ├── memory.py                        # MemoryProtocol + data models
│   ├── planner.py                       # PlannerProtocol + Plan/PlanStep models
│   ├── policy.py                        # PolicyProtocol + Permission/PermissionSet
│   ├── durability.py                    # DurabilityProtocol + ThreadInfo models
│   ├── remote.py                        # RemoteAgentProtocol
│   └── concurrency.py                   # ConcurrencyPolicy model
├── context/                             # NEW: context implementations
│   ├── __init__.py
│   ├── keyword.py                       # KeywordContext (lightweight)
│   └── indexed.py                       # IndexedContext (embedding-based)
├── memory_store/                        # NEW: memory implementations
│   ├── __init__.py
│   ├── store_backed.py                  # StoreBackedMemory
│   └── semantic.py                      # SemanticMemory
├── planning/                            # NEW: planner implementations
│   ├── __init__.py
│   ├── direct.py                        # DirectPlanner
│   └── subagent.py                      # SubagentPlanner
├── policy/                              # NEW: policy implementations
│   ├── __init__.py
│   └── config_driven.py                 # ConfigDrivenPolicy
├── durability/                          # NEW: durability implementations
│   ├── __init__.py
│   └── langgraph_durability.py          # LangGraphDurability
├── remote/                              # NEW: remote agent adapters
│   ├── __init__.py
│   ├── acp.py                           # ACPRemoteAgent
│   ├── a2a.py                           # A2ARemoteAgent
│   └── langgraph_remote.py             # LangGraphRemoteAgent
├── middleware/                          # NEW: Soothe middleware
│   ├── __init__.py
│   ├── context_middleware.py            # ContextMiddleware
│   ├── policy_middleware.py             # PolicyMiddleware
│   └── planner_middleware.py            # PlannerMiddleware
├── subagents/                           # EXISTING (extend)
├── tools/                               # EXISTING (extend with memory tools)
├── mcp/                                 # EXISTING
├── cli/                                 # EXISTING (extend with thread commands)
└── utils/                               # EXISTING
```

## Implementation Plan

### Phase 1: Protocols and Data Models

**Goal**: Define all protocol interfaces and Pydantic data models. Zero runtime dependencies in protocols.

**Files**:
- `src/soothe/protocols/context.py` -- ContextProtocol, ContextEntry, ContextProjection
- `src/soothe/protocols/memory.py` -- MemoryProtocol, MemoryItem
- `src/soothe/protocols/planner.py` -- PlannerProtocol, Plan, PlanStep, PlanContext, StepResult, Reflection
- `src/soothe/protocols/policy.py` -- PolicyProtocol, Permission, PermissionSet, ActionRequest, PolicyDecision, PolicyContext, PolicyProfile
- `src/soothe/protocols/durability.py` -- DurabilityProtocol, ThreadInfo, ThreadMetadata, ThreadFilter
- `src/soothe/protocols/remote.py` -- RemoteAgentProtocol
- `src/soothe/protocols/concurrency.py` -- ConcurrencyPolicy

### Phase 2: Core Implementations

**Goal**: Default implementations using langchain ecosystem.

**Priority order** (by dependency):
1. `ContextProtocol` -- `KeywordContext` (no external deps)
2. `MemoryProtocol` -- `StoreBackedMemory` (no external deps)
3. `PolicyProtocol` -- `ConfigDrivenPolicy` (no external deps)
4. `PlannerProtocol` -- `DirectPlanner` (needs langchain BaseChatModel)
5. `DurabilityProtocol` -- `LangGraphDurability` (needs langgraph Checkpointer + BaseStore)
6. `ConcurrencyPolicy` -- data model only (no impl needed)
7. `RemoteAgentProtocol` -- stubs for ACP/A2A/LangGraph adapters

### Phase 3: Middleware Integration

**Goal**: Wire protocols into deepagents' middleware stack.

**Files**:
- `src/soothe/middleware/context_middleware.py` -- wraps ContextProtocol as AgentMiddleware
- `src/soothe/middleware/policy_middleware.py` -- wraps PolicyProtocol as AgentMiddleware
- `src/soothe/middleware/planner_middleware.py` -- wraps PlannerProtocol as AgentMiddleware

### Phase 4: Config and Agent Wiring

**Goal**: Extend SootheConfig and create_soothe_agent() to wire everything together.

**Files**:
- `src/soothe/config.py` -- add policy_profiles, planner_routing, context_backend, memory_backend, concurrency
- `src/soothe/agent.py` -- instantiate protocols, create middleware, pass to create_deep_agent()

## Implementation Details

### Phase 1 Key Decisions

- All protocols use `typing.Protocol` (structural subtyping, no inheritance required)
- Data models use Pydantic `BaseModel` with no langchain/langgraph imports
- `PermissionSet` is a regular class (not Pydantic) since it needs custom matching logic
- `Permission` uses `@dataclass(frozen=True)` for hashability

### Phase 2 Key Decisions

- `KeywordContext` stores entries in a simple list, scores by keyword overlap + recency
- `StoreBackedMemory` uses a dict internally, serializes to JSON for persistence
- `ConfigDrivenPolicy` evaluation order: deny rules -> granted permissions -> approvable -> default deny
- `DirectPlanner` uses `model.with_structured_output(Plan)` for single-call planning

### Phase 3 Key Decisions

- `ContextMiddleware` extends deepagents' `AgentMiddleware` protocol
- It wraps `wrap_model_call()` to inject context projection before LLM calls
- It cannot directly intercept tool results (deepagents middleware doesn't have that hook),
  so context ingestion of tool results happens via a post-processing node or tool wrapper
- `PolicyMiddleware` wraps `wrap_tool_call()` to check permissions before tool execution

## Testing Strategy

### Unit Tests

- `tests/unit_tests/test_protocols.py` -- protocol data models serialization
- `tests/unit_tests/test_context.py` -- KeywordContext projection, ingestion, persistence
- `tests/unit_tests/test_memory.py` -- StoreBackedMemory remember/recall/forget
- `tests/unit_tests/test_planner.py` -- DirectPlanner plan creation with mock LLM
- `tests/unit_tests/test_policy.py` -- Permission matching, PermissionSet, ConfigDrivenPolicy
- `tests/unit_tests/test_durability.py` -- thread lifecycle operations
- `tests/unit_tests/test_concurrency.py` -- ConcurrencyPolicy validation

### Integration Tests

- `tests/integration_tests/test_agent_with_protocols.py` -- full agent with all protocols wired

## Verification

- [ ] All protocols defined with no runtime deps in signatures
- [ ] KeywordContext passes projection and persistence tests
- [ ] StoreBackedMemory passes remember/recall/forget tests
- [ ] ConfigDrivenPolicy correctly evaluates permission scopes
- [ ] DirectPlanner produces valid Plan from mock LLM
- [ ] PolicyMiddleware blocks denied tool calls
- [ ] ContextMiddleware enriches prompts with projected context
- [ ] create_soothe_agent() wires all protocols from SootheConfig
- [ ] All existing tests still pass
- [ ] ruff lint clean

## Related Documents

- [RFC-000](../specs/RFC-000-system-conceptual-design.md) - System Conceptual Design
- [RFC-001](../specs/RFC-001-core-modules-architecture.md) - Core Modules Architecture Design
- [IG-004](./004-ecosystem-capability-analysis.md) - Ecosystem Capability Analysis
- [RFC Index](../specs/rfc-index.md)

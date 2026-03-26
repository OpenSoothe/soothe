# Ecosystem Capability Analysis

**Guide**: IG-004
**Title**: Gap Analysis -- deepagents + langchain + langgraph vs Soothe TARGET
**Created**: 2026-03-12
**Related RFCs**: RFC-0001, RFC-0002

## Overview

Maps each TARGET capability to what the ecosystem (deepagents, langchain, langgraph) already provides and identifies gaps that Soothe must fill.

## Fully Provided (Use As-Is)

| Capability | Source | Key Components |
|---|---|---|
| Tool system | langchain | `BaseTool`, `@tool`; langgraph `ToolNode` |
| MCP integration | langchain-mcp-adapters | stdio/SSE/HTTP; soothe `MCPSessionManager` |
| In-process subagents | deepagents | `SubAgent`, `CompiledSubAgent`, `task` tool |
| File/shell operations | deepagents | `FilesystemMiddleware`, `BackendProtocol` |
| Conversation summarization | deepagents | `SummarizationMiddleware` |
| Prompt caching | deepagents | `AnthropicPromptCachingMiddleware` |
| Human-in-the-loop | langgraph | `GraphInterrupt`, deepagents `interrupt_on` |
| Node-level retries | langgraph | `RetryPolicy` |
| Task tracking | deepagents | `TodoListMiddleware`, `write_todos` |

## Partially Provided (Need Protocol + Extension)

### State Persistence

- **Provided**: langgraph `Checkpointer` + `BaseStore` for storage layer
- **Gap**: No thread lifecycle management (status tracking, resume-from-crash, MCP cleanup)
- **Filled by**: `DurabilityProtocol`

### Remote Agent Orchestration

- **Provided**: langgraph `RemoteGraph` (LG-to-LG); deepagents ACP (editor integration)
- **Gap**: No ACP client adapter, no A2A support
- **Filled by**: `RemoteAgentProtocol`

### Error Tolerance

- **Provided**: `RetryPolicy` per node + `GraphInterrupt` for pause
- **Gap**: No plan-level step failure handling or content-policy fallback
- **Filled by**: PlannerProtocol revision logic

## Not Provided (Must Implement)

### Context Engineering

- **Existing**: deepagents' `SummarizationMiddleware` compacts conversation history
- **Gap**: No knowledge accumulation beyond message stream. No structured findings, no relevance-based projection, no subagent briefings
- **Filled by**: `ContextProtocol` + `KeywordContext` / `VectorContext`

### Long-Term Memory

- **Existing**: deepagents' `MemoryMiddleware` loads static AGENTS.md files; langgraph `BaseStore` provides storage
- **Gap**: No what/how to remember across threads, no semantic recall, no importance scoring
- **Filled by**: `MemoryProtocol` + `StoreBackedMemory` / `VectorMemory`

### Planning

- **Existing**: None
- **Gap**: No plan-execute-reflect-revise lifecycle
- **Filled by**: `PlannerProtocol` + `DirectPlanner` / `SubagentPlanner`

### Security Policy

- **Existing**: None
- **Gap**: No permission model or tool-level enforcement
- **Filled by**: `PolicyProtocol` + `PermissionSet` + `ConfigDrivenPolicy`

### Thread Lifecycle Management

- **Existing**: None
- **Gap**: No create/resume/suspend/archive API
- **Filled by**: `DurabilityProtocol`

### Remote Agent Adapters

- **Existing**: None (beyond langgraph RemoteGraph)
- **Gap**: No ACP client or A2A handling for task delegation
- **Filled by**: `RemoteAgentProtocol` + adapter implementations

### Concurrency Control

- **Existing**: None
- **Gap**: No mechanism for controlling parallel execution with dependency-aware scheduling
- **Filled by**: `ConcurrencyPolicy` model + orchestrator scheduling

### Vector Storage

- **Existing**: langchain has vector store abstractions but they are document-centric
- **Gap**: Need a lightweight async protocol for raw vector operations (insert, search, update) with provider-specific implementations
- **Filled by**: `VectorStoreProtocol` + `PGVectorStore` / `WeaviateVectorStore`

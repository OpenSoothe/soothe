# RFC-410: RemoteAgentProtocol Architecture

**RFC**: 410
**Title**: RemoteAgentProtocol: Remote Invocation & Backend Implementations
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-17
**Dependencies**: RFC-000, RFC-001
**Related**: RFC-100 (CoreAgent), RFC-600 (Plugin)

---

## Abstract

This RFC defines RemoteAgentProtocol, Soothe's remote agent invocation interface for uniform delegation across different transport backends. RemoteAgentProtocol provides invoke, stream, and health_check operations with implementations for LangGraph RemoteGraph, ACP endpoints, and A2A peers. Future wrapping as deepagents CompiledSubAgent will enable uniform task tool access for local and remote agents.

---

## Protocol Interface

```python
class RemoteAgentProtocol(Protocol):
    """Remote agent invocation protocol."""

    async def invoke(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Invoke remote agent synchronously."""
        ...

    async def stream(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Invoke remote agent with streaming output."""
        ...

    async def health_check(self) -> bool:
        """Check remote agent health status."""
        ...
```

---

## Design Principles

### 1. Uniform Delegation Envelope

Local subagents, MCP tools, ACP endpoints, A2A peers, and LangGraph remote graphs accessed through same deepagents SubAgent/CompiledSubAgent interface (future).

**Current state**: RemoteAgentProtocol accessed directly through protocol interface.

**Planned future**: Wrap remote backends as CompiledSubAgent for uniform `task` tool access.

### 2. Transport Agnostic Interface

Protocol independent of transport mechanism:
- HTTP/REST for ACP
- WebSocket for A2A
- LangGraph RemoteGraph for distributed graphs
- Implementation details hidden from caller

### 3. Streaming Support

Remote agents support streaming output:
- AsyncIterator[str] for incremental results
- Real-time progress updates
- Large output handling
- Non-blocking execution

### 4. Health Monitoring

Health check for remote agent availability:
- Connection status
- Service availability
- Resource health
- Graceful degradation

---

## Implementations

### LangGraphRemoteAgent

```python
class LangGraphRemoteAgent(RemoteAgentProtocol):
    """LangGraph RemoteGraph implementation."""

    def __init__(self, remote_graph: RemoteGraph) -> None:
        self._remote_graph = remote_graph

    async def invoke(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        result = await self._remote_graph.invoke(
            input={"task": task, "context": context or {}},
        )
        return result["output"]

    async def stream(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        async for chunk in self._remote_graph.astream(
            input={"task": task, "context": context or {}},
        ):
            yield chunk["content"]

    async def health_check(self) -> bool:
        try:
            # Ping remote graph endpoint
            response = await self._remote_graph.health_check()
            return response.status == "healthy"
        except Exception:
            return False
```

**Backend**: LangGraph RemoteGraph
**Transport**: HTTP/WebSocket (LangGraph native)
**Status**: Implemented

### ACPRemoteAgent (Planned)

```python
class ACPRemoteAgent(RemoteAgentProtocol):
    """ACP endpoint implementation (planned)."""

    def __init__(self, endpoint_url: str) -> None:
        self._endpoint_url = endpoint_url

    async def invoke(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        # HTTP POST to ACP endpoint
        response = await http_post(
            url=f"{self._endpoint_url}/invoke",
            json={"task": task, "context": context or {}},
        )
        return response["result"]

    async def stream(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        # WebSocket connection for streaming
        ws = await websocket_connect(f"{self._endpoint_url}/stream")
        await ws.send_json({"task": task, "context": context or {}})
        async for message in ws:
            yield message["content"]

    async def health_check(self) -> bool:
        try:
            response = await http_get(f"{self._endpoint_url}/health")
            return response["status"] == "healthy"
        except Exception:
            return False
```

**Backend**: ACP (Agent Communication Protocol) endpoint
**Transport**: HTTP/REST + WebSocket
**Status**: Planned (stub implementation)

### A2ARemoteAgent (Planned)

```python
class A2ARemoteAgent(RemoteAgentProtocol):
    """A2A peer implementation (planned)."""

    def __init__(self, peer_url: str) -> None:
        self._peer_url = peer_url

    async def invoke(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        # A2A protocol invocation
        response = await a2a_invoke(
            peer_url=self._peer_url,
            task=task,
            context=context or {},
        )
        return response["output"]

    async def stream(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        # A2A streaming protocol
        async for chunk in a2a_stream(
            peer_url=self._peer_url,
            task=task,
            context=context or {},
        ):
            yield chunk

    async def health_check(self) -> bool:
        try:
            response = await a2a_health_check(self._peer_url)
            return response["status"] == "healthy"
        except Exception:
            return False
```

**Backend**: A2A (Agent-to-Agent) protocol
**Transport**: A2A-specific protocol
**Status**: Planned (stub implementation)

---

## Future: CompiledSubAgent Wrapping

### Uniform Task Tool Access

**Goal**: Wrap remote backends as deepagents CompiledSubAgent for uniform access via `task` tool.

**Implementation** (future):
```python
def wrap_remote_as_subagent(remote: RemoteAgentProtocol) -> CompiledSubAgent:
    """Wrap remote agent as CompiledSubAgent for uniform delegation."""

    async def remote_agent_func(state: AgentState) -> AgentState:
        result = await remote.invoke(
            task=state["task"],
            context=state["context"],
        )
        return {"output": result}

    return CompiledSubAgent(
        name="remote_agent",
        description="Remote agent via uniform interface",
        func=remote_agent_func,
    )

# Usage: All remote agents accessed via task tool
task_result = await agent.invoke(
    input={"task": "research_topic", "subagent": "remote_agent"},
)
```

**Benefits**:
- Local and remote agents indistinguishable to caller
- Uniform `task` tool interface
- Simplified delegation logic
- Backend abstraction

---

## Configuration

```yaml
remote_agents:
  langgraph:
    enabled: true
    endpoints:
      - name: distributed_research
        url: https://remote.example.com/graph/research

  acp:
    enabled: false  # Planned
    endpoints:
      - name: external_agent
        url: https://acp.example.com/agent

  a2a:
    enabled: false  # Planned
    peers:
      - name: peer_agent
        url: https://peer.example.com/a2a
```

---

## Implementation Status

- ✅ RemoteAgentProtocol interface
- ✅ LangGraphRemoteAgent implementation
- ⚠️ ACPRemoteAgent (planned stub)
- ⚠️ A2ARemoteAgent (planned stub)
- ⚠️ CompiledSubAgent wrapping (future)
- ✅ Health check integration
- ✅ Streaming support (LangGraph)

---

## References

- RFC-000: System Conceptual Design (§9 Uniform delegation envelope)
- RFC-100: CoreAgent Runtime (tool execution)
- RFC-600: Plugin Extension System
- RFC-001: Core Modules Architecture (original Module 6)

---

## Changelog

### 2026-04-17
- Consolidated RFC-001 Module 6 (RemoteAgentProtocol) with all backend implementations (RFC-410-413)
- Defined LangGraphRemoteAgent primary implementation with ACP/A2A planned backends
- Specified future CompiledSubAgent wrapping for uniform task tool access
- Maintained transport-agnostic interface design
- Clarified current vs planned implementation status

---

*RemoteAgentProtocol remote agent invocation interface with LangGraph, ACP, and A2A backend implementations. Future CompiledSubAgent wrapping enables uniform task tool access.*
# Execution Protocols

**RFCs**: RFC-221 (LoopRunner)  
**Locations**:
- `packages/soothe/src/soothe/protocols/runner.py`

**Status**: Implemented  

## Overview

Execution protocols define the interfaces for running agents:

1. **LoopRunnerProtocol**: StrangeLoop runner orchestration

This protocol forms the execution layer, coordinating agent runs and streaming results.

## LoopRunnerProtocol

### Purpose

- **StrangeLoop orchestration**: Run complete Plan → Execute loops
- **Subprocess execution**: Worker pool management
- **Streaming**: Real-time result streaming
- **Timeout management**: Execution timeout and cancellation

### Protocol Interface

```python
class LoopRunnerProtocol(Protocol):
    """Protocol for StrangeLoop runner orchestration.
    
    Orchestrates complete Plan → Execute loops, handling subprocess
    execution, streaming, and timeout management.
    """

    async def run(
        self,
        request: LoopRunRequest,
    ) -> AsyncIterator[StreamChunk]:
        """Run StrangeLoop and stream results.
        
        Args:
            request: LoopRunRequest with all parameters.
            
        Yields:
            StreamChunk tuples (namespace, mode, data).
        """
        ...
```

### Data Models

#### LoopRunRequest

```python
@dataclass
class LoopRunRequest:
    """All parameters needed to run one agent loop in a subprocess.
    
    Consolidates fields previously passed ad-hoc to SootheRunner.astream(),
    including thread/workspace binding.
    
    Workspace resolution:
        - client_workspace set → use that path directly
        - else → $SOOTHE_HOME/workspaces/<normalized_user_id>/ws_<hash>
    """

    loop_id: str
    thread_id: str
    user_input: str
    client_workspace: str | None = None
    user_id: str | None = None
    client_workspace_id: str | None = None
    autonomous: bool = False
    max_iterations: int | None = None
    preferred_subagent: str | None = None
    model: str | None = None
    model_params: dict[str, Any] = field(default_factory=dict)
    
    # Worker pool timeout and cancellation support
    timeout_seconds: float | None = None
    
    # Intent hint to bypass LLM classification
    intent_hint: str | None = None
    
    # RFC-622: Clarification mode and answer handling
    clarification_mode: str | None = None
    clarification_answer: bool = False
    clarification_answers: list[str] | None = None
    
    # RFC-222 revised: Autopilot job dispatch
    autopilot_job: AutopilotJob | None = None
    
    def resolve_workspace_path(self) -> str:
        """Absolute workspace path for runner."""
        ...
```

#### AutopilotJob

```python
@dataclass(frozen=True)
class AutopilotJob:
    """Autopilot-dispatched goal job (RFC-222 revised).
    
    Attached to LoopRunRequest.autopilot_job when daemon's
    AutopilotService dispatches goal to subprocess worker.
    
    Attributes:
        goal_id: Daemon's canonical goal id.
        goal_description: Frozen at dispatch time.
        merged_context: Pre-projected hydration bundle.
        deadline_seconds: Wall-clock budget (None = no cap).
        attempt: 1 on first dispatch, N on retry/backoff.
    """

    goal_id: str
    goal_description: str
    merged_context: GoalDispatchContextBundle
    deadline_seconds: float | None = None
    attempt: int = 1
```

#### StreamChunk

```python
StreamChunk = tuple[tuple[str, ...], str, Any]
"""Deepagents-canonical stream chunk: (namespace, mode, data)."""
```

**Components**:
- **namespace**: Path tuple (e.g., `("agent", "loop")`)
- **mode**: Stream mode (e.g., `"messages", "updates", "custom"`)
- **data**: Payload data (e.g., message dict, event object)

### Backend Implementation

#### SootheRunner

**Status**: Current implementation  
**Location**: `packages/soothe/src/soothe/core/runner/`  

**Features**:
- Complete StrangeLoop orchestration
- Worker pool management
- Timeout handling
- Checkpoint persistence
- Streaming result delivery
- Autopilot job dispatch (RFC-222)

**Implementation Pattern**:
```python
class SootheRunner(LoopRunnerProtocol):
    """Runner implementation with full StrangeLoop orchestration."""
    
    async def run(
        self,
        request: LoopRunRequest,
    ) -> AsyncIterator[StreamChunk]:
        # Resolve workspace
        workspace = request.resolve_workspace_path()
        
        # Configure agent loop
        loop_config = self._configure_loop(request)
        
        # Run agent loop with streaming
        async for chunk in self._strange_loop.astream(
            input=request.user_input,
            config=loop_config,
            stream_mode=["messages", "updates", "custom"],
            subgraphs=True
        ):
            yield chunk
```

## RemoteAgentProtocol

### Purpose

- **Remote agent invocation**: Call agents via ACP, A2A, or LangGraph Remote
- **Streaming support**: Stream results from remote agents
- **Health checking**: Verify remote agent availability

### Protocol Interface

```python
@runtime_checkable
class RemoteAgentProtocol(Protocol):
    """Protocol for invoking remote agents via ACP, A2A, or LangGraph.
    
    Current implementations are accessed through RemoteAgentProtocol
    directly. Future remote backends may be wrapped as CompiledSubAgent
    instances for uniform task-tool access.
    """

    async def invoke(
        self, 
        task: str, 
        context: dict[str, Any] | None = None
    ) -> str:
        """Invoke the remote agent and return the result.
        
        Args:
            task: The task description.
            context: Optional context to pass to the remote agent.
            
        Returns:
            The agent's result as text.
        """
        ...

    async def stream(
        self, 
        task: str, 
        context: dict[str, Any] | None = None
    ) -> AsyncIterator[str]:
        """Stream results from the remote agent.
        
        Args:
            task: The task description.
            context: Optional context to pass.
            
        Yields:
            Incremental result chunks.
        """
        ...

    async def health_check(self) -> bool:
        """Check if the remote agent is reachable.
        
        Returns:
            True if the agent responded to health check.
        """
        ...
```

### Backend Implementations

Remote agent backends implement various protocols:

- **ACP**: Agent Communication Protocol (HTTP-based)
- **A2A**: Agent-to-Agent protocol (peer-to-peer)
- **LangGraph Remote**: LangGraph RemoteGraph

**Implementation Note**: Current implementations are accessed via protocol directly. Planned: wrap as `CompiledSubAgent` for uniform delegation envelope.

### Usage Patterns

```python
from soothe.protocols import RemoteAgentProtocol

# Invoke remote agent
remote_agent: RemoteAgentProtocol = resolve_remote_agent(config)

# Non-streaming invocation
result = await remote_agent.invoke(
    task="Analyze database performance",
    context={"database": "production"}
)

# Streaming invocation
async for chunk in remote_agent.stream(
    task="Generate migration plan",
    context={"schema": "current_schema"}
):
    print(chunk)

# Health check
is_reachable = await remote_agent.health_check()
```

## ToolkitProtocol

### Purpose

- **Tool collections**: Group related tools into cohesive kits
- **Instantiation**: Toolkits create tools with configuration
- **Domain organization**: Organize tools by domain (filesystem, web, etc.)

### Protocol Interface

```python
@runtime_checkable
class ToolkitProtocol(Protocol):
    """Protocol for toolkits -- collections of related tools.
    
    Each toolkit provides a cohesive set of tools for a specific domain.
    Toolkits are instantiated by resolver or plugin system with
    configuration parameters, and return BaseTool instances via get_tools().
    """

    def get_tools(self) -> list[BaseTool]:
        """Return all tools in this toolkit.
        
        Returns:
            List of langchain BaseTool instances.
        """
        ...
```

### Built-in Toolkits

Soothe provides several built-in toolkits:

- **FileSystemToolkit**: File operations (read, write, edit)
- **WebToolkit**: Web search, crawling, requests
- **ResearchToolkit**: Academic search, paper reading
- **ExecutionToolkit**: Shell commands, Python execution
- **MediaToolkit**: Image, audio, video analysis

**Example Implementation**:
```python
from langchain_core.tools import BaseTool
from soothe.protocols import ToolkitProtocol

class FileSystemToolkit(ToolkitProtocol):
    """Toolkit for filesystem operations."""
    
    def __init__(self, config: ToolkitConfig) -> None:
        self._config = config
    
    def get_tools(self) -> list[BaseTool]:
        """Return filesystem tools."""
        from soothe.toolkits.filesystem import (
            ReadFileTool,
            WriteFileTool,
            EditFileTool,
            ListDirectoryTool,
        )
        
        return [
            ReadFileTool(config=self._config),
            WriteFileTool(config=self._config),
            EditFileTool(config=self._config),
            ListDirectoryTool(config=self._config),
        ]
```

### Plugin Toolkits

Plugins can register custom toolkits:

```python
from soothe_sdk.plugin import plugin, tool

@plugin(name="my-plugin", version="1.0.0")
class MyPlugin:
    @tool(name="my_custom_tool", description="Custom tool")
    def my_custom_tool(self, arg: str) -> str:
        """Custom tool implementation."""
        return f"Processed: {arg}"
    
    def get_tools(self) -> list[BaseTool]:
        """Return plugin tools."""
        return [self.my_custom_tool]
```

### Usage Patterns

```python
from soothe.protocols import ToolkitProtocol
from soothe.core.resolver import resolve_toolkit

# Resolve toolkit
filesystem_kit: ToolkitProtocol = resolve_toolkit(
    "filesystem",
    config
)

# Get tools
tools = filesystem_kit.get_tools()

# Use in agent
agent = create_agent_with_tools(tools)

# Or add to tool registry
for tool in tools:
    registry.register(tool)
```

## Integration Patterns

### Runner ↔ LoopPlanner Integration

```
Runner execution flow:

1. LoopRunner.run(request)
   ↓
2. Resolve workspace and configuration
   ↓
3. Initialize StrangeLoop
   ↓
4. Loop iteration:
   a. LoopPlanner.plan() → PlanResult
   b. Execute decision → CoreAgent
   c. Collect StepResult
   d. Update LoopState
   ↓
5. Stream chunks to client
   ↓
6. Persist final state
```

### RemoteAgent ↔ Subagent Integration

Remote agents can be wrapped as subagents:

```python
# Current: Direct protocol access
remote: RemoteAgentProtocol = resolve_remote_agent(config)
result = await remote.invoke(task)

# Planned: CompiledSubAgent wrapper
from deepagents import CompiledSubAgent

remote_wrapper = CompiledSubAgent.from_remote_agent(remote)
# Use via task tool like local subagents
```

### Toolkit ↔ ToolRegistry Integration

Toolkits populate tool registry:

```python
from soothe.core.context.tool_registry import ToolRegistry

registry = ToolRegistry()

# Register toolkit tools
filesystem_tools = filesystem_kit.get_tools()
for tool in filesystem_tools:
    registry.register(tool)

# Registry provides unified tool access
available_tools = registry.get_available_tools()
```

## Configuration

### Runner Settings

```yaml
# config/config.template.yml
agent:
  runner:
    max_iterations: 8
    timeout_seconds: 600
    worker_pool_size: 4
    
  loop:
    autonomous: false
    preferred_subagent: null
```

### RemoteAgent Settings

```yaml
remote_agents:
  production_analyzer:
    type: acp
    endpoint: https://analyzer.example.com
    timeout: 30
    
  research_peer:
    type: a2a
    peer_id: research-agent-001
```

### Toolkit Settings

```yaml
toolkits:
  filesystem:
    enabled: true
    allowed_paths:
      - /project/**
      - /tmp/**
    
  web:
    enabled: true
    search_engine: tavily
```

## Testing

### Unit Tests

**Locations**:
- `packages/soothe/tests/unit/protocols/test_runner_autopilot_job.py`
- Toolkit tests in respective toolkit packages

Tests verify:
- LoopRunRequest workspace resolution
- AutopilotJob dispatch
- RemoteAgent health checks
- Toolkit tool instantiation

## Specification Reference

- **RFC-221**: Loop Runner Protocol and Ray
- **RFC-222**: Autopilot Goal Engine Architecture
- **RFC-622**: CoreAgent Clarification Relay
- **RFC-000**: System Conceptual Design (Module 6)
- **RFC-101**: Tool Interface

## Related Documentation

- [StrangeLoop Architecture](../sloop.md)
- [Planner Protocol](planner.md)
- [Plugin System](../plugins.md)
- [Tool Registry](../tool-registry.md)
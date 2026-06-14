# Agent Factory

CoreAgent construction and runtime factory.

---

## Overview

The agent factory module (`soothe.core.agent`) provides the foundational runtime for Soothe. Built on the `create_soothe_agent()` factory, CoreAgent delivers a CompiledStateGraph with built-in tools, subagents, and middlewares, executing through LangGraph's Model → Tools → Model loop.

**RFC**: [RFC-100](../../specs/RFC-100-coreagent-runtime.md)

---

## Architecture

### Factory Pattern

CoreAgent uses a factory pattern to assemble all components:

```
create_soothe_agent(config)
    ├─ Load Configuration
    ├─ Instantiate Protocols
    ├─ Resolve Models
    ├─ Assemble Tools/Subagents
    ├─ Load MCP Servers
    ├─ Wire Middlewares
    ├─ Create Deep Agent
    └─ Attach Protocols
```

### Construction Steps

1. **Load Configuration**: Resolve models, protocols, capabilities from SootheConfig
2. **Instantiate Protocols**: Context, Memory, Planner, Policy, Durability
3. **Resolve Models**: Map roles to provider:model strings
4. **Assemble Tools/Subagents**: Built-in + configured tools and subagents
5. **Load MCP Servers**: Via langchain-mcp-adapters
6. **Wire Middlewares**: Soothe-specific + deepagents middlewares
7. **Create Deep Agent**: Call `create_deep_agent()` to assemble graph
8. **Attach Protocols**: Add protocol instances as graph attributes

---

## Core Components

### AgentBuilder Class

Encapsulates all construction concerns:

```python
class AgentBuilder:
    """Builder for CoreAgent instances.
    
    Encapsulates:
    - Protocol resolution (memory, planner, policy)
    - Middleware stack construction
    - Backend initialization
    - Plugin loading
    - Tools/subagents resolution
    - MCP registry integration
    """
    
    def __init__(self, config: SootheConfig):
        self.config = config
        
    def build(self) -> CompiledStateGraph:
        """Construct and return CoreAgent instance."""
        # Resolve protocols
        memory = resolve_memory(self.config)
        planner = resolve_planner(self.config)
        policy = resolve_policy(self.config)
        
        # Assemble tools
        tools = resolve_tools(self.config)
        subagents = resolve_subagents(self.config)
        
        # Wire middlewares
        middlewares = build_soothe_middleware_stack(self.config)
        
        # Create agent
        return create_deep_agent(
            model=self.config.create_chat_model("default"),
            tools=tools,
            subagents=subagents,
            middlewares=middlewares,
            ...
        )
```

---

## Factory Function

### create_soothe_agent()

Main factory that creates Soothe's CoreAgent runtime:

```python
def create_soothe_agent(config: SootheConfig) -> CompiledStateGraph:
    """Factory that creates Soothe's CoreAgent runtime.
    
    Assembles:
    - Tools (built-in + configured)
    - Subagents (explore, plan, veritas, etc.)
    - MCP servers (via langchain-mcp-adapters)
    - Middlewares (Soothe + deepagents)
    - Protocol instances (context, memory, planner, policy, durability)
    
    Args:
        config: Soothe configuration instance
        
    Returns:
        CompiledStateGraph with attached protocol instances:
        - soothe_context: ContextProtocol instance
        - soothe_memory: MemoryProtocol instance
        - soothe_planner: PlannerProtocol instance
        - soothe_policy: PolicyProtocol instance
        - soothe_durability: DurabilityProtocol instance
        
    Example:
        config = SootheConfig.from_file("config.yml")
        agent = create_soothe_agent(config)
        
        async for chunk in agent.astream("query", config={"thread_id": "test"}):
            print(chunk)
    """
```

---

## Execution Interface

### Stream API

CoreAgent provides async streaming execution:

```python
agent.astream(
    input: str | dict,
    config: RunnableConfig
) -> AsyncIterator[StreamChunk]
```

**Config Parameters**:
```python
config = {
    "configurable": {
        "thread_id": str,      # Thread identifier
        "recursion_limit": int # Max recursion depth
    }
}
```

**Stream Output**:
```python
AsyncIterator[StreamChunk]  # Yields events:
    - messages: LLM messages
    - tool_calls: Tool execution events
    - custom_events: Soothe-specific events
    - tokens: Token streaming
```

---

## Execution Flow

```
agent.astream(input, config)
    → LangGraph execution:
        ├─ Model turn
        │  └─ LLM processes input
        │  └─ Decides tool calls
        ├─ Tool execution
        │  └─ Execute tools
        │  └─ Collect results
        │  └─ Apply middlewares
        ├─ Model turn
        │  └─ LLM processes results
        │  └─ Decides more tools or final response
        └─ Stream output
           └─ Yield events
```

---

## Attached Protocols

After construction, the agent has protocol instances attached as attributes:

```python
agent = create_soothe_agent(config)

# Access attached protocols
agent.soothe_context    # ContextProtocol
agent.soothe_memory     # MemoryProtocol
agent.soothe_planner    # PlannerProtocol
agent.soothe_policy     # PolicyProtocol
agent.soothe_durability # DurabilityProtocol
```

---

## Middleware Stack

Soothe injects 5 specific middlewares into the agent:

### 1. SoothePolicyMiddleware
Enforces security policies on tool execution.

### 2. SystemPromptMiddleware
Injects system prompts and context.

### 3. ExecutionHintsMiddleware
Applies execution hints from configuration.

### 4. WorkspaceContextMiddleware
Provides workspace context to tools.

### 5. SubagentContextMiddleware
Manages subagent context isolation.

---

## Usage Patterns

### Basic Execution

```python
from soothe.core.agent import create_soothe_agent
from soothe.config import SootheConfig

config = SootheConfig.from_file("config.yml")
agent = create_soothe_agent(config)

# Execute query
async for chunk in agent.astream("Analyze the codebase"):
    print(chunk)
```

### Thread-Based Execution

```python
# Execute with thread ID
async for chunk in agent.astream(
    "Query",
    config={"configurable": {"thread_id": "thread-123"}}
):
    print(chunk)
```

### Protocol Access

```python
# Access attached protocols
context = agent.soothe_context

# Use context for retrieval
projection = await context.project("goal", token_budget=2000)
```

---

## Integration Points

### StrangeLoop Integration

CoreAgent serves as Layer 1 foundation for StrangeLoop:

```python
# StrangeLoop uses CoreAgent for Execute phase
class StrangeLoop:
    async def execute_step(self, step: PlanStep):
        # Delegate to CoreAgent
        async for chunk in self.agent.astream(step.prompt):
            yield chunk
```

### CLI/Daemon Usage

Direct usage in CLI and daemon:

```python
# CLI one-shot execution
soothe -p "query"

# Daemon WebSocket handling
async def handle_query(ws, query):
    agent = create_soothe_agent(config)
    async for event in agent.astream(query):
        ws.send(event)
```

---

## Advanced Features

### Model Override

Per-execution model override:

```python
# Override model for specific execution
agent.astream(
    "Complex reasoning task",
    config={
        "configurable": {
            "model_override": "openai:o3-mini"
        }
    }
)
```

### Tool Filtering

Dynamic tool filtering:

```python
# Filter tools for sandbox mode
agent = without_execute_tool_when_sandbox_disabled(agent)
```

### Checkpoint Integration

```python
# Use checkpointer for durability
agent.astream(
    "query",
    config={
        "configurable": {
            "thread_id": "thread-123",
            "checkpointer": checkpointer
        }
    }
)
```

---

## Configuration

### Model Routing

Configure models by purpose:

```yaml
router:
  default: "openai:gpt-4o-mini"  # CoreAgent default
  think: "openai:o3-mini"        # Complex reasoning
  fast: "openai:gpt-4o-mini"     # Quick tasks
```

### Tool Configuration

Enable/disable tools:

```yaml
tools:
  execution:
    enabled: true
  websearch:
    enabled: true
  research:
    enabled: true
```

### Subagent Configuration

Configure subagents:

```yaml
subagents:
  explore:
    enabled: true
  plan:
    enabled: true
  veritas:
    enabled: true
```

---

## Related Documentation

- **[SootheRunner](runner.md)** - Protocol orchestration
- **[StrangeLoop](strangeloop.md)** - Plan-Execute loop
- **[Protocol Resolver](resolver.md)** - Protocol wiring
- **[Middleware](../architecture/middleware.md)** - Middleware details
- **[RFC-100](../../specs/RFC-100-coreagent-runtime.md)** - Full specification

---

## API Reference

### Core Functions

```python
# Factory function
def create_soothe_agent(config: SootheConfig) -> CompiledStateGraph:
    """Create CoreAgent runtime."""

# Builder class
class AgentBuilder:
    def __init__(self, config: SootheConfig): ...
    def build(self) -> CompiledStateGraph: ...
```

### CoreAgent Class

```python
class CoreAgent:
    """CoreAgent wrapper with protocol attachments."""
    
    # Protocol attributes
    soothe_context: ContextProtocol
    soothe_memory: MemoryProtocol
    soothe_planner: PlannerProtocol
    soothe_policy: PolicyProtocol
    soothe_durability: DurabilityProtocol
    
    # Execution methods
    async def astream(self, input, config): ...
```

---

## See Also

- **[Tool Interface](../../specs/RFC-101-tool-interface.md)** - Tool design
- **[Subagents](../modules/subagents/README.md)** - Built-in subagents
- **[MCP Servers](../user-guide/mcp-servers.md)** - MCP integration
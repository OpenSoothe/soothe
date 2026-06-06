# Protocol Resolver

Wire protocols from configuration to runtime instances.

---

## Overview

The protocol resolver (`soothe.core.resolver`) wires protocol instances from SootheConfig, connecting configuration declarations to runtime protocol implementations. It handles checkpointer resolution, durability setup, goal engine instantiation, and tools/subagents wiring.

---

## Architecture

### Resolver Pattern

Protocol resolver connects configuration to implementation:

```
Protocol Resolver Flow
├─ Configuration Loading
│  ├─ Parse YAML config
│  ├─ Resolve providers
│  └─ Map model routing
│
├─ Protocol Resolution
│  ├─ ContextProtocol → Backend implementation
│  ├─ MemoryProtocol → Backend implementation
│  ├─ PlannerProtocol → Backend implementation
│  ├─ PolicyProtocol → Backend implementation
│  ├─ DurabilityProtocol → Backend implementation
│  └─ GoalEngine → Engine instance
│
├─ Capability Resolution
│  ├─ Tools → Tool registry
│  ├─ Subagents → Subagent registry
│  └─ MCP servers → MCP registry
│
└─ Dependency Injection
   ├─ Attach to agent
   └─ Configure middleware
```

---

## Core Functions

### Protocol Resolution

Resolve protocol instances from configuration:

```python
def resolve_context(config: SootheConfig) -> ContextProtocol:
    """Resolve ContextProtocol from config.
    
    Args:
        config: Soothe configuration
        
    Returns:
        ContextProtocol implementation instance
    """

def resolve_memory(config: SootheConfig) -> MemoryProtocol:
    """Resolve MemoryProtocol from config."""

def resolve_planner(config: SootheConfig) -> PlannerProtocol:
    """Resolve PlannerProtocol from config."""

def resolve_policy(config: SootheConfig) -> PolicyProtocol:
    """Resolve PolicyProtocol from config."""

def resolve_durability(config: SootheConfig) -> DurabilityProtocol:
    """Resolve DurabilityProtocol from config."""

def resolve_goal_engine(config: SootheConfig) -> GoalEngine:
    """Resolve GoalEngine from config."""
```

### Capability Resolution

Resolve tools and subagents:

```python
def resolve_tools(config: SootheConfig) -> list[BaseTool]:
    """Resolve tools from config.
    
    Args:
        config: Soothe configuration
        
    Returns:
        List of BaseTool instances
    """

def resolve_subagents(config: SootheConfig) -> list[SubAgent]:
    """Resolve subagents from config."""

def resolve_mcp_servers(config: SootheConfig) -> dict:
    """Resolve MCP servers from config."""
```

### Checkpointer Resolution

Resolve checkpointer for durability:

```python
def resolve_checkpointer(config: SootheConfig) -> Checkpointer:
    """Resolve checkpointer from config.
    
    Args:
        config: Soothe configuration
        
    Returns:
        LangGraph Checkpointer instance
    """
```

---

## Resolution Process

### Backend Resolution

Resolve protocol backend implementation:

```python
def resolve_context_backend(config: SootheConfig) -> ContextProtocol:
    """Resolve context backend from config."""
    
    backend_type = config.context_backend  # "keyword" or "vector"
    
    if backend_type == "keyword":
        return KeywordContext(
            persist_dir=config.context_persist_dir,
            ...
        )
    elif backend_type == "vector":
        vector_store = resolve_vector_store(config)
        return VectorContext(
            vector_store=vector_store,
            embedding_model=config.create_embedding_model(),
            ...
        )
    else:
        raise ValueError(f"Unknown context backend: {backend_type}")
```

### Backend Types

ContextProtocol backends:
- `keyword`: KeywordContext (keyword/tag matching)
- `vector`: VectorContext (semantic search)

MemoryProtocol backends:
- `keyword`: KeywordMemory (keyword matching)
- `vector`: VectorMemory (semantic search)

PlannerProtocol backends:
- `simple`: SimplePlanner
- `subagent`: SubagentPlanner
- `model`: Model-specific planner
- `auto`: AutoPlanner (model selection)

PolicyProtocol backends:
- `config`: ConfigDrivenPolicy

DurabilityProtocol backends:
- `json`: JsonDurability
- `rocksdb`: RocksDBDurability
- `postgres`: PostgreSQLDurability

---

## Dependency Injection

### Protocol Attachment

Attach resolved protocols to agent:

```python
def attach_protocols(
    agent: CompiledStateGraph,
    config: SootheConfig
) -> CompiledStateGraph:
    """Attach resolved protocols to agent."""
    
    # Resolve protocols
    context = resolve_context(config)
    memory = resolve_memory(config)
    planner = resolve_planner(config)
    policy = resolve_policy(config)
    durability = resolve_durability(config)
    
    # Attach as attributes
    agent.soothe_context = context
    agent.soothe_memory = memory
    agent.soothe_planner = planner
    agent.soothe_policy = policy
    agent.soothe_durability = durability
    
    return agent
```

### Middleware Configuration

Configure middleware with resolved protocols:

```python
def configure_middlewares(
    config: SootheConfig,
    context: ContextProtocol,
    memory: MemoryProtocol,
    planner: PlannerProtocol,
    policy: PolicyProtocol
) -> list[AgentMiddleware]:
    """Configure middlewares with protocols."""
    
    middlewares = [
        SoothePolicyMiddleware(policy),
        SystemPromptMiddleware(config),
        ExecutionHintsMiddleware(config),
        WorkspaceContextMiddleware(config),
        SubagentContextMiddleware(planner)
    ]
    
    return middlewares
```

---

## Configuration Mapping

### YAML to Instance Mapping

Map configuration to runtime instances:

```yaml
# Configuration YAML
context_backend: keyword
context_persist_dir: ~/.soothe/context

memory_backend: keyword
memory_persist_dir: ~/.soothe/memory

planner_routing: auto

policy_backend: config

durability_backend: json
durability_persist_dir: ~/.soothe/durability
```

```python
# Resolver mapping
context = resolve_context(config)
# → KeywordContext(persist_dir="~/.soothe/context")

memory = resolve_memory(config)
# → KeywordMemory(persist_dir="~/.soothe/memory")

planner = resolve_planner(config)
# → AutoPlanner(config)

policy = resolve_policy(config)
# → ConfigDrivenPolicy(config)

durability = resolve_durability(config)
# → JsonDurability(persist_dir="~/.soothe/durability")
```

---

## Backend Dependencies

### Vector Backend Dependencies

Vector backends require vector store and embeddings:

```python
def resolve_vector_backend(config: SootheConfig):
    """Resolve vector backend with dependencies."""
    
    # Vector store
    vector_store = resolve_vector_store(config)
    
    # Embedding model
    embedding_model = config.create_embedding_model()
    
    # Create backend
    return VectorBackend(
        vector_store=vector_store,
        embedding_model=embedding_model
    )
```

### Planner Dependencies

Planner requires model for reasoning:

```python
def resolve_planner(config: SootheConfig):
    """Resolve planner with model."""
    
    routing = config.planner_routing
    
    if routing == "auto":
        # Auto-select model based on task
        return AutoPlanner(config)
    elif routing == "subagent":
        # Use plan subagent
        plan_subagent = resolve_plan_subagent(config)
        return SubagentPlanner(plan_subagent)
    else:
        # Use model-specific planner
        model = config.create_chat_model("think")
        return ModelPlanner(model)
```

---

## Tool Resolution

### Tool Registry

Resolve tools from configuration:

```python
def resolve_tools(config: SootheConfig) -> list[BaseTool]:
    """Resolve tools from config."""
    
    tools = []
    
    # Built-in tools
    if config.tools.execution.enabled:
        tools.extend(get_execution_tools())
    
    if config.tools.websearch.enabled:
        tools.extend(get_websearch_tools())
    
    if config.tools.research.enabled:
        tools.extend(get_research_tools())
    
    # Plugin tools
    plugin_tools = load_plugin_tools(config)
    tools.extend(plugin_tools)
    
    # MCP tools
    mcp_tools = load_mcp_tools(config)
    tools.extend(mcp_tools)
    
    return tools
```

### Tool Configuration

```yaml
tools:
  execution:
    enabled: true
    sandbox: true  # Sandbox mode
  
  websearch:
    enabled: true
    engines: [tavily, duckduckgo]
  
  research:
    enabled: true
  
  documents:
    enabled: true
  
  media:
    enabled: true
```

---

## Subagent Resolution

### Subagent Registry

Resolve subagents from configuration:

```python
def resolve_subagents(config: SootheConfig) -> list[SubAgent]:
    """Resolve subagents from config."""
    
    subagents = []
    
    # Built-in subagents
    if config.subagents.explore.enabled:
        subagents.append(create_explore_subagent())
    
    if config.subagents.plan.enabled:
        subagents.append(create_plan_subagent())
    
    if config.subagents.veritas.enabled:
        subagents.append(create_veritas_subagent())
    
    # Plugin subagents
    plugin_subagents = load_plugin_subagents(config)
    subagents.extend(plugin_subagents)
    
    return subagents
```

### Subagent Configuration

```yaml
subagents:
  explore:
    enabled: true
  
  plan:
    enabled: true
  
  veritas:
    enabled: true
  
  tacitus:
    enabled: true
  
  claude:
    enabled: false  # Optional
  
  browser_use:
    enabled: false  # Optional
```

---

## MCP Server Resolution

### MCP Registry

Resolve MCP servers from configuration:

```python
def resolve_mcp_servers(config: SootheConfig) -> dict:
    """Resolve MCP servers from config."""
    
    mcp_servers = {}
    
    for server_config in config.mcp.servers:
        # Load MCP server
        server = load_mcp_server(server_config)
        
        # Register tools
        tools = server.get_tools()
        mcp_servers[server_config.name] = {
            "server": server,
            "tools": tools
        }
    
    return mcp_servers
```

### MCP Configuration

```yaml
mcp:
  servers:
    - name: filesystem
      command: mcp-server-filesystem
      args: ["/path/to/workspace"]
    
    - name: github
      command: mcp-server-github
      env:
        GITHUB_TOKEN: "${GITHUB_TOKEN}"
```

---

## Checkpointer Resolution

### Checkpointer Types

Resolve checkpointer for thread durability:

```python
def resolve_checkpointer(config: SootheConfig) -> Checkpointer:
    """Resolve checkpointer from config."""
    
    durability = resolve_durability(config)
    
    # Create checkpointer based on durability backend
    if config.durability_backend == "json":
        return JsonCheckpointer(durability)
    elif config.durability_backend == "rocksdb":
        return RocksDBCheckpointer(durability)
    elif config.durability_backend == "postgres":
        return PostgresCheckpointer(durability)
```

---

## Usage Patterns

### Basic Resolution

```python
from soothe.core.resolver import (
    resolve_context,
    resolve_memory,
    resolve_tools
)
from soothe.config import SootheConfig

config = SootheConfig.from_file("config.yml")

# Resolve protocols
context = resolve_context(config)
memory = resolve_memory(config)

# Resolve capabilities
tools = resolve_tools(config)
subagents = resolve_subagents(config)
```

### Agent Construction

```python
from soothe.core.agent import create_soothe_agent

# Resolver is called internally
agent = create_soothe_agent(config)

# Protocols already attached
agent.soothe_context  # ContextProtocol instance
agent.soothe_memory   # MemoryProtocol instance
```

---

## Error Handling

### Resolution Errors

Handle resolution failures:

```python
try:
    context = resolve_context(config)
except BackendNotFoundError as e:
    logger.error(f"Backend not found: {e.backend}")
    # Fallback to default
    context = KeywordContext()

try:
    tools = resolve_tools(config)
except ToolLoadError as e:
    logger.error(f"Tool load failed: {e.tool}")
    # Skip failed tool
```

---

## Configuration

### Resolution Settings

```yaml
resolution:
  fallback_backend: keyword  # Fallback backend on error
  validate_backends: true    # Validate backend availability
  load_plugins: true         # Load plugin tools/subagents
```

---

## Related Documentation

- **[Agent Factory](agent-factory.md)** - Agent construction
- **[SootheRunner](runner.md)** - Runner integration
- **[Protocols](../architecture/protocol-first.md)** - Protocol definitions
- **[Backends](../modules/backends/README.md)** - Backend implementations
- **[RFC-001](../../specs/RFC-001-core-modules-architecture.md)** - Architecture spec

---

## API Reference

### Core Functions

```python
# Protocol resolution
def resolve_context(config: SootheConfig) -> ContextProtocol: ...
def resolve_memory(config: SootheConfig) -> MemoryProtocol: ...
def resolve_planner(config: SootheConfig) -> PlannerProtocol: ...
def resolve_policy(config: SootheConfig) -> PolicyProtocol: ...
def resolve_durability(config: SootheConfig) -> DurabilityProtocol: ...
def resolve_goal_engine(config: SootheConfig) -> GoalEngine: ...

# Capability resolution
def resolve_tools(config: SootheConfig) -> list[BaseTool]: ...
def resolve_subagents(config: SootheConfig) -> list[SubAgent]: ...
def resolve_mcp_servers(config: SootheConfig) -> dict: ...

# Checkpointer resolution
def resolve_checkpointer(config: SootheConfig) -> Checkpointer: ...
```

### Helper Functions

```python
def resolve_vector_store(config: SootheConfig) -> VectorStoreProtocol: ...
def resolve_embedding_model(config: SootheConfig) -> Embeddings: ...

def load_plugin_tools(config: SootheConfig) -> list[BaseTool]: ...
def load_plugin_subagents(config: SootheConfig) -> list[SubAgent]: ...

def load_mcp_server(config: dict) -> MCPServer: ...
```

---

## See Also

- **[Configuration](../configuration.md)** - Configuration system
- **[Protocol Layer](../architecture/protocol-first.md)** - Protocol overview
- **[Backend Implementations](../modules/backends/README.md)** - Backend details
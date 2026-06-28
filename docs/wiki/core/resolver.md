# Protocol Resolver

Wire protocols from configuration to runtime instances.

---

## Overview

The protocol resolver (`soothe.runner.resolver`) wires protocol instances from SootheConfig, connecting configuration declarations to runtime protocol implementations. It handles checkpointer resolution, durability setup, and tools/subagents wiring.

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
│  ├─ MemoryProtocol → Backend implementation
│  ├─ PlannerProtocol → Backend implementation
│  ├─ PolicyProtocol → Backend implementation
│  └─ DurabilityProtocol → Backend implementation
│
├─ Capability Resolution
│  ├─ Tools → Tool registry
│  └─ Subagents → Subagent registry
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
def resolve_memory(config: SootheConfig) -> MemoryProtocol | None:
    """Resolve MemoryProtocol from config.

    Args:
        config: Soothe configuration

    Returns:
        A MemoryProtocol instance, or None if disabled.
    """

def resolve_planner(
    config: SootheConfig,
    model: BaseChatModel | None,
) -> PlannerProtocol:
    """Resolve LLMPlanner as the sole planner implementation.

    Args:
        config: Soothe configuration.
        model: The resolved chat model.

    Returns:
        LLMPlanner instance.
    """

def resolve_policy(config: SootheConfig) -> PolicyProtocol | None:
    """Resolve PolicyProtocol from config.

    Args:
        config: Soothe configuration

    Returns:
        A PolicyProtocol instance, or None if disabled.
    """

def resolve_durability(config: SootheConfig) -> DurabilityProtocol:
    """Resolve DurabilityProtocol from config.

    Supports: postgresql, sqlite backends.
    """
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

### Backend Types

MemoryProtocol backends:
- `memu`: MemUMemory (semantic search + keyword indexing)

PlannerProtocol backends:
- `llm`: LLMPlanner (unified, IG-150 consolidation)

PolicyProtocol backends:
- `config`: ConfigDrivenPolicy (profile-based)

DurabilityProtocol backends:
- `sqlite`: SQLiteDurability (via SQLitePersistStore)
- `postgres`: PostgreSQLDurability (via PostgreSQLPersistStore)

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
    memory = resolve_memory(config)
    planner = resolve_planner(config)
    policy = resolve_policy(config)
    durability = resolve_durability(config)

    # Attach as attributes
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
agent:
  protocols:
    memory:
      enabled: true
      llm_chat_role: think
      llm_embed_role: embedding

    planner:
      enabled: true
      model: think

    policy:
      enabled: true
      profile: standard

    durability:
      enabled: true
      backend: sqlite
```

```python
# Resolver mapping
memory = resolve_memory(config)
# → MemUMemory(config)

planner = resolve_planner(config, model)
# → LLMPlanner(model=model, config=config)

policy = resolve_policy(config)
# → ConfigDrivenPolicy(config=config)

durability = resolve_durability(config)
# → SQLiteDurability(db_path=...) or PostgreSQLDurability(persist_store=...)
```

---

## Backend Dependencies

### Planner Dependencies

Planner requires model for reasoning:

```python
def resolve_planner(config: SootheConfig, model: BaseChatModel | None):
    """Resolve planner with model."""
    from soothe.foundation.loop.planning.planner import LLMPlanner
    return LLMPlanner(model=model, config=config)
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

## Checkpointer Resolution

### Checkpointer Types

Resolve checkpointer for thread durability:

```python
def resolve_checkpointer(config: SootheConfig) -> tuple[Checkpointer, Any] | Checkpointer:
    """Resolve checkpointer from config.

    Uses persistence configuration for PostgreSQL or SQLite connection.
    No fallback to in-memory storage - persistent storage required.

    Returns:
        A tuple of (checkpointer, connection_resource) for PostgreSQL, or
        just the checkpointer for SQLite. The connection_resource must be
        closed during cleanup (e.g., via runner.cleanup()).
    """
    backend = config.resolve_checkpointer_backend()
    if backend == "postgresql":
        # Uses SharedCheckpointerPool for PostgreSQL
        ...
    if backend == "sqlite":
        # Resolves db_path, defers AsyncSqliteSaver to async context
        ...
```

---

## Usage Patterns

### Basic Resolution

```python
from soothe.runner.resolver import (
    resolve_memory,
    resolve_tools,
    resolve_subagents,
)
from soothe.config import SootheConfig

config = SootheConfig.from_yaml_file("config.yml")

# Resolve protocols
memory = resolve_memory(config)

# Resolve capabilities
tools = resolve_tools(config)
subagents = resolve_subagents(config)
```

### Agent Construction

```python
from soothe.foundation.core.agent import create_soothe_agent

# Resolver is called internally
agent = create_soothe_agent(config)

# Protocols already attached
agent.soothe_memory   # MemoryProtocol instance
```

---

## Error Handling

### Resolution Errors

Handle resolution failures:

```python
try:
    memory = resolve_memory(config)
except BackendNotFoundError as e:
    logger.error(f"Backend not found: {e.backend}")
    # Fallback to default memory backend
    memory = MemUMemory(config)

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
def resolve_memory(config: SootheConfig) -> MemoryProtocol | None: ...
def resolve_planner(config: SootheConfig, model: BaseChatModel | None) -> PlannerProtocol: ...
def resolve_policy(config: SootheConfig) -> PolicyProtocol | None: ...
def resolve_durability(config: SootheConfig) -> DurabilityProtocol: ...

# Capability resolution
def resolve_tools(config: SootheConfig) -> list[BaseTool]: ...
def resolve_subagents(config: SootheConfig) -> list[SubAgent]: ...

# Infrastructure resolution
def resolve_checkpointer(config: SootheConfig) -> tuple[Checkpointer, Any] | Checkpointer: ...
```

### Helper Functions

```python
def load_plugin_tools(config: SootheConfig) -> list[BaseTool]: ...
def load_plugin_subagents(config: SootheConfig) -> list[SubAgent]: ...
```

---

## See Also

- **[Configuration](../configuration-guide/README.md)** - Configuration system
- **[Protocol Layer](../architecture/protocol-first.md)** - Protocol overview
- **[Backend Implementations](../modules/backends/README.md)** - Backend details
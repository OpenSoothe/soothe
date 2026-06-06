# Extension Patterns

The **Plugin System** (RFC-600) provides a decorator-based API for extending Soothe with custom subagents, tools, and MCP integration. This guide covers patterns for creating, registering, and managing custom capabilities.

## Overview

### Plugin System Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  Discovery Engine                                                   │
│  - Entry points (pyproject.toml)                                   │
│  - Config-declared (config.yml)                                    │
│  - Filesystem (~/.soothe/plugins/)                                 │
└────────────────────────┬───────────────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────────────┐
│  Manifest Registry                                                  │
│  - Validation                                                       │
│  - Storage                                                          │
│  - Lookup                                                           │
└────────────────────────┬───────────────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────────────┐
│  Dependency Resolver                                                │
│  - Library dependencies (PEP 440)                                  │
│  - Configuration dependencies                                       │
└────────────────────────┬───────────────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────────────┐
│  Plugin Loader                                                      │
│  - Import module                                                    │
│  - Call on_load() hook                                             │
│  - Register tools/subagents                                         │
└────────────────────────┬───────────────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────────────┐
│  Plugin Registry                                                    │
│  - Runtime tool lookup                                              │
│  - Runtime subagent lookup                                          │
│  - Priority-based conflict resolution                               │
└────────────────────────────────────────────────────────────────────┘
```

### Extension Points

Soothe supports three extension points:

| Extension Point | Decorator | Returns |
|----------------|-----------|---------|
| **Tools** | `@tool` | `BaseTool` or callable |
| **Subagents** | `@subagent` | `CompiledSubAgent` runnable |
| **Events** | `register_event()` | Event class registration |

### Trust Levels

Plugins declare trust levels for security boundaries:

| Level | Permissions | Use Case |
|-------|-------------|----------|
| **built-in** | Full permissions | Core capabilities (explore, plan, tacitus) |
| **trusted** | Elevated permissions | Verified third-party plugins |
| **standard** | Default permissions | Most third-party plugins |
| **untrusted** | Restricted permissions | Experimental/plugins under review |

## Plugin Development

### Basic Plugin Structure

```python
from soothe_sdk.plugin import plugin, tool, subagent

@plugin(
    name="my-plugin",
    version="1.0.0",
    description="My custom plugin",
    dependencies=["langchain>=0.1.0"],
    trust_level="standard",
)
class MyPlugin:
    """Custom plugin for specialized operations."""
    
    async def on_load(self, context):
        """Initialize plugin resources."""
        self.api_key = context.config.get("api_key")
        context.logger.info("Loaded my-plugin v1.0.0")
    
    async def on_unload(self):
        """Cleanup plugin resources."""
        # Cleanup code
    
    async def health_check(self):
        """Return health status."""
        return PluginHealth(status="healthy", message="All systems operational")
```

### PluginContext Fields

The `context` object in `on_load()` provides:

```python
class PluginContext:
    config: dict              # Plugin-specific configuration
    soothe_config: SootheConfig  # Global configuration
    logger: Logger            # Python logger instance
    work_dir: str             # Workspace directory
    emit_event: callable      # Event emission function
```

### Manifest Fields

```python
@plugin(
    name="my-plugin",         # Required: unique identifier (lowercase, hyphenated)
    version="1.0.0",          # Required: semantic version
    description="...",",      # Required: human-readable description
    author="Author Name",     # Optional: author information
    dependencies=[            # Optional: library dependencies (PEP 440)
        "langchain>=0.1.0",
        "arxiv>=2.0.0",
    ],
    config_requirements=[     # Optional: configuration dependencies
        "providers.openai.api_key",
    ],
    python_version=">=3.11",  # Optional: Python version requirement
    soothe_version=">=0.1.0", # Optional: Soothe version requirement
    trust_level="standard",   # Optional: built-in | trusted | standard | untrusted
)
```

### Lifecycle Hooks

```python
class MyPlugin:
    async def on_load(self, context):
        """Called when plugin is loaded.
        
        Use for:
        - Initializing resources
        - Validating configuration
        - Setting up connections
        
        Args:
            context: PluginContext with config, logger, work_dir.
        """
        pass
    
    async def on_unload(self):
        """Called when plugin is unloaded.
        
        Use for:
        - Cleanup resources
        - Closing connections
        - Saving state
        """
        pass
    
    async def health_check(self):
        """Called periodically to check plugin health.
        
        Returns:
            PluginHealth with status and message.
        """
        return PluginHealth(status="healthy")
```

## Creating Tools

### Simple Tool (Callable)

```python
from soothe_sdk.plugin import plugin, tool

@plugin(name="my-tools", version="1.0.0")
class MyToolsPlugin:
    @tool(
        name="greet",
        description="Greet someone by name",
    )
    def greet(self, name: str) -> str:
        """Greet a person.
        
        Args:
            name: Name of the person to greet.
            
        Returns:
            Greeting message.
        """
        return f"Hello, {name}!"
```

### Structured Tool (BaseTool)

```python
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

class AnalyzeInput(BaseModel):
    """Input for analyze_data tool."""
    file_path: str = Field(description="Path to data file")
    analysis_type: str = Field(default="summary", description="Type of analysis")

class AnalyzeDataTool(BaseTool):
    """Analyze data file with configurable analysis type."""
    name: str = "analyze_data"
    description: str = "Analyze CSV/JSON data file. Returns statistics."
    args_schema: type[BaseModel] = AnalyzeInput
    
    def _run(self, file_path: str, analysis_type: str = "summary") -> str:
        """Execute analysis synchronously."""
        # Implementation
        return analysis_result
    
    async def _arun(self, file_path: str, analysis_type: str = "summary") -> str:
        """Execute analysis asynchronously."""
        return self._run(file_path, analysis_type)

@plugin(name="my-tools", version="1.0.0")
class MyToolsPlugin:
    @tool(name="analyze_data", description="Analyze data files")
    def create_analyze_tool(self) -> BaseTool:
        return AnalyzeDataTool()
```

### Tool with Security

```python
from soothe.core.security.operation_security import WorkspaceToolOperationSecurity
from soothe.protocols.operation_security import OperationSecurityRequest

class SecureFileTool(BaseTool):
    """Secure file operation tool."""
    name: str = "secure_read"
    description: str = "Read file with workspace boundary enforcement"
    
    def _run(self, file_path: str, runtime: Any = None) -> str:
        """Execute with security checks."""
        # Resolve workspace
        workspace = resolve_workspace_for_tool_execution(runtime)
        
        # Apply security
        security = WorkspaceToolOperationSecurity(workspace)
        request = OperationSecurityRequest(
            operation="read",
            target=file_path,
        )
        
        allowed, reason = security.check(request)
        if not allowed:
            raise PermissionError(f"Operation denied: {reason}")
        
        # Execute safely
        return read_file_content(workspace / file_path)

@plugin(name="secure-tools", version="1.0.0")
class SecureToolsPlugin:
    @tool(name="secure_read")
    def create_secure_tool(self) -> BaseTool:
        return SecureFileTool()
```

### Tool Events

```python
from soothe.core.event_catalog import register_event
from soothe.core.base_events import SootheEvent

class AnalyzeEvent(SootheEvent):
    """Event for analyze_data tool."""
    type: str = "soothe.tool.my_tools.analyze"
    file_path: str
    analysis_type: str

# Register at module load
register_event(
    AnalyzeEvent,
    summary_template="Analyzed {file_path} with {analysis_type}"
)

@plugin(name="my-tools", version="1.0.0")
class MyToolsPlugin:
    @tool(name="analyze_data")
    def analyze_data(self, file_path: str, analysis_type: str = "summary") -> str:
        """Analyze data file."""
        # Emit event
        emit_event(AnalyzeEvent(
            file_path=file_path,
            analysis_type=analysis_type,
        ))
        
        return analysis_result
```

## Creating Subagents

### Basic Subagent Pattern

```python
from soothe_sdk.plugin import plugin, subagent
from langgraph.graph import StateGraph, END
from typing import Annotated
from typing_extensions import TypedDict

@plugin(name="my-agent", version="1.0.0")
class MyAgentPlugin:
    @subagent(
        name="my_agent",
        description="Custom analysis agent",
        triggers=["analyze", "process"],  # Keywords for auto-routing
    )
    async def create_agent(self, model, config, context):
        """Create subagent runnable."""
        return create_my_agent(model, config, context)

def create_my_agent(model, config, context):
    """Factory function for my_agent subagent."""
    # Define state schema
    class MyAgentState(TypedDict):
        messages: Annotated[list, add_messages]  # Required
        target: str
        findings: list[dict]
        result: dict | None
    
    # Build graph
    graph = StateGraph(MyAgentState)
    
    # Add nodes
    graph.add_node("analyze", analyze_node)
    graph.add_node("process", process_node)
    graph.add_node("finalize", finalize_node)
    
    # Add edges
    graph.add_edge("analyze", "process")
    graph.add_conditional_edges("process", should_continue, {
        "continue": "analyze",
        "finish": "finalize",
    })
    graph.add_edge("finalize", END)
    
    # Compile
    return graph.compile()
```

### Subagent with Tools

```python
from deepagents import create_react_agent

@plugin(name="research-agent", version="1.0.0")
class ResearchAgentPlugin:
    @subagent(
        name="researcher",
        description="Research agent with web and academic tools",
    )
    async def create_agent(self, model, config, context):
        """Create research agent."""
        # Create tools
        tools = [
            WebSearchTool(),
            AcademicSearchTool(),
            URLCrawlTool(),
        ]
        
        # Create ReAct agent
        agent = create_react_agent(model, tools)
        
        return agent
```

### Subagent State Schema

```python
from typing import Annotated
from typing_extensions import TypedDict
from operator import add

class MyAgentState(TypedDict):
    """State schema for my_agent subagent."""
    
    # Required: messages with add_messages reducer
    messages: Annotated[list, add_messages]
    
    # Domain-specific fields
    target: str              # Input: search target
    workspace: str           # Input: workspace boundary
    findings: Annotated[list, add]  # Accumulated findings
    iterations_used: int     # Current iteration count
    max_iterations: int      # Cap from thoroughness level
    assessment_decision: str # "continue" | "adjust" | "finish"
    
    # Output fields
    result: dict | None      # Structured output
```

### Subagent Output Schema

```python
from pydantic import BaseModel

class MatchEntry(BaseModel):
    """Single match from search."""
    path: str
    relevance: str           # "high" | "medium" | "low"
    description: str         # One-line description
    snippet: str | None      # Content snippet

class MyAgentResult(BaseModel):
    """Structured output from my_agent."""
    target: str
    matches: list[MatchEntry]  # Top matches
    summary: str              # Brief answer
    
    # Domain-specific fields
    confidence: float         # Confidence score
```

### Subagent Events

```python
from soothe.core.event_catalog import register_event

class MyAgentStartedEvent(SootheEvent):
    """Event for subagent start."""
    type: str = "soothe.subagent.my_agent.started"
    target: str

class MyAgentIterationEvent(SootheEvent):
    """Event for each iteration."""
    type: str = "soothe.subagent.my_agent.iteration"
    iteration: int
    decision: str

class MyAgentCompletedEvent(SootheEvent):
    """Event for completion."""
    type: str = "soothe.subagent.my_agent.completed"
    duration_ms: int
    matches_count: int

# Register at module load
register_event(MyAgentStartedEvent, summary_template="my_agent started: {target}")
register_event(MyAgentIterationEvent, summary_template="Iteration {iteration}: {decision}")
register_event(MyAgentCompletedEvent, summary_template="Completed in {duration_ms}ms")
```

## Discovery Mechanisms

### Entry Points (Recommended)

**pyproject.toml**:
```toml
[project.entry-points."soothe.plugins"]
my_plugin = "my_package:MyPlugin"
```

**Priority**: 50 (high)

**Advantages**:
- Standard Python packaging mechanism
- Automatic discovery via importlib.metadata
- Version tracking via package metadata

### Config-Declared

**config.yml**:
```yaml
plugins:
  - name: my-custom-plugin
    enabled: true
    module: "my_package:MyPlugin"  # module_path:ClassName
    config:
      api_key: "${MY_API_KEY}"
      settings:
        timeout: 30
```

**Priority**: 30 (medium)

**Advantages**:
- No package installation required
- Runtime configuration
- Environment-specific plugins

### Filesystem

**Location**: `~/.soothe/plugins/<name>/plugin.py`

**Structure**:
```
~/.soothe/plugins/
  my-plugin/
    plugin.py           # Required: contains @plugin class
    __init__.py         # Optional: package initialization
    config.json         # Optional: plugin configuration
```

**Priority**: 10 (low)

**Advantages**:
- User-specific plugins
- No installation required
- Quick experimentation

### Discovery Priority

When multiple discovery mechanisms find the same plugin:

| Priority | Mechanism | Reason |
|----------|-----------|--------|
| 100 | built-in | Core capabilities always win |
| 50 | entry_point | Standard Python packaging |
| 30 | config-declared | Runtime configuration |
| 10 | filesystem | User-specific |

**Conflict resolution**: Higher priority plugin wins. Built-in plugins cannot be overridden.

## Configuration Integration

### Plugin Configuration

```yaml
plugins:
  - name: my-plugin
    enabled: true
    module: "my_package:MyPlugin"
    config:
      # Plugin-specific configuration
      api_key: "${MY_API_KEY}"
      settings:
        timeout: 30
        retries: 3
      features:
        enable_advanced: true
```

### Configuration Dependencies

```python
@plugin(
    name="my-plugin",
    config_requirements=[
        "providers.openai.api_key",     # Requires global config
        "plugins.my-plugin.api_key",    # Requires plugin config
    ]
)
class MyPlugin:
    async def on_load(self, context):
        # Access global config
        openai_key = context.soothe_config.providers.openai.api_key
        
        # Access plugin config
        my_key = context.config.get("api_key")
        
        # Validate dependencies
        if not openai_key:
            raise DependencyError("Missing providers.openai.api_key")
```

### Configuration Validation

```python
from pydantic import BaseModel

class MyPluginConfig(BaseModel):
    """Configuration schema for my-plugin."""
    api_key: str
    timeout: int = 30
    retries: int = 3
    enable_advanced: bool = False

@plugin(name="my-plugin", version="1.0.0")
class MyPlugin:
    async def on_load(self, context):
        # Validate configuration
        config = MyPluginConfig(**context.config)
        self.config = config
        
        # Use validated config
        self.timeout = config.timeout
```

## Dependency Management

### Library Dependencies

```python
@plugin(
    name="research",
    dependencies=[
        "arxiv>=2.0.0",           # PEP 440 version spec
        "langchain>=0.1.0",
        "sentence-transformers>=2.0",
    ]
)
class ResearchPlugin:
    async def on_load(self, context):
        # Check dependencies
        for dep in self.dependencies:
            if not check_dependency(dep):
                raise DependencyError(f"Missing dependency: {dep}")
```

**Behavior**: Missing dependencies prevent plugin loading. The orchestrator continues with other plugins.

### Optional Dependencies

```python
@plugin(name="optional-features", version="1.0.0")
class OptionalFeaturesPlugin:
    async def on_load(self, context):
        # Try to import optional dependency
        try:
            import advanced_features
            self.advanced = True
        except ImportError:
            context.logger.warning("Optional dependency missing, using basic mode")
            self.advanced = False
    
    @tool(name="advanced_op")
    def advanced_op(self, data: str) -> str:
        """Advanced operation (requires optional dependency)."""
        if not self.advanced:
            raise RuntimeError("Optional dependency missing")
        return advanced_features.process(data)
```

## Testing Extensions

### Unit Testing Tools

```python
import pytest
from my_package import MyPlugin

def test_greet_tool():
    """Test greet tool."""
    plugin = MyPlugin()
    tool = plugin.greet
    
    result = tool("Alice")
    assert result == "Hello, Alice!"

def test_analyze_tool():
    """Test analyze_data tool."""
    plugin = MyPlugin()
    tool = plugin.create_analyze_tool()
    
    result = tool._run("/data/test.csv", analysis_type="summary")
    assert "rows" in result
    assert "columns" in result
```

### Unit Testing Subagents

```python
import pytest
from my_package import create_my_agent
from langchain_core.messages import HumanMessage

@pytest.mark.asyncio
async def test_my_agent():
    """Test my_agent subagent."""
    # Create mock model
    model = MockChatModel()
    
    # Create agent
    agent = create_my_agent(model, {}, {"work_dir": "/tmp"})
    
    # Invoke
    result = await agent.invoke({
        "messages": [HumanMessage(content="Analyze test data")]
    })
    
    # Check output
    assert result["result"]["matches_count"] > 0
    assert result["result"]["summary"] != ""
```

### Integration Testing

```python
@pytest.mark.asyncio
async def test_plugin_loading():
    """Test plugin discovery and loading."""
    from soothe.plugin import PluginLifecycleManager
    from soothe.config.settings import SootheConfig
    
    # Create config
    config = SootheConfig()
    
    # Load plugins
    lifecycle = PluginLifecycleManager()
    await lifecycle.load_all(config)
    
    # Check my-plugin loaded
    registry = lifecycle.registry
    tools = registry.get_all_tools()
    
    assert "greet" in [t.name for t in tools]
    assert "analyze_data" in [t.name for t in tools]
```

## Package Structure

### Standard Package Layout

```
my_package/
├── __init__.py           # Public API + plugin registration
├── plugin.py             # @plugin class definition
├── tools/
│   ├── __init__.py
│   ├── greet.py          # Greet tool implementation
│   └── analyze.py        # Analyze tool implementation
├── subagents/
│   ├── __init__.py
│   ├── my_agent.py       # Subagent implementation
│   ├── schemas.py        # State/output schemas
│   ├── events.py         # Wire events
│   └── engine.py         # LangGraph engine
├── config.py             # Configuration schema
├── exceptions.py         # Plugin-specific exceptions
└── tests/
    ├── __init__.py
    ├── test_tools.py
    └ test_subagents.py
    └── test_integration.py
```

### Module Self-Containment

Follow IG-047 pattern for self-contained modules:

```
my_package/
├── __init__.py           # Plugin + public API
├── events.py             # Events + register_event() calls
├── implementation.py     # Factory functions
├── schemas.py            # State/output schemas
└── engine.py             # LangGraph engine (if complex)
```

### Event Registration Pattern

```python
# my_package/events.py
from soothe.core.event_catalog import register_event

class MyPluginLoadedEvent(SootheEvent):
    type: str = "soothe.plugin.my_plugin.loaded"

class MyToolEvent(SootheEvent):
    type: str = "soothe.tool.my_plugin.operation"

# Register at module load
register_event(MyPluginLoadedEvent)
register_event(MyToolEvent)

# Import in __init__.py for side-effect registration
from . import events  # noqa: F401
```

## Best Practices

### Tool Design

1. **Single-purpose**: One operation per tool
2. **Clear naming**: `{verb}_{noun}` pattern
3. **Type-safe**: Pydantic input schema
4. **Security-aware**: Workspace boundary enforcement
5. **Well-documented**: Detailed descriptions for LLM comprehension

### Subagent Design

1. **Messages in state**: Required for CompiledSubAgent contract
2. **Structured output**: Pydantic models, not raw dicts
3. **Single AIMessage**: Return one final AIMessage from last node
4. **Bounded cost**: Configurable iteration caps
5. **Domain events**: Register wire events for observability

### Plugin Design

1. **Graceful degradation**: Failures disable plugin, not orchestrator
2. **Dependency declaration**: Explicit dependencies in manifest
3. **Health checks**: Implement periodic health checks
4. **Resource cleanup**: Implement on_unload() for cleanup
5. **Configuration validation**: Validate config in on_load()

### Testing

1. **Unit tests**: Test factory, nodes, output schema
2. **Integration tests**: Test plugin loading and resolution
3. **Event tests**: Verify event emission
4. **Security tests**: Verify workspace boundaries
5. **Run verification**: `./scripts/verify_finally.sh`

### Documentation

1. **Plugin README**: Purpose, usage, configuration
2. **Tool descriptions**: Clear, detailed for LLM comprehension
3. **Subagent descriptions**: When to use, inputs/outputs
4. **Configuration guide**: YAML examples, environment variables
5. **API reference**: Type hints, docstrings, examples

## Troubleshooting

### Common Issues

1. **ImportError on plugin load**:
   - Check dependencies in manifest
   - Verify package installation
   - Check PYTHONPATH

2. **Plugin not discovered**:
   - Verify entry point registration
   - Check config.yml `plugins:` section
   - Verify filesystem plugin location

3. **Conflict with built-in plugin**:
   - Built-in plugins cannot be overridden
   - Use different name or trust level

4. **Configuration validation error**:
   - Check config_requirements
   - Verify plugin config schema
   - Check environment variable interpolation

5. **CompiledSubAgent contract violation**:
   - Ensure `messages: Annotated[list, add_messages]` in state
   - Return single AIMessage in final node
   - Use `graph.compile()` for runnable

### Debugging Tips

```bash
# Enable debug logs
SOOTHE_LOG_LEVEL=DEBUG soothe -p "use my-plugin"

# Check plugin loading
grep -i "loaded.*plugin" ~/.soothe/logs/soothe.log

# Verify discovery
grep -i "discovered.*plugin" ~/.soothe/logs/soothe.log

# Check dependencies
pip list | grep langchain

# Run verification
./scripts/verify_finally.sh
```

## Related RFCs

| RFC | Title | Key Sections |
|-----|-------|--------------|
| [RFC-600](../../specs/RFC-600-plugin-extension-system.md) | Plugin Extension System | Full specification |
| [RFC-601](../../specs/RFC-601-built-in-agents.md) | Built-in Plugin Agents | Architecture patterns |
| [RFC-101](../../specs/RFC-101-tool-interface.md) | Tool Interface | Single-purpose design |
| [RFC-047](../../impl/IG-047-module-self-containment.md) | Module Self-Containment | Package structure |

---

**Previous**: [MCP Integration](mcp.md) | **Back to**: [Capabilities Index](index.md)
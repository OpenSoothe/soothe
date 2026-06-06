# Core API Reference

The Soothe Core package (`soothe`) provides the framework-level APIs for configuration, protocol definitions, agent construction, and backend implementations.

**Package**: `soothe`  
**Import**: `from soothe import ...`  
**Python**: `>=3.11`

---

## Table of Contents

1. [Configuration System](#configuration-system)
2. [Protocol Definitions](#protocol-definitions)
3. [Agent Construction](#agent-construction)
4. [Agent Execution](#agent-execution)
5. [Backend Implementations](#backend-implementations)

---

## Configuration System

### SootheConfig

**Import**: `from soothe.config import SootheConfig`

Declarative configuration for Soothe agents with environment variable support.

#### Constructor

```python
SootheConfig(
    *,
    providers: dict[str, ModelProviderConfig] | None = None,
    models: ModelRouter | None = None,
    agent: AgentConfig | None = None,
    tools: ToolsConfig | None = None,
    protocols: ProtocolsConfig | None = None,
    persistence: PersistenceConfig | None = None,
    observability: ObservabilityConfig | None = None,
    security: SecurityConfig | None = None,
    subagents: dict[str, SubagentConfig] | None = None,
    mcp_servers: dict[str, MCPServerConfig] | None = None,
    autopilot: AutonomousConfig | None = None,
)
```

**Parameters**: All parameters are optional with sensible defaults.

**Environment Variables**: All configuration values support `${ENV_VAR}` syntax for environment variable interpolation. Environment variables can also be set with `SOOTHE_` prefix (e.g., `SOOTHE_PROVIDERS__OPENAI__API_KEY`).

**Example**:
```python
from soothe.config import SootheConfig, ModelProviderConfig, ModelRouter

# Minimal configuration with defaults
config = SootheConfig()

# Configuration with custom providers
config = SootheConfig(
    providers={
        "openai": ModelProviderConfig(
            type="openai",
            api_key="${OPENAI_API_KEY}",
            model_kwargs={"temperature": 0.7}
        ),
        "anthropic": ModelProviderConfig(
            type="anthropic",
            api_key="${ANTHROPIC_API_KEY}",
        )
    },
    models=ModelRouter(
        default="openai:gpt-4",
        planner="openai:gpt-4o",
        subagent="openai:gpt-3.5-turbo"
    )
)

# Load from YAML file
config = SootheConfig.from_yaml("config/config.yml")

# Load with environment overrides
config = SootheConfig.from_yaml(
    "config/config.yml",
    env_prefix="SOOTHE"
)
```

#### Methods

##### `resolve_model(role: str) -> str`

Resolve a model role to a provider:model string.

**Parameters**:
- `role`: Model role (`"default"`, `"planner"`, `"subagent"`, `"embedding"`)

**Returns**: Provider:model string (e.g., `"openai:gpt-4"`)

**Example**:
```python
config = SootheConfig()
model_str = config.resolve_model("planner")  # "openai:gpt-4o"
```

##### `create_chat_model(role: str) -> BaseChatModel`

Instantiate a langchain chat model for the given role.

**Parameters**:
- `role`: Model role (`"default"`, `"planner"`, `"subagent"`)

**Returns**: LangChain `BaseChatModel` instance

**Example**:
```python
from soothe.config import SootheConfig

config = SootheConfig()
model = config.create_chat_model("default")

# Use model
response = await model.ainvoke([{"role": "user", "content": "Hello"}])
```

##### `create_embedding_model() -> Embeddings`

Instantiate a langchain embedding model.

**Returns**: LangChain `Embeddings` instance

**Example**:
```python
config = SootheConfig()
embeddings = config.create_embedding_model()

# Generate embeddings
texts = ["Hello world", "How are you?"]
vectors = await embeddings.aembed_documents(texts)
```

##### `propagate_env() -> None`

Set environment variables for downstream libraries.

**Example**:
```python
config = SootheConfig()
config.propagate_env()  # Sets OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.
```

##### `from_yaml(path: str, env_prefix: str = "SOOTHE") -> SootheConfig`

Load configuration from YAML file with environment interpolation.

**Parameters**:
- `path`: Path to YAML configuration file
- `env_prefix`: Environment variable prefix for overrides

**Returns**: SootheConfig instance

**Example**:
```python
config = SootheConfig.from_yaml(
    "config/config.yml",
    env_prefix="SOOTHE"
)
```

---

### Configuration Models

#### ModelProviderConfig

**Import**: `from soothe.config import ModelProviderConfig`

Configuration for a model provider.

```python
class ModelProviderConfig(BaseModel):
    """Model provider configuration."""
    
    type: str
    """Provider type (e.g., 'openai', 'anthropic', 'google')."""
    
    api_key: str | None = None
    """API key (supports ${ENV_VAR} syntax)."""
    
    api_base: str | None = None
    """API base URL override."""
    
    model_kwargs: dict[str, Any] = Field(default_factory=dict)
    """Additional model parameters."""
```

---

#### ModelRouter

**Import**: `from soothe.config import ModelRouter`

Router for mapping roles to models.

```python
class ModelRouter(BaseModel):
    """Model role routing configuration."""
    
    default: str = "openai:gpt-4"
    """Default model for general use."""
    
    planner: str | None = None
    """Model for planning operations."""
    
    subagent: str | None = None
    """Model for subagent execution."""
    
    embedding: str | None = None
    """Model for embeddings."""
    
    classify: str | None = None
    """Model for intent classification."""
```

---

#### AgentConfig

**Import**: `from soothe.config import AgentConfig`

Configuration for agent behavior.

```python
class AgentConfig(BaseModel):
    """Agent configuration."""
    
    system_prompt: str | None = None
    """Custom system prompt."""
    
    max_iterations: int = DEFAULT_AGENT_LOOP_MAX_ITERATIONS
    """Maximum iterations per loop (RFC-201)."""
    
    execute_timeout: float = DEFAULT_EXECUTE_TIMEOUT
    """Timeout for tool execution."""
    
    parallel_tools: bool = True
    """Enable parallel tool execution."""
```

---

#### ProtocolsConfig

**Import**: `from soothe.config import ProtocolsConfig`

Configuration for protocol implementations.

```python
class ProtocolsConfig(BaseModel):
    """Protocol configuration."""
    
    memory: MemUConfig | None = None
    """Memory protocol config."""
    
    durability: DurabilityProtocolConfig | None = None
    """Durability protocol config."""
    
    planner: PlannerProtocolConfig | None = None
    """Planner protocol config."""
    
    policy: PolicyProtocolConfig | None = None
    """Policy protocol config."""
    
    vector_store: VectorStoreRouter | None = None
    """Vector store router config."""
```

---

## Protocol Definitions

### MemoryProtocol

**Import**: `from soothe.protocols import MemoryProtocol`

Protocol for agent memory operations (RFC-301).

#### Definition

```python
class MemoryProtocol(Protocol):
    """Memory protocol for remember/recall operations."""
    
    async def remember(
        self,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
        scope: str = "thread",
        thread_id: str | None = None,
    ) -> MemoryItem:
        """Store a memory.
        
        Args:
            content: Memory content to store
            metadata: Optional metadata dict
            scope: Memory scope ('thread', 'workspace', 'user', 'global')
            thread_id: Thread ID for thread-scoped memories
            
        Returns:
            Stored MemoryItem
        """
        ...
    
    async def recall(
        self,
        query: str,
        *,
        scope: str = "thread",
        thread_id: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """Recall memories by query.
        
        Args:
            query: Search query
            scope: Memory scope to search
            thread_id: Thread ID for thread-scoped search
            limit: Maximum number of results
            
        Returns:
            List of matching MemoryItems
        """
        ...
    
    async def clear(
        self,
        *,
        scope: str = "thread",
        thread_id: str | None = None,
    ) -> int:
        """Clear memories in scope.
        
        Args:
            scope: Memory scope to clear
            thread_id: Thread ID
            
        Returns:
            Number of memories cleared
        """
        ...
```

**Implementations**:
- `soothe.backends.memory.memu.MemUProtocol` (keyword-based)

**Example**:
```python
from soothe.protocols import MemoryProtocol

async def save_context(memory: MemoryProtocol, thread_id: str):
    # Remember important information
    await memory.remember(
        "User prefers concise responses",
        metadata={"type": "preference"},
        scope="thread",
        thread_id=thread_id,
    )
    
    # Recall relevant memories
    memories = await memory.recall(
        "user preferences",
        scope="thread",
        thread_id=thread_id,
        limit=5,
    )
    
    for mem in memories:
        print(f"Remembered: {mem.content}")
```

---

### DurabilityProtocol

**Import**: `from soothe.protocols import DurabilityProtocol`

Protocol for thread lifecycle management (RFC-304).

#### Definition

```python
class DurabilityProtocol(Protocol):
    """Durability protocol for thread persistence."""
    
    async def create_thread(
        self,
        *,
        workspace: str | None = None,
        metadata: ThreadMetadata | None = None,
    ) -> ThreadInfo:
        """Create a new thread.
        
        Args:
            workspace: Workspace path for the thread
            metadata: Optional thread metadata
            
        Returns:
            Created ThreadInfo
        """
        ...
    
    async def get_thread(self, thread_id: str) -> ThreadInfo | None:
        """Get thread by ID.
        
        Args:
            thread_id: Thread ID
            
        Returns:
            ThreadInfo or None if not found
        """
        ...
    
    async def list_threads(
        self,
        filter: ThreadFilter | None = None,
    ) -> list[ThreadInfo]:
        """List threads matching filter.
        
        Args:
            filter: Thread filter criteria
            
        Returns:
            List of matching ThreadInfo
        """
        ...
    
    async def suspend_thread(
        self,
        thread_id: str,
        *,
        reason: str | None = None,
    ) -> ThreadInfo:
        """Suspend a thread.
        
        Args:
            thread_id: Thread ID
            reason: Suspension reason
            
        Returns:
            Updated ThreadInfo
        """
        ...
    
    async def resume_thread(
        self,
        thread_id: str,
    ) -> ThreadInfo:
        """Resume a suspended thread.
        
        Args:
            thread_id: Thread ID
            
        Returns:
            Updated ThreadInfo
        """
        ...
    
    async def archive_thread(
        self,
        thread_id: str,
        *,
        reason: str | None = None,
    ) -> ThreadInfo:
        """Archive a thread.
        
        Args:
            thread_id: Thread ID
            reason: Archive reason
            
        Returns:
            Updated ThreadInfo
        """
        ...
```

**Implementations**:
- `soothe.backends.durability.postgres.PostgresDurability`
- `soothe.backends.durability.sqlite.SqliteDurability`

**Example**:
```python
from soothe.protocols import DurabilityProtocol, ThreadMetadata

async def manage_threads(durability: DurabilityProtocol):
    # Create thread
    thread = await durability.create_thread(
        workspace="/home/user/project",
        metadata=ThreadMetadata(
            tags=["research", "important"],
            notes="Quantum computing research thread",
        ),
    )
    
    print(f"Created thread: {thread.thread_id}")
    
    # List threads
    threads = await durability.list_threads()
    for t in threads:
        print(f"Thread {t.thread_id}: {t.status}")
    
    # Suspend thread
    suspended = await durability.suspend_thread(
        thread.thread_id,
        reason="User requested pause",
    )
    
    # Resume later
    resumed = await durability.resume_thread(thread.thread_id)
```

---

### PlannerProtocol

**Import**: `from soothe.protocols import PlannerProtocol`

Protocol for goal decomposition and planning (RFC-305).

#### Definition

```python
class PlannerProtocol(Protocol):
    """Planner protocol for goal decomposition."""
    
    async def plan(
        self,
        goal: str,
        context: PlanContext,
    ) -> Plan:
        """Decompose a goal into steps.
        
        Args:
            goal: Goal description
            context: Planning context
            
        Returns:
            Plan with steps
        """
        ...
    
    async def assess_goal(
        self,
        goal: str,
        context: PlanContext,
    ) -> GoalReport:
        """Assess goal status and completion.
        
        Args:
            goal: Goal description
            context: Planning context
            
        Returns:
            GoalReport with status
        """
        ...
```

**Implementations**:
- `soothe.backends.planner.llm_planner.LLMPlanner`

**Example**:
```python
from soothe.protocols import PlannerProtocol, PlanContext

async def plan_goal(planner: PlannerProtocol, workspace: str):
    # Create plan context
    context = PlanContext(
        workspace=workspace,
        available_tools=["file_read", "file_write", "execute"],
    )
    
    # Generate plan
    plan = await planner.plan(
        "Create a Python script to analyze CSV data",
        context,
    )
    
    print(f"Plan has {len(plan.steps)} steps:")
    for i, step in enumerate(plan.steps, 1):
        print(f"  {i}. {step.description}")
```

---

### PolicyProtocol

**Import**: `from soothe.protocols import PolicyProtocol`

Protocol for policy-based access control (RFC-306).

#### Definition

```python
class PolicyProtocol(Protocol):
    """Policy protocol for permission enforcement."""
    
    async def evaluate(
        self,
        request: ActionRequest,
        context: PolicyContext | None = None,
    ) -> PolicyDecision:
        """Evaluate action request against policy.
        
        Args:
            request: Action request to evaluate
            context: Optional policy context
            
        Returns:
            PolicyDecision with allowed/denied status
        """
        ...
    
    async def get_permissions(
        self,
        context: PolicyContext | None = None,
    ) -> PermissionSet:
        """Get permission set for context.
        
        Args:
            context: Optional policy context
            
        Returns:
            PermissionSet with granted permissions
        """
        ...
```

**Implementations**:
- `soothe.backends.policy.config_policy.ConfigDrivenPolicy`

**Example**:
```python
from soothe.protocols import PolicyProtocol, ActionRequest, PolicyContext

async def check_permission(policy: PolicyProtocol, workspace: str):
    # Create request
    request = ActionRequest(
        category="file",
        action="write",
        scope="workspace",
        resource="/home/user/project/config.yml",
        context=PolicyContext(workspace=workspace),
    )
    
    # Evaluate
    decision = await policy.evaluate(request)
    
    if decision.allowed:
        print(f"Allowed: {decision.reason}")
    else:
        print(f"Denied: {decision.reason}")
```

---

### VectorStoreProtocol

**Import**: `from soothe.protocols import VectorStoreProtocol`

Protocol for vector database operations (RFC-303).

See [SDK API: VectorStoreProtocol](sdk-api.md#vectorstoreprotocol) for full documentation.

---

### AsyncPersistStore

**Import**: `from soothe.protocols import AsyncPersistStore`

Protocol for key-value persistence (RFC-302).

See [SDK API: AsyncPersistStore](sdk-api.md#asyncpersiststore) for full documentation.

---

## Agent Construction

### create_soothe_agent()

**Import**: `from soothe.core.agent import create_soothe_agent`

Factory function for creating a CoreAgent with protocol properties.

#### Signature

```python
def create_soothe_agent(
    config: SootheConfig | None = None,
    *,
    memory: MemoryProtocol | None = None,
    durability: DurabilityProtocol | None = None,
    planner: PlannerProtocol | None = None,
    policy: PolicyProtocol | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CoreAgent:
```

**Parameters**:
- `config`: Soothe configuration
- `memory`: Memory protocol instance
- `durability`: Durability protocol instance
- `planner`: Planner protocol instance
- `policy`: Policy protocol instance
- `checkpointer`: LangGraph checkpointer for state persistence

**Returns**: CoreAgent instance

**Example**:
```python
from soothe.core.agent import create_soothe_agent
from soothe.config import SootheConfig
from soothe.backends.memory.memu import MemUProtocol
from soothe.backends.durability.sqlite import SqliteDurability

config = SootheConfig()

# Create protocols
memory = MemUProtocol(config)
durability = SqliteDurability(config)

# Create agent
agent = create_soothe_agent(
    config=config,
    memory=memory,
    durability=durability,
)

print(f"Agent created with protocols: {agent.protocols}")
```

---

### CoreAgent

**Import**: `from soothe.core.agent import CoreAgent`

Typed wrapper around LangGraph CompiledStateGraph with protocol properties.

#### Definition

```python
class CoreAgent:
    """CoreAgent - Layer 1 runtime (RFC-0023).
    
    Self-contained module wrapping CompiledStateGraph with typed protocol properties.
    Pure execution runtime - NO goal infrastructure.
    """
    
    def __init__(
        self,
        graph: CompiledStateGraph,
        *,
        memory: MemoryProtocol | None = None,
        durability: DurabilityProtocol | None = None,
        planner: PlannerProtocol | None = None,
        policy: PolicyProtocol | None = None,
    ):
        """Initialize CoreAgent with graph and protocols."""
        ...
    
    @property
    def graph(self) -> CompiledStateGraph:
        """Get the underlying LangGraph."""
        ...
    
    @property
    def memory(self) -> MemoryProtocol | None:
        """Get memory protocol."""
        ...
    
    @property
    def durability(self) -> DurabilityProtocol | None:
        """Get durability protocol."""
        ...
    
    @property
    def planner(self) -> PlannerProtocol | None:
        """Get planner protocol."""
        ...
    
    @property
    def policy(self) -> PolicyProtocol | None:
        """Get policy protocol."""
        ...
    
    async def astream(
        self,
        input: dict[str, Any],
        config: RunnableConfig | None = None,
        *,
        stream_mode: list[str] = ["messages", "updates", "custom"],
        subgraphs: bool = True,
    ) -> AsyncGenerator[tuple[str, Any], None]:
        """Stream agent execution.
        
        Args:
            input: Input dict with 'messages' key
            config: Runnable config with thread_id
            stream_mode: Stream modes to yield
            subgraphs: Include subgraph updates
            
        Yields:
            Tuples of (namespace, data)
        """
        ...
```

**Example**:
```python
from soothe.core.agent import CoreAgent

async def run_agent(agent: CoreAgent, query: str, thread_id: str):
    # Stream execution
    async for namespace, data in agent.astream(
        {"messages": [{"role": "user", "content": query}]},
        config={"configurable": {"thread_id": thread_id}},
    ):
        if namespace == "messages":
            # Handle message chunks
            print(data.get("content", ""), end="", flush=True)
        
        elif namespace == "custom":
            # Handle custom events
            event_type = data.get("type")
            print(f"\n[Event: {event_type}]")
```

---

### AgentBuilder

**Import**: `from soothe.core.agent import AgentBuilder`

Builder for constructing CoreAgent instances with custom middleware.

#### Definition

```python
class AgentBuilder:
    """Builder for CoreAgent construction."""
    
    def __init__(self, config: SootheConfig):
        """Initialize builder with config."""
        ...
    
    def with_memory(self, memory: MemoryProtocol) -> AgentBuilder:
        """Add memory protocol."""
        ...
    
    def with_durability(self, durability: DurabilityProtocol) -> AgentBuilder:
        """Add durability protocol."""
        ...
    
    def with_planner(self, planner: PlannerProtocol) -> AgentBuilder:
        """Add planner protocol."""
        ...
    
    def with_policy(self, policy: PolicyProtocol) -> AgentBuilder:
        """Add policy protocol."""
        ...
    
    def with_checkpointer(self, checkpointer: BaseCheckpointSaver) -> AgentBuilder:
        """Add checkpointer."""
        ...
    
    def with_middleware(self, middleware: Middleware) -> AgentBuilder:
        """Add custom middleware."""
        ...
    
    def build(self) -> CoreAgent:
        """Build the CoreAgent."""
        ...
```

**Example**:
```python
from soothe.core.agent import AgentBuilder
from soothe.config import SootheConfig

config = SootheConfig()

agent = AgentBuilder(config)
    .with_memory(MemUProtocol(config))
    .with_durability(SqliteDurability(config))
    .with_policy(ConfigDrivenPolicy(config))
    .build()
```

---

## Agent Execution

### SootheRunner

**Import**: `from soothe.core.runner import SootheRunner`

Protocol-orchestrated agent runner with pre/post processing.

#### Constructor

```python
SootheRunner(config: SootheConfig | None = None)
```

**Parameters**:
- `config`: Soothe configuration

**Example**:
```python
from soothe.core.runner import SootheRunner
from soothe.config import SootheConfig

config = SootheConfig()
runner = SootheRunner(config)
```

#### Methods

##### `astream()`

```python
async def astream(
    query: str,
    *,
    thread_id: str | None = None,
    workspace: str | None = None,
    verbosity: str = "normal",
    mode: str = "agentic",
    intent: str | None = None,
) -> AsyncGenerator[StreamChunk, None]:
```

Stream agent execution with protocol orchestration.

**Parameters**:
- `query`: User query
- `thread_id`: Thread ID for continuity
- `workspace`: Workspace path
- `verbosity`: Verbosity level
- `mode`: Execution mode
- `intent`: Intent hint

**Yields**: StreamChunk objects

**Example**:
```python
async def run_query(runner: SootheRunner, query: str):
    async for chunk in runner.astream(
        query,
        workspace="/home/user/project",
        verbosity="verbose",
    ):
        namespace = chunk.namespace
        mode = chunk.mode
        data = chunk.data
        
        if namespace == "assistant":
            print(data.get("content", ""), end="", flush=True)
        
        elif namespace == "soothe":
            event_type = data.get("type")
            print(f"\n[Protocol event: {event_type}]")
```

---

### StreamChunk

**Import**: `from soothe.core.runner._runner_shared import StreamChunk`

Stream chunk data structure.

```python
class StreamChunk(BaseModel):
    """Stream chunk from runner."""
    
    namespace: str
    """Chunk namespace ('assistant', 'tool', 'soothe', etc.)."""
    
    mode: str
    """Stream mode ('messages', 'updates', 'custom')."""
    
    data: dict[str, Any]
    """Chunk data payload."""
    
    thread_id: str | None = None
    """Thread ID."""
    
    loop_id: str | None = None
    """Loop ID."""
```

---

## Backend Implementations

### Memory Backends

#### MemUProtocol

**Import**: `from soothe.backends.memory.memu import MemUProtocol`

Keyword-based memory implementation (RFC-301).

```python
class MemUProtocol(MemoryProtocol):
    """Keyword-based memory protocol (MemU)."""
    
    def __init__(self, config: SootheConfig):
        """Initialize with config."""
        ...
    
    async def remember(
        self,
        content: str,
        *,
        metadata: dict | None = None,
        scope: str = "thread",
        thread_id: str | None = None,
    ) -> MemoryItem:
        """Store memory with keyword indexing."""
        ...
    
    async def recall(
        self,
        query: str,
        *,
        scope: str = "thread",
        thread_id: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """Recall memories by keyword search."""
        ...
```

**Configuration**:
```yaml
protocols:
  memory:
    type: memu
    max_items_per_scope: 100
    index_keywords: true
```

---

### Durability Backends

#### SqliteDurability

**Import**: `from soothe.backends.durability.sqlite import SqliteDurability`

SQLite-based durability implementation (RFC-304).

```python
class SqliteDurability(DurabilityProtocol):
    """SQLite durability protocol."""
    
    def __init__(self, config: SootheConfig, db_path: str | None = None):
        """Initialize with config and optional DB path."""
        ...
```

**Configuration**:
```yaml
protocols:
  durability:
    type: sqlite
    db_path: "${SOOTHE_HOME}/threads.db"
```

---

#### PostgresDurability

**Import**: `from soothe.backends.durability.postgres import PostgresDurability`

PostgreSQL-based durability implementation (RFC-304).

```python
class PostgresDurability(DurabilityProtocol):
    """PostgreSQL durability protocol."""
    
    def __init__(
        self,
        config: SootheConfig,
        *,
        connection_string: str | None = None,
    ):
        """Initialize with config and connection string."""
        ...
```

**Configuration**:
```yaml
protocols:
  durability:
    type: postgres
    connection_string: "${DATABASE_URL}"
    pool_size: 5
```

---

### Policy Backends

#### ConfigDrivenPolicy

**Import**: `from soothe.backends.policy.config_policy import ConfigDrivenPolicy`

Configuration-driven policy implementation (RFC-306).

```python
class ConfigDrivenPolicy(PolicyProtocol):
    """Configuration-driven policy protocol."""
    
    def __init__(self, config: SootheConfig):
        """Initialize with config."""
        ...
    
    async def evaluate(
        self,
        request: ActionRequest,
        context: PolicyContext | None = None,
    ) -> PolicyDecision:
        """Evaluate against config rules."""
        ...
```

**Configuration**:
```yaml
protocols:
  policy:
    type: config
    default_permissions:
      file:
        read: ["workspace"]
        write: ["workspace"]
      tool:
        execute: ["safe"]
    deny_by_default: true
```

---

### Planner Backends

#### LLMPlanner

**Import**: `from soothe.backends.planner.llm_planner import LLMPlanner`

LLM-based planner implementation (RFC-305).

```python
class LLMPlanner(PlannerProtocol):
    """LLM-based planner protocol."""
    
    def __init__(
        self,
        config: SootheConfig,
        *,
        model_role: str = "planner",
    ):
        """Initialize with config and model role."""
        ...
```

**Configuration**:
```yaml
protocols:
  planner:
    type: llm
    model_role: planner
    max_steps: 10
    assess_completion: true
```

---

### Vector Store Backends

#### PGVectorStore

**Import**: `from soothe.backends.vector_store.pgvector import PGVectorStore`

PostgreSQL pgvector implementation (RFC-303).

```python
class PGVectorStore(VectorStoreProtocol):
    """PostgreSQL pgvector store."""
    
    def __init__(
        self,
        config: SootheConfig,
        *,
        connection_string: str | None = None,
        table_name: str = "vectors",
    ):
        """Initialize with config."""
        ...
```

**Configuration**:
```yaml
vector_store:
  default: pgvector
  providers:
    pgvector:
      connection_string: "${DATABASE_URL}"
      table_name: embeddings
      dimensions: 1536
```

---

#### SqliteVecStore

**Import**: `from soothe.backends.vector_store.sqlite_vec import SqliteVecStore`

SQLite-vec implementation (RFC-303).

```python
class SqliteVecStore(VectorStoreProtocol):
    """SQLite-vec store."""
    
    def __init__(
        self,
        config: SootheConfig,
        *,
        db_path: str | None = None,
    ):
        """Initialize with config."""
        ...
```

**Configuration**:
```yaml
vector_store:
  default: sqlite_vec
  providers:
    sqlite_vec:
      db_path: "${SOOTHE_HOME}/vectors.db"
      dimensions: 1536
```

---

### Persistence Backends

#### SqlitePersistStore

**Import**: `from soothe.backends.persistence.sqlite import SqlitePersistStore`

SQLite-based key-value persistence (RFC-302).

```python
class SqlitePersistStore(AsyncPersistStore):
    """SQLite persistence store."""
    
    def __init__(self, db_path: str | None = None):
        """Initialize with optional DB path."""
        ...
```

---

#### PostgresPersistStore

**Import**: `from soothe.backends.persistence.postgres import PostgresPersistStore`

PostgreSQL-based key-value persistence (RFC-302).

```python
class PostgresPersistStore(AsyncPersistStore):
    """PostgreSQL persistence store."""
    
    def __init__(self, connection_string: str):
        """Initialize with connection string."""
        ...
```

---

## Resolver Functions

### resolve_durability()

**Import**: `from soothe.core.resolver import resolve_durability`

Resolve durability protocol from configuration.

```python
def resolve_durability(config: SootheConfig) -> DurabilityProtocol:
    """Resolve durability protocol from config.
    
    Args:
        config: Soothe configuration
        
    Returns:
        DurabilityProtocol instance
    """
    ...
```

---

### resolve_memory()

**Import**: `from soothe.core.resolver import resolve_memory`

Resolve memory protocol from configuration.

```python
def resolve_memory(config: SootheConfig) -> MemoryProtocol | None:
    """Resolve memory protocol from config."""
    ...
```

---

### resolve_planner()

**Import**: `from soothe.core.resolver import resolve_planner`

Resolve planner protocol from configuration.

```python
def resolve_planner(config: SootheConfig) -> PlannerProtocol | None:
    """Resolve planner protocol from config."""
    ...
```

---

### resolve_policy()

**Import**: `from soothe.core.resolver import resolve_policy`

Resolve policy protocol from configuration.

```python
def resolve_policy(config: SootheConfig) -> PolicyProtocol | None:
    """Resolve policy protocol from config."""
    ...
```

---

## See Also

- **[SDK API Reference](sdk-api.md)** - Client and plugin development API
- **[REST API Reference](rest-api.md)** - HTTP REST endpoints
- **[Protocols Layer](../protocols/README.md)** - Protocol specifications
- **[RFC-000 System Design](../../specs/RFC-000-system-conceptual-design.md)** - Overall architecture
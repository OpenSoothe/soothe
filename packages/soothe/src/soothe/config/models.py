"""Pydantic configuration models for Soothe."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from soothe.config.constants import (
    DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS,
    DEFAULT_MAX_TOOL_CALLS_PER_STEP,
    DEFAULT_STRANGE_LOOP_MAX_ITERATIONS,
    DEFAULT_TASK_TIMEOUT_SECONDS,
    DEFAULT_TOOL_OUTPUT_CHARS,
)


class UIConfig(BaseModel):
    """Configuration for UI preferences.

    Args:
        theme: Theme name for the TUI (e.g., 'langchain', 'langchain-light').
    """

    theme: str | None = None
    """Theme preference for the TUI."""


class UpdateConfig(BaseModel):
    """Configuration for CLI update and auto-update preferences.

    Args:
        check: Whether to run a PyPI version check on startup (CLI).
        auto_update: Whether auto-update is enabled when an update is available.
    """

    check: bool = True
    """Run version check on CLI startup."""

    auto_update: bool = True
    """Auto-update preference."""


class ModelProviderConfig(BaseModel):
    """Configuration for a single model provider.

    Args:
        name: Provider name (e.g., ``dashscope``, ``openrouter``, ``ollama``).
        api_base_url: Base URL for the provider's API endpoint.
        api_key: API key. Supports ``${ENV_VAR}`` syntax for env var references.
        provider_type: langchain provider type for ``init_chat_model`` /
            ``init_embeddings``. Supported values:
            - ``openai``: OpenAI API (official or compatible). Custom ``api_base_url``
              endpoints (oMLX, LMStudio, vLLM) auto-receive compatibility wrappers.
            - ``anthropic``: Anthropic Claude API
            - ``ollama``: Ollama local inference
        models: Model names available from this provider (for documentation).
    """

    name: str
    api_base_url: str | None = None
    api_key: str | None = None
    provider_type: str = "openai"
    models: list[str] = Field(default_factory=list)


class VectorStoreProviderConfig(BaseModel):
    """Configuration for a single vector store provider.

    Args:
        name: Provider identifier (used in router).
        provider_type: Backend type (pgvector, weaviate, in_memory).
        dsn: PostgreSQL DSN (pgvector). Supports ${ENV_VAR}.
        index_type: Index type (pgvector): hnsw, ivfflat, none.
        url: Weaviate server URL. Supports ${ENV_VAR}.
        api_key: Weaviate Cloud API key. Supports ${ENV_VAR}.
        grpc_port: Weaviate gRPC port.
    """

    name: str
    provider_type: Literal["pgvector", "weaviate", "in_memory", "sqlite_vec"] = "sqlite_vec"

    # pgvector options
    dsn: str | None = None
    index_type: Literal["hnsw", "ivfflat", "none"] = "hnsw"

    # Weaviate options
    url: str | None = None
    api_key: str | None = None
    grpc_port: int = 50051


ModelRole = Literal["default", "fast", "think", "image", "ocr", "embedding"]
"""Valid purpose-based model roles.

- ``default``: Main orchestrator reasoning (CoreAgent, failure analysis, system context).
- ``fast``: Cheap/fast operations (intent classification, routing, scenario classification,
  deep_research subagents, memory extraction, document/audio tooling).
- ``think``: Stronger reasoning (planning, consensus validation, backoff reasoning).
- ``image``: Vision-capable model (image analysis, daemon vision preflight).
- ``ocr``: Dedicated OCR / document text extraction model.
- ``embedding``: Embedding model (MemU vector search, semantic memory).
"""


class ModelRouter(BaseModel):
    """Maps :data:`ModelRole` values to ``provider_name:model_name`` strings.

    Unset roles fall back to ``default``.

    Args:
        default: Default model for orchestrator reasoning.
        think: Stronger model for planning and complex reasoning.
        fast: Cheap/fast model for classification and scoring.
        image: Vision-capable model for image understanding.
        ocr: OCR model for document text extraction.
        embedding: Embedding model for vector operations.
    """

    default: str = "openai:gpt-4o-mini"
    think: str | None = None
    fast: str | None = None
    image: str | None = None
    ocr: str | None = None
    embedding: str | None = None


class RouterProfile(BaseModel):
    """Named preset combining a :class:`ModelRouter` with matching ``embedding_dims``.

    Use with ``active_router_profile`` on :class:`~soothe.config.settings.SootheConfig`
    to switch between deployment targets (cloud vs local) without editing role mappings.

    Args:
        name: Unique profile identifier (e.g. ``production``, ``local-deploy``).
        router: Role → ``provider:model`` mapping for this preset.
        embedding_dims: Vector size for the profile's embedding model; must match output.
    """

    name: str
    router: ModelRouter
    embedding_dims: int = 1536


class VectorStoreRouter(BaseModel):
    """Maps component roles to "provider:collection" strings.

    Format: "provider_name:collection_name"
    Example: "pgvector_prod:soothe_context"

    Args:
        default: Default assignment for unspecified roles.
        context: Reserved for future use.
    """

    default: str | None = None


class SubagentConfig(BaseModel):
    """Configuration for a single subagent."""

    enabled: bool = True
    model: str | None = Field(
        default=None,
        description=(
            "Explicit ``provider:model`` override for subagents that support it "
            "(``planner``, ``deep_research``, ``academic_research``). "
            "Takes precedence over ``model_role``. ``browser_use`` uses ``model_role`` only."
        ),
    )
    model_role: ModelRole | None = Field(
        default=None,
        description=(
            "Router profile role for subagents that resolve via ModelRouter. "
            "``planner`` defaults to ``think`` when unset; ``browser_use`` defaults to ``default``."
        ),
    )
    transport: Literal["local", "acp", "a2a", "langgraph"] = "local"
    url: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    runtime_dir: str = ""
    """Runtime directory for subagent. Defaults to SOOTHE_HOME/agents/<name>/."""


class PluginConfig(BaseModel):
    """Configuration for a single plugin.

    Args:
        name: Plugin name.
        enabled: Whether this plugin is enabled.
        module: Python import path (e.g., "my_package:MyPlugin").
        config: Plugin-specific configuration dictionary.
    """

    name: str
    enabled: bool = True
    module: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class MCPTransport(StrEnum):
    """Transport types for MCP server connections."""

    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"
    WEBSOCKET = "websocket"


class MCPAuthHeaders(BaseModel):
    """Bearer tokens / API keys via headers. Supports ${ENV_VAR} interpolation."""

    headers: dict[str, str] = Field(default_factory=dict)


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server (RFC-412).

    Supports four transports via MCPTransport enum. Compatible with
    `langchain_mcp_adapters` connection types.

    Args:
        name: Required unique server identifier.
        transport: Transport type (stdio, sse, streamable_http, websocket).
        command: Subprocess command for stdio transport.
        args: Command arguments for stdio transport.
        env: Environment variables for stdio (supports ${ENV_VAR} interpolation).
        url: Server URL for remote transports.
        auth: Bearer/header auth configuration (v1; OAuth deferred).
        enabled: Per-server on/off toggle.
        defer: When True, tools are progressive (not in default tool array).
        tool_filter: Allowlist glob patterns for tool names (fnmatch).
        timeout_seconds: Connection timeout.
        request_timeout_seconds: Per-RPC timeout.
        tool_timeout_seconds: Tool-call hard cap.
    """

    name: str
    transport: MCPTransport = MCPTransport.STDIO
    # stdio
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    # remote
    url: str | None = None
    auth: MCPAuthHeaders | None = None
    # behavior
    enabled: bool = True
    defer: bool = True
    tool_filter: list[str] | None = None
    timeout_seconds: float = 30.0
    request_timeout_seconds: float = 60.0
    tool_timeout_seconds: float = 600.0

    @model_validator(mode="after")
    def _validate_transport_fields(self) -> MCPServerConfig:
        if self.transport == MCPTransport.STDIO:
            if not self.command:
                raise ValueError(f"Server '{self.name}': stdio requires 'command'")
            if self.url:
                raise ValueError(f"Server '{self.name}': stdio cannot have 'url'")
        else:
            if not self.url:
                raise ValueError(f"Server '{self.name}': {self.transport.value} requires 'url'")
            if self.command:
                raise ValueError(
                    f"Server '{self.name}': {self.transport.value} cannot have 'command'"
                )
        return self


class ComplexityThresholds(BaseModel):
    """Query complexity classification thresholds.

    Supports token-based thresholds for accurate LLM context management.

    Args:
        trivial_tokens: Maximum tokens for trivial queries (default: 10).
        simple_tokens: Maximum tokens for simple queries (default: 30).
        medium_tokens: Maximum tokens for medium queries (default: 60).
        use_tiktoken: Use tiktoken for token counting if available.
    """

    trivial_tokens: int = 10
    simple_tokens: int = 30
    medium_tokens: int = 60
    use_tiktoken: bool = False


class ToolConfig(BaseModel):
    """Base configuration for tool groups.

    Args:
        enabled: Whether this tool group is enabled.
    """

    enabled: bool = True


class ExecutionToolsConfig(ToolConfig):
    """Configuration for host execution tools (run_command, run_background, etc.).

    Args:
        enabled: Whether execution tools are bound to the agent.
        background_log_dir: Optional directory for ``run_background`` stdout/stderr logs.
            When null, logs go under ``<workspace>/.soothe/background`` or soothe home.
        background_log_retention_days: Prune ``bg-*.log`` older than this on spawn (0=off).
    """

    background_log_dir: str | None = Field(
        default=None,
        description=(
            "Directory for run_background stdout/stderr logs. "
            "Null uses workspace .soothe/background or soothe home fallback."
        ),
    )
    background_log_retention_days: int = Field(
        default=7,
        ge=0,
        description=(
            "Delete bg-*.log files older than this many days when run_background spawns "
            "(0 disables cleanup)."
        ),
    )


class WebSearchConfig(ToolConfig):
    """Configuration for web search tools.

    Args:
        enabled: Whether web search tools are enabled.
        default_engines: List of default search engines to use.
        max_results_per_engine: Maximum results per search engine.
        timeout: Request timeout in seconds.

    Note: The crawler runs in headless mode by default (BrowserConfig default in wizsearch backend).
    """

    default_engines: list[str] = Field(default_factory=lambda: ["tavily"])
    max_results_per_engine: int = 10
    timeout: int = 30


class DeepxivToolsConfig(ToolConfig):
    """DeepXiv academic paper search and reading tools.

    Args:
        enabled: Whether DeepXiv tools are enabled.
        token: API token, ``${DEEPXIV_API_KEY}`` / ``${DEEPXIV_TOKEN}``, or null for env lookup.
        timeout: Request timeout in seconds.
        max_retries: Maximum retry attempts per request.
    """

    token: str | None = None
    timeout: int = 60
    max_retries: int = 3


class HttpRequestsToolsConfig(ToolConfig):
    """LangChain Community ``RequestsToolkit`` (HTTP verbs).

    Requires ``allow_dangerous_requests=True`` to instantiate tools (upstream LangChain gate).

    Args:
        enabled: Whether to register HTTP request tools (default on).
        allow_dangerous_requests: Required for LangChain tool construction; default on with toolkit enabled.
        headers: Optional default headers for ``TextRequestsWrapper`` (e.g. Bearer tokens via ``${ENV}``).
        verify_ssl: Whether to verify TLS certificates (passed through to the requests wrapper).
    """

    enabled: bool = Field(
        default=True,
        description="Enable requests_get / requests_post / ... tools.",
    )
    allow_dangerous_requests: bool = Field(
        default=True,
        description="Must be True for LangChain to construct dangerous request tools.",
    )
    headers: dict[str, str] = Field(default_factory=dict)
    verify_ssl: bool = Field(default=True, description="TLS verification for outbound HTTP.")


class ToolsConfig(BaseModel):
    """Configuration for all tool groups.

    Each tool group can be enabled/disabled and have specific settings.
    Tool groups not listed here use defaults.

    Args:
        execution: Execution tools config (run_command, run_python, etc.).
        file_ops: File operation tools config.
        datetime: DateTime tool config.
        data: Data inspection tools config.
        wizsearch: Wizsearch multi-engine search tools config.
        http_requests: LangChain Requests toolkit (HTTP GET/POST/PATCH/PUT/DELETE).
        deepxiv: DeepXiv academic paper search tools (disabled by default).
    """

    execution: ExecutionToolsConfig = Field(default_factory=ExecutionToolsConfig)
    file_ops: ToolConfig = Field(default_factory=ToolConfig)
    datetime: ToolConfig = Field(default_factory=ToolConfig)
    data: ToolConfig = Field(default_factory=ToolConfig)
    wizsearch: WebSearchConfig = Field(default_factory=WebSearchConfig)
    http_requests: HttpRequestsToolsConfig = Field(default_factory=HttpRequestsToolsConfig)
    deepxiv: DeepxivToolsConfig = Field(default_factory=lambda: DeepxivToolsConfig(enabled=False))


class PersistenceConfig(BaseModel):
    """Unified persistence settings for protocol backends.

    RFC-612: Multi-database PostgreSQL architecture for lifecycle isolation,
    backup granularity, and pgvector extension requirements.

    Args:
        postgres_base_dsn: Base PostgreSQL DSN without database name (RFC-612).
            Example: "postgresql://user:pass@host:port"
            Used with postgres_databases to construct full DSNs for each component.
        postgres_databases: Named database mapping for each component (RFC-612).
            Maps component names to database names.
            Default: {"checkpoints": "soothe_checkpoints", "metadata": "soothe_metadata",
                      "vectors": "soothe_vectors", "memory": "soothe_memory"}
        soothe_postgres_dsn: Single-database PostgreSQL DSN when ``postgres_base_dsn`` is unset.
        default_backend: Default backend for new protocols (can be overridden).
    """

    # RFC-612: Multi-database architecture
    postgres_base_dsn: str | None = None
    """Base PostgreSQL DSN without database name (RFC-612)."""

    postgres_databases: dict[str, str] = {
        "checkpoints": "soothe_checkpoints",
        "metadata": "soothe_metadata",
        "vectors": "soothe_vectors",
        "memory": "soothe_memory",
    }
    """Named database mapping for each component (RFC-612).

    Note: StrangeLoop checkpoints use the same 'checkpoints' database as LangGraph
    with separate table names for schema isolation.
    """

    soothe_postgres_dsn: str = "postgresql://postgres:postgres@localhost:5432/soothe"
    """Single-database PostgreSQL DSN when ``postgres_base_dsn`` is not set."""

    default_backend: Literal["postgresql", "sqlite"] = "sqlite"

    postgres_pool_min_size: int = Field(
        default=4,
        ge=1,
        le=32,
        description=(
            "psycopg ``AsyncConnectionPool`` min_size for shared PostgreSQL pools. "
            "Keeps warm connections ready under thread_pool load."
        ),
    )
    checkpoints_pool_size: int = Field(
        default=32,
        ge=1,
        le=128,
        description=(
            "Shared PostgreSQL pool max_size for the checkpoints database per process. "
            "Used by LangGraph checkpointer, StrangeLoop persistence, ContextEngine, "
            "and anchor manager (single pool via PostgresPoolRegistry)."
        ),
    )
    metadata_pool_size: int = Field(
        default=16,
        ge=1,
        le=128,
        description=(
            "Shared metadata/durability PostgreSQL pool max_size per process. "
            "Singleton in thread_pool mode — not multiplied by runner count."
        ),
    )
    vectors_pool_size: int = Field(
        default=16,
        ge=1,
        le=128,
        description=("Shared pgvector PostgreSQL pool max_size per process (vectors database)."),
    )
    postgres_connection_budget_warn: int = Field(
        default=120,
        ge=16,
        le=512,
        description=(
            "Log a warning when checkpoints + metadata + vectors pool max sizes exceed this sum."
        ),
    )
    postgres_pool_max_idle_seconds: float = Field(
        default=120.0,
        ge=10.0,
        le=3600.0,
        description=(
            "Close idle PostgreSQL pool connections after this many seconds (psycopg max_idle). "
            "Lower values return connections to PgBouncer faster under bursty load."
        ),
    )
    postgres_pool_max_lifetime_seconds: float = Field(
        default=1800.0,
        ge=60.0,
        le=86400.0,
        description="Recycle pool connections after this many seconds (psycopg max_lifetime).",
    )
    postgres_pool_acquire_timeout_seconds: float = Field(
        default=45.0,
        ge=1.0,
        le=300.0,
        description="Seconds to wait for a free pool connection before PoolTimeout.",
    )

    # SQLite concurrency settings for multiple loop support
    sqlite_reader_pool_size: int = Field(
        default=8,
        ge=1,
        le=32,
        description=(
            "SQLite reader connection pool size for concurrent reads. "
            "Higher values support more parallel loops reading simultaneously. "
            "Writer operations are serialized via WAL mode."
        ),
    )

    # IG-500: Loop archival configuration
    archive_enabled: bool = Field(
        default=True,
        description="Enable loop checkpoint archival on /clear command.",
    )
    archive_retention_days: int = Field(
        default=90,
        ge=1,
        le=365,
        description="Days to retain archived loops before automatic cleanup.",
    )
    archive_max_count: int = Field(
        default=1000,
        ge=10,
        le=10000,
        description="Maximum number of archived loops to retain.",
    )


class MemUConfig(BaseModel):
    """MemU memory backend configuration.

    Args:
        enabled: Whether MemU memory backend is enabled. Default off pending redesign.
        persist_dir: Directory for memory files. Defaults to ~/.soothe/memory.
        llm_chat_role: Router role for chat model (extraction/categorization).
        llm_embed_role: Router role for embedding model (vector search).
        enable_embeddings: Enable embedding-based similarity search.
        enable_auto_categorization: Enable automatic categorization using LLM.
        enable_category_summaries: Enable category summary generation.
        memory_categories: Predefined memory categories.
    """

    enabled: bool = False
    persist_dir: str | None = None

    llm_chat_role: str = "fast"
    llm_embed_role: str = "embedding"

    enable_embeddings: bool = True
    enable_auto_categorization: bool = True
    enable_category_summaries: bool = True
    memory_categories: list[dict[str, str]] = [
        {"name": "personal_info", "description": "Personal information"},
        {"name": "preferences", "description": "User preferences and interests"},
        {"name": "knowledge", "description": "Facts and learned information"},
        {"name": "experiences", "description": "Past experiences and events"},
        {"name": "goals", "description": "Goals and objectives"},
    ]


class PlannerProtocolConfig(BaseModel):
    """Planner Protocol configuration.

    Args:
        model: Model role used for planning (resolved via ModelRouter).
            Use "think" for complex reasoning (default), "fast" for speed,
            or "default" as fallback.
        routing: Routing strategy for planner selection.
    """

    model: str = "think"

    # Config fields (IG-150 Phase 4)
    routing: Literal["auto", "always_direct", "always_planner"] = "auto"

    @field_validator("routing", mode="before")
    @classmethod
    def _normalize_legacy_routing(cls, value: Any) -> Any:
        if value == "always_claude":
            return "auto"
        return value


class PolicyProtocolConfig(BaseModel):
    """Policy Protocol configuration.

    Args:
        profile: Named profile from policy_profiles.yml.
    """

    profile: str = "standard"


class DurabilityProtocolConfig(BaseModel):
    """Durability Protocol configuration.

    Args:
        backend: Durability backend for thread lifecycle and metadata.
            Use 'default' to inherit from persistence.default_backend.
        checkpointer: LangGraph checkpoint backend (consistent naming).
            Use 'default' to inherit from persistence.default_backend.
        persist_dir: Directory for durability persistence.
        thread_inactivity_timeout_hours: Hours before an active thread with no updates is marked as suspended.
    """

    backend: Literal["postgresql", "sqlite", "default"] = "default"
    checkpointer: Literal["postgresql", "sqlite", "default"] = "default"
    persist_dir: str | None = None
    thread_inactivity_timeout_hours: int = Field(default=72, ge=1, le=720)


class ProtocolsConfig(BaseModel):
    """Protocol backends configuration.

    Args:
        memory: MemU memory backend configuration.
        planner: Planner Protocol configuration.
        policy: Policy Protocol configuration.
        durability: Durability Protocol configuration.
    """

    memory: MemUConfig = Field(default_factory=MemUConfig)
    planner: PlannerProtocolConfig = Field(default_factory=PlannerProtocolConfig)
    policy: PolicyProtocolConfig = Field(default_factory=PolicyProtocolConfig)
    durability: DurabilityProtocolConfig = Field(default_factory=DurabilityProtocolConfig)


class DreamingModeConfig(BaseModel):
    """Per-mode dreaming configuration (RFC-625 §13).

    Args:
        enabled: Whether this dreaming mode is enabled.
        max_episodes: Maximum episodes to distill (episodic mode only).
        min_success_rate: Minimum success rate for procedure extraction (procedure mode only).
    """

    enabled: bool = True
    max_episodes: int = Field(
        default=10, ge=1, le=100, description="Max episodes for episodic mode"
    )
    min_success_rate: float = Field(
        default=0.8, ge=0.0, le=1.0, description="Min success rate for procedure mode"
    )


class DreamingModesConfig(BaseModel):
    """Dreaming modes configuration container (RFC-625 §13).

    Args:
        episodic: Episodic memory distillation config.
        procedure: Procedure/skill extraction config.
        semantic: Project MEMORY.md update config.
        profile: User profile extraction config.
    """

    episodic: DreamingModeConfig = Field(
        default_factory=lambda: DreamingModeConfig(max_episodes=10)
    )
    procedure: DreamingModeConfig = Field(
        default_factory=lambda: DreamingModeConfig(min_success_rate=0.8)
    )
    semantic: DreamingModeConfig = Field(default_factory=DreamingModeConfig)
    profile: DreamingModeConfig = Field(default_factory=DreamingModeConfig)


class AutopilotConfig(BaseModel):
    """Autopilot scheduling and self-running configuration.

    Controls 24/7 self-running behavior for both goal-level and daemon-level.

    Args:
        enabled: Whether the AutopilotService scheduling loop is enabled.
            When False, the daemon constructs the service but does not start
            the scheduling loop. HTTP /autopilot/submit endpoints are available
            but goals won't be dispatched automatically. Default is False.
        max_iterations: Maximum iterations per autopilot thread (goal-level).
        max_retries: Maximum retries per goal on failure.
        max_total_goals: Maximum goals allowed (RFC-0007 §5.6).
        max_goal_depth: Maximum hierarchy depth (RFC-0007 §5.6).
        max_parallel_goals: Maximum goals running simultaneously.
        enable_dynamic_goals: Enable/disable dynamic creation (RFC-0007 §5.4).

        max_send_backs: Per-goal send-back budget for consensus validation (daemon-level).
        checkpoint_interval: Iterations between periodic checkpoints.
        dreaming_enabled: Enter dreaming mode when all goals complete.
        dreaming_consolidation_interval: Seconds between memory consolidation during dreaming.
        dreaming_health_check_interval: Seconds between health checks during dreaming.
        monitor_model_role: Router role for AutopilotMonitor LLM reasoners (backoff,
            DAG verification, dreaming distillation). Defaults to ``think``.
        consensus_model_role: Router role for RFC-204 goal consensus validation.
            Defaults to ``think``; daemon uses ``create_chat_model`` with automatic
            fallback to ``default`` on instantiation failure.
        webhooks: Webhook URLs by event type (e.g., on_goal_completed).
    """

    # === Autopilot scheduling (daemon-level) ===
    enabled: bool = Field(
        default=False,
        description=(
            "Enable the AutopilotService scheduling loop. When True, the daemon "
            "starts the scheduling loop on startup for 24/7 autonomous operation. "
            "When False (default), the service is constructed but the scheduling loop does not "
            "start automatically; goals must be dispatched manually."
        ),
    )
    max_iterations: int = 10
    max_retries: int = 2
    max_total_goals: int = Field(default=50, ge=1, le=500)
    max_goal_depth: int = Field(default=5, ge=1, le=10)
    max_parallel_goals: int = Field(default=3, ge=1, le=10)
    enable_dynamic_goals: bool = Field(default=True)
    # Concurrency cap for parallel goal execution. Enforced in two places:
    # 1. ConcurrencyController in the runner (runner-side semaphore)
    # 2. AutopilotService._execution_semaphore (service-side semaphore, RFC-222)
    # Independent of `max_loops`: loops can be reused for lineage, so the
    # number of in-flight executions can be lower than the loop pool size.

    # === Orchestration (from old autopilot) ===
    max_send_backs: int = Field(default=3, ge=1, le=10)
    checkpoint_interval: int = Field(default=10, ge=1, le=100)

    # === Dreaming ===
    dreaming_enabled: bool = True
    dreaming_consolidation_interval: int = Field(default=300, ge=10)
    dreaming_health_check_interval: int = Field(default=60, ge=5)

    monitor_model_role: ModelRole = Field(
        default="think",
        description=(
            "Router model role for AutopilotMonitor LLM reasoners "
            "(backoff, DAG verification, dreaming distillation)."
        ),
    )

    consensus_model_role: ModelRole = Field(
        default="think",
        description="Router model role for RFC-204 goal consensus validation.",
    )

    # RFC-625: AutopilotMonitor settings
    verify_interval: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Background verification loop interval (seconds)",
    )
    """Seconds between DAG health verification cycles."""

    dreaming_interval: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Time-based dreaming trigger interval (seconds)",
    )
    """Seconds between time-triggered dreaming mode entries."""

    dreaming_scope: Literal["loop", "workspace", "topic"] = Field(
        default="workspace",
        description="Cross-loop dreaming scope for memory distillation",
    )
    """Scope for dreaming: loop (current), workspace (all goals), topic (tagged goals)."""

    dreaming_modes: DreamingModesConfig = Field(
        default_factory=lambda: DreamingModesConfig(),
        description="Per-mode dreaming distillation config",
    )
    """Configuration for each dreaming distillation mode."""

    webhooks: dict[str, str | None] = Field(default_factory=dict)

    # === Loop pool (RFC-222) ===
    # Distinct from `max_parallel_goals`: `max_loops` caps worker capacity in
    # the StrangeLoop pool (loops can be reused for parent→child lineage), while
    # `max_parallel_goals` caps the number of goals actively scheduled at once.
    # They can differ — e.g. max_loops=8 for lineage reuse, max_parallel_goals=4.
    max_loops: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Maximum concurrent StrangeLoop workers in the autopilot pool",
    )
    loop_idle_timeout: int = Field(
        default=300,
        ge=10,
        description="Seconds an idle loop is kept before release",
    )
    poll_interval: int = Field(
        default=5,
        ge=1,
        description="AutopilotService scheduling-loop tick interval, seconds",
    )
    dreaming_poll_interval: int = Field(
        default=60,
        ge=5,
        description="Reduced polling cadence when in dreaming mode, seconds",
    )
    # RFC-222 H5: wall-clock budget per dispatched goal. None disables.
    goal_deadline_seconds: float | None = Field(
        default=1_209_600,
        description=(
            "Wall-clock budget per dispatched autopilot goal in seconds; "
            "the AutopilotService monitor cancels the worker on overrun (RFC-222 H5). "
            "None disables deadline enforcement (default 14d)."
        ),
    )
    # === Context projection (RFC-222 revised) ===
    # Bounds the GoalDispatchContextBundle that the daemon's ContextProjector
    # builds for each dispatched goal. Keeps cross-process IPC bounded and
    # caps memory of the GoalDispatchContextStore in durability.
    context_projection: ContextProjectionConfig = Field(
        default_factory=lambda: ContextProjectionConfig(),
        description="Bounds for GoalDispatchContextBundle merging",
    )

    # === Workspace reservation (RFC-222 revised) ===
    # Scheduling-time conflict gate. Refuses to dispatch two goals whose
    # workspace prefixes overlap. Supersedes per-path FileLockMiddleware for v1.
    workspace_reservation: WorkspaceReservationConfig = Field(
        default_factory=lambda: WorkspaceReservationConfig(),
        description="Workspace-prefix conflict gate config",
    )


class ContextProjectionConfig(BaseModel):
    """Bounds for GoalDispatchContextBundle merging (RFC-222 revised).

    The ContextProjector unions parents' GoalDispatchContextContributions,
    deduplicates, and truncates to these caps. Bundle stays small enough to
    ship over IPC cheaply (~100 KB).

    Args:
        max_findings: Max LLM-synthesized findings per bundle.
        max_files: Max file touchpoints per bundle.
        max_plan_steps: Max prior plan steps per bundle.
        context_retention_hours: After a root goal reaches a terminal state,
            its DAG's contributions become evictable from the store this many
            hours later. Default 168 (1 week). LRU-evict if quota exceeded.
    """

    max_findings: int = Field(default=20, ge=1, le=200)
    max_files: int = Field(default=50, ge=1, le=500)
    max_plan_steps: int = Field(default=30, ge=1, le=300)
    context_retention_hours: int = Field(default=168, ge=1)


class WorkspaceReservationConfig(BaseModel):
    """Workspace-prefix conflict gate config (RFC-222 revised).

    Args:
        enabled: When false, autopilot does not check for workspace overlap
            (allows multiple goals on overlapping paths). Default true.
        strict_overlap: When true, any prefix overlap counts as conflict
            (`/foo/bar` conflicts with `/foo/bar/baz`). Default true.
    """

    enabled: bool = True
    strict_overlap: bool = True


class LoopWorkingMemoryConfig(BaseModel):
    """Agentic loop working memory (RFC-203).

    In-memory scratchpad for the agentic loop; large entries spill under
    ``SOOTHE_HOME/data/threads/{thread_id}/working_memory/``.

    Args:
        enabled: Enable working memory for Layer 2 Reason prompts.
        max_inline_chars: Max size of the aggregated block injected into Reason.
        max_entry_chars_before_spill: Per-step output larger than this is written to disk.
    """

    enabled: bool = Field(default=True, description="Enable working memory")
    max_inline_chars: int = Field(
        default=4000,
        ge=400,
        le=100_000,
        description="Max chars for working-memory block in Reason prompt",
    )
    max_entry_chars_before_spill: int = Field(
        default=1500,
        ge=200,
        le=50_000,
        description="Spill step output to disk under SOOTHE_HOME/data/threads/{thread_id}/working_memory/ when longer than this",
    )


class GoalContextConfig(BaseModel):
    """Goal context injection configuration (RFC-217).

    Args:
        plan_limit: Number of previous goals to inject into Plan phase.
        execute_limit: Number of previous goals for Execute briefing on thread switch.
        enabled: Enable goal context injection.
    """

    plan_limit: int = Field(
        default=10, ge=1, le=50, description="Number of previous goals for Plan phase"
    )
    execute_limit: int = Field(
        default=10, ge=1, le=50, description="Number of previous goals for Execute briefing"
    )
    enabled: bool = Field(default=True, description="Enable goal context injection")


class ReportOutputConfig(BaseModel):
    """Configuration for report output behavior.

    Args:
        display_threshold: Max chars to display in terminal. Reports larger than this
            are saved to file with preview. Set to 0 to always save to file.
        preview_chars: Number of chars to show in terminal preview when report is saved to file.
        synthesis_max_chars: Max chars for LLM-synthesized reports. Set to 0 for unlimited.
    """

    display_threshold: int = Field(default=20000, ge=0, le=100000)
    preview_chars: int = Field(default=500, ge=0, le=5000)
    synthesis_max_chars: int = Field(default=0, ge=0, le=50000)


AgenticFinalResponseMode = Literal["auto", "always_synthesize"]

AgenticGoalCompletionMode = Literal["llm_only", "heuristic_only", "hybrid"]
ExecuteDeliverableAssessMode = Literal["auto", "always", "never"]


def normalize_agentic_final_response_mode(value: Any) -> Any:
    """Normalize ``final_response``; ``adaptive`` is a deprecated alias for ``auto``."""
    if value == "adaptive":
        return "auto"
    return value


class PlanPromptLedgerConfig(BaseModel):
    """Caps for RFC-214 ledger copies sent to plan-assess / plan-generate (IG-380).

    All limits use 0 to mean unlimited (preserve legacy behavior: full ledger, no copies).
    When any limit is positive, the plan phase uses deep-copied, trimmed messages only.
    """

    plan_ledger_max_messages: int = Field(
        default=40,
        ge=0,
        le=500,
        description="Max ledger messages tail for plan prompts (0 = unlimited)",
    )
    plan_ledger_max_total_chars: int = Field(
        default=0,
        ge=0,
        le=2_000_000,
        description="Max total extracted characters for plan ledger projection (0 = unlimited)",
    )
    plan_ledger_max_message_chars: int = Field(
        default=0,
        ge=0,
        le=500_000,
        description="Max extracted characters per ledger message in plan projection (0 = unlimited)",
    )


class PlanAssessPromptConfig(BaseModel):
    """Assess-specific prompt assembly knobs (mid-goal accuracy, IG-557)."""

    ledger_max_messages: int = Field(
        default=24,
        ge=0,
        le=500,
        description="Max execute AI ledger rows for assess projection (0 = unlimited)",
    )
    execute_ai_max_chars: int = Field(
        default=400,
        ge=0,
        le=50_000,
        description="Per execute AI row char cap in assess projection (0 = unlimited)",
    )
    keep_head_tail_execute_ai: bool = Field(
        default=True,
        description="Preserve first-wave + recent execute AI when tail-truncating",
    )
    omit_prior_progress_hint: bool = Field(
        default=True,
        description="Omit derived_progress_hint from assess PRIOR PROGRESS block",
    )
    include_plan_coverage: bool = Field(
        default=True,
        description="Inject deterministic PLAN COVERAGE block when a plan exists",
    )


class ExecutePromptLedgerConfig(BaseModel):
    """Caps for execute-step CoreAgent ledger projection (IG-542)."""

    cross_goal_completion_tail: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Prior-goal completion units at goal boundary (0 = disable Slice A)",
    )
    predecessor_max_messages: int = Field(
        default=96,
        ge=0,
        le=500,
        description="Max predecessor execute_step ledger rows for Slice B (0 = unlimited)",
    )
    execute_ai_ledger_max_tokens: int = Field(
        default=65536,
        ge=0,
        le=100_000,
        description=(
            "Max tokens for execute_step AI rows at ledger write time via langchain "
            "trim_messages (0 = store full text)"
        ),
    )


class LoopCheckpointConfig(BaseModel):
    """Loop checkpoint and recovery configuration (RFC-203).

    Args:
        progressive: Save checkpoint after each step/goal completion.
        auto_resume_on_start: Auto-resume incomplete threads on daemon start.
    """

    progressive: bool = True
    auto_resume_on_start: bool = False


class ToolCallLimitConfig(BaseModel):
    """Tool call limit configuration for ToolCallLimitMiddleware.

    Args:
        global_thread_limit: Maximum tool calls allowed per thread across all tools.
        global_run_limit: Maximum tool calls allowed per single agent invocation.
        tool_specific_limits: Tool-specific limit overrides (tool_name -> limits).
    """

    global_thread_limit: int = Field(
        default=200, ge=1, description="Global thread-level tool call limit"
    )
    global_run_limit: int = Field(default=200, ge=1, description="Global run-level tool call limit")
    tool_specific_limits: dict[str, dict[str, int]] = Field(
        default_factory=lambda: {
            "wizsearch_search": {"thread_limit": 5, "run_limit": 3},
            "wizsearch_crawl": {"thread_limit": 5, "run_limit": 3},
            "web_search": {"thread_limit": 5, "run_limit": 3},
            "fetch_url": {"thread_limit": 5, "run_limit": 3},
            "search": {"thread_limit": 5, "run_limit": 3},
        },
        description="Tool-specific limit overrides",
    )


class ToolRetryConfig(BaseModel):
    """Tool retry configuration for ToolRetryMiddleware.

    Args:
        max_retries: Maximum number of retry attempts after initial failure.
        backoff_factor: Exponential backoff multiplier.
        initial_delay: Initial delay in seconds before first retry.
    """

    max_retries: int = Field(default=3, ge=0, description="Max retry attempts")
    backoff_factor: float = Field(default=2.0, ge=0, description="Backoff multiplier")
    initial_delay: float = Field(default=1.0, ge=0, description="Initial delay in seconds")


class LLMRateLimitConfig(BaseModel):
    """LLM rate limiting, timeout, and retry configuration.

    Args:
        enabled: When false, LLM rate-limit middleware is not installed.
        rpm_limit: Soft cap on LLM HTTP requests per minute.
        concurrent_limit: Max concurrent in-flight LLM calls per thread.
        call_timeout_seconds: Per-LLM-call timeout.
        call_timeout_max_seconds: Upper bound for retry timeout escalation.
        retry_on_timeout: Enable retry with timeout escalation (IG-295).
        max_timeout_retries: Max retry attempts after timeout (IG-295).
        timeout_retry_multiplier: Timeout multiplier on retry (IG-295).
        retry_on_rate_limit: Enable retry on HTTP 429 rate limit errors (IG-499).
        max_rate_limit_retries: Max retry attempts after 429 error (IG-499).
        rate_limit_backoff_base: Exponential backoff base in seconds (IG-499).
        rate_limit_backoff_max: Maximum backoff wait in seconds (IG-499).
        respect_retry_after_header: Use retry-after header from API when present (IG-499).
        rate_limit_retry_timeout_seconds: Per-attempt timeout after a 429 (shorter than normal calls).
    """

    enabled: bool = Field(
        default=True,
        description="Enable LLM rate-limit middleware (RPM, concurrency, timeouts, retries)",
    )
    rpm_limit: int = Field(default=60, ge=1, le=10_000)
    concurrent_limit: int = Field(default=8, ge=1, le=500)
    # IG-504: Increased timeouts for robust step execution (600s default)
    call_timeout_seconds: int = Field(default=600, ge=30, le=3600)
    call_timeout_max_seconds: int = Field(default=900, ge=60, le=3600)
    retry_on_timeout: bool = True
    # IG-504: Increased retries for robust step execution (10 default)
    max_timeout_retries: int = Field(default=10, ge=0, le=15)
    timeout_retry_multiplier: float = Field(default=1.2, ge=1.0, le=5.0)

    # IG-499: HTTP 429 rate limit retry configuration
    retry_on_rate_limit: bool = Field(
        default=True,
        description="Retry LLM calls on HTTP 429 rate limit errors",
    )
    max_rate_limit_retries: int = Field(
        default=10,
        ge=0,
        le=20,
        description="Max retry attempts after 429 error",
    )
    rate_limit_backoff_base: float = Field(
        default=2.0,
        ge=1.0,
        le=10.0,
        description="Exponential backoff base (seconds)",
    )
    rate_limit_backoff_max: float = Field(
        default=60.0,
        ge=10.0,
        le=300.0,
        description="Maximum backoff wait (seconds)",
    )
    respect_retry_after_header: bool = Field(
        default=True,
        description="Use retry-after header from API when present",
    )
    rate_limit_retry_timeout_seconds: int = Field(
        default=120,
        ge=10,
        le=600,
        description="Per-attempt timeout for LLM calls after HTTP 429 (seconds)",
    )


class LoopCheckpointAsyncConfig(BaseModel):
    """Async checkpoint write configuration (RFC-803 Phase 6, IG-550).

    Checkpoint writes are always coalesced and non-blocking. PostgreSQL uses the
    process-scoped persistence writer; SQLite uses a per-manager flush worker.

    Args:
        flush_interval: Periodic forced write interval (seconds).
        close_timeout_seconds: Max seconds to wait for persist on manager close.
        durable_flush_timeout: Max seconds for goal-boundary durable flush.
    """

    flush_interval: float = Field(
        default=5.0,
        ge=1.0,
        le=60.0,
        description="Periodic forced write interval (seconds). Bounds crash data loss window.",
    )
    close_timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Bounded wait for checkpoint flush during StrangeLoopStateManager.close()",
    )
    durable_flush_timeout: float = Field(
        default=10.0,
        ge=1.0,
        le=120.0,
        description="Bounded wait for durable goal-boundary checkpoint flush",
    )


class LoopConcurrencyConfig(BaseModel):
    """Loop execution concurrency and scheduling controls.

    Args:
        max_parallel_goals: Maximum goals running simultaneously (autonomous mode).
        max_parallel_steps: Maximum plan steps running concurrently per execute batch.
        max_parallel_subagents: Maximum subagents running simultaneously.
        global_max_llm_calls: Cross-level circuit breaker for concurrent LLM calls.
        step_parallelism: Scheduling strategy for plan steps (sequential/dependency/max).
        max_parallel_tools: Maximum concurrent tool calls per thread.
    """

    max_parallel_goals: int = Field(
        default=4, ge=0, description="Maximum parallel goals (0=unlimited)"
    )
    max_parallel_steps: int = Field(
        default=4,
        ge=0,
        description="Max concurrent plan steps per batch; 0=unlimited; multiple batches per execute",
    )
    max_parallel_subagents: int = Field(
        default=4, ge=0, description="Maximum parallel subagents (0=unlimited)"
    )
    global_max_llm_calls: int = Field(
        default=10, ge=0, description="Global LLM call cap (0=unlimited)"
    )
    step_parallelism: Literal["sequential", "dependency", "max"] = Field(
        default="dependency", description="Step scheduling strategy"
    )
    max_parallel_tools: int = Field(
        default=50, ge=0, description="Maximum concurrent tool calls per thread (0=unlimited)"
    )
    checkpoint: LoopCheckpointAsyncConfig = Field(
        default_factory=LoopCheckpointAsyncConfig,
        description="Async checkpoint write configuration (RFC-803 Phase 6)",
    )


class LoopToolOutputConfig(BaseModel):
    """Tool result size caps for graph state and model context.

    Args:
        code_exec_max_output_chars: Max chars for shell/code tool stdout.
        tool_output_max_chars: Max chars for non-code_exec tool output.
    """

    code_exec_max_output_chars: int = Field(
        default=32_000,
        ge=1000,
        le=500_000,
        description="Max chars for shell/code tool stdout in graph state and model context",
    )
    tool_output_max_chars: int = Field(
        default=DEFAULT_TOOL_OUTPUT_CHARS,
        ge=500,
        le=500_000,
        description="Max chars for non-code_exec tool output in graph state and model context",
    )


class OutputStreamingConfig(BaseModel):
    """Configuration for output streaming behavior (RFC-614).

    Controls how goal_completion synthesis and other assistant outputs are
    delivered from daemon to client.

    Three delivery modes (IG-441):

    - ``batch``: Buffer the entire goal_completion synthesis. Emit a single
      ``AIMessageChunk`` with ``chunk_position="last"`` when the agent loop
      completes. Pure single-shot delivery; the client sees nothing during the
      synthesis. Intended for headless automation that does not need real-time
      progress.

    - ``adaptive`` (default, two-phase):

      1. *Streaming phase* — while cumulative goal_completion chars are below
         ``adaptive_threshold_chars`` every incoming chunk is forwarded
         individually, giving the lowest possible first-token latency.
      2. *Chunked-streaming phase* — once the threshold is crossed the
         coalescer buffers incoming text and flushes intermediate
         ``AIMessageChunk`` frames whenever the buffer reaches
         ``adaptive_block_chars`` characters or ``adaptive_block_interval_ms``
         milliseconds have elapsed since the last block flush, whichever
         happens first. The final block carries ``chunk_position="last"``.
         This keeps the user informed of progress on long outputs while
         reducing wire frame count vs. raw passthrough.

    - ``streaming``: Raw passthrough at the LLM's native generation speed.
      Every goal_completion chunk is forwarded immediately with no buffering.
      Highest wire-frame count and lowest latency — intended for local /
      low-latency clients that want token-level fidelity.

    If ``file_output_threshold_chars`` is set (> 0) goal_completion reverts to
    pure-batch buffering regardless of mode so the final file_output decision
    sees the complete text.

    Args:
        mode: Delivery mode (``batch`` | ``adaptive`` | ``streaming``).
        streaming_interval_ms: Daemon WebSocket batching interval (milliseconds).
        tui_flush_interval_ms: TUI rendering flush interval (milliseconds).
        adaptive_threshold_chars: Cumulative chars at which adaptive switches
            from streaming phase to chunked-streaming phase.
        adaptive_block_chars: Chars per block in chunked-streaming phase.
        adaptive_block_interval_ms: Max ms between block flushes in
            chunked-streaming phase.
        file_output_threshold_chars: Threshold to write goal_completion to file (0 = never).
        file_output_preview_chars: Preview chars in TUI when output saved to file.
        file_output_dir: Directory for output files (default: current workspace root/.soothe/output).
        message_coalesce_enabled: When true, coalesce plain assistant text chunks per namespace.
        tool_batch_enabled: Debounce tool invocation wire into ``tool_call_updates_batch``.
        tool_batch_interval_ms: Max wait before flushing a debounced tool batch (milliseconds).
        suppress_redundant_stream_tool_updates: Drop ``soothe.stream.tool_call.update`` when batched.
        skip_redundant_tool_message_wire: Drop empty tool-result wire frames (off by default).
    """

    mode: Literal["batch", "adaptive", "streaming"] = Field(
        default="adaptive",
        description=(
            "Delivery mode. batch: buffer entire goal_completion and emit one frame "
            "at strange_loop.completed. adaptive: stream until adaptive_threshold_chars, "
            "then emit block-sized AIMessageChunk frames. streaming: raw passthrough "
            "at the LLM's native generation rate (no buffering)."
        ),
    )
    streaming_interval_ms: int = Field(
        default=100,
        ge=50,
        le=1000,
        description=(
            "Daemon WebSocket batching interval (milliseconds). "
            "IG-534 Phase 3: 100ms default for TUI clients (faster perceived response); "
            "use 300 for headless consumers to reduce network overhead."
        ),
    )
    tui_flush_interval_ms: int = Field(
        default=200,
        ge=50,
        le=1000,
        description="TUI markdown stream flush interval (milliseconds)",
    )
    adaptive_threshold_chars: int = Field(
        default=500,
        ge=100,
        le=10000,
        description=(
            "Cumulative chars at which adaptive switches from per-chunk streaming "
            "to chunked-streaming (block-buffered) goal_completion delivery"
        ),
    )
    adaptive_block_chars: int = Field(
        default=500,
        ge=128,
        le=16384,
        description=(
            "Chars per intermediate block in adaptive chunked-streaming phase "
            "(IG-441). Higher values reduce frame count; lower values smooth UX. "
            "Default 500 aligns with adaptive_threshold_chars so the first block "
            "after cutover is the same size as one streamed chunk window."
        ),
    )
    adaptive_block_interval_ms: int = Field(
        default=250,
        ge=50,
        le=2000,
        description=(
            "Max milliseconds between intermediate block flushes in adaptive "
            "chunked-streaming phase (IG-441). Time-based fallback so slow streams "
            "still show progress before adaptive_block_chars accumulates."
        ),
    )
    file_output_threshold_chars: int = Field(
        default=0,
        ge=0,
        le=100000,
        description="Chars threshold to write goal_completion to file",
    )
    file_output_preview_chars: int = Field(
        default=500,
        ge=0,
        le=5000,
        description="Preview chars when output saved to file",
    )
    file_output_dir: str | None = Field(
        default=None,
        description="Directory for output files (default: current workspace root/.soothe/output)",
    )
    message_coalesce_enabled: bool = Field(
        default=True,
        description="Coalesce plain assistant AIMessageChunk text before WebSocket broadcast",
    )
    tool_batch_enabled: bool = Field(
        default=True,
        description="Debounce tool invocation metadata into tool_call_updates_batch events",
    )
    tool_batch_interval_ms: int = Field(
        default=500,
        ge=50,
        le=1000,
        description="Debounce window for tool_call_updates_batch (milliseconds)",
    )
    suppress_redundant_stream_tool_updates: bool = Field(
        default=True,
        description="Suppress soothe.stream.tool_call.update when covered by a pending batch",
    )
    skip_redundant_tool_message_wire: bool = Field(
        default=True,
        description="Suppress empty ToolMessage wire frames (keep false for full wire debug)",
    )


class ContextEngineConfig(BaseModel):
    """Context Engine integration for StrangeLoop (RFC-624 Phase 4).

    ContextEngine is always active and replaces PlanManager, LoopWorkingMemory,
    and GoalContextManager as the internal state backend. The existing prompt
    pipeline, executor, and LangGraph topology remain unchanged.

    The persistence backend follows ``persistence.default_backend`` — no
    separate ``persistence_backend`` knob is needed. When the global backend
    is ``postgresql``, CE uses PgsqlContextPersistence with the same DSN.
    When ``sqlite``, CE uses SqliteContextPersistence (default). If
    ``postgresql`` is configured but ``asyncpg`` is not installed, CE
    falls back to SQLite automatically.

    Args:
        projection_max_goals: Max goals in projection output.
        projection_max_steps_per_goal: Max steps per goal in projection output.
        projection_max_ledger_chars: Max total chars for ledger summary in projection.
        projection_max_ledger_messages: Max messages in projection ledger output.
        projection_max_lineage_chars: Max chars for lineage context in projection.
        projection_max_project_instructions_chars: Max chars for project instructions.
    """

    projection_max_goals: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Max goals in CE projection output",
    )
    projection_max_steps_per_goal: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Max steps per goal in CE projection output",
    )
    projection_max_ledger_chars: int = Field(
        default=4000,
        ge=0,
        le=500_000,
        description="Max total chars for ledger summary in CE projection (0 = unlimited)",
    )
    projection_max_ledger_messages: int = Field(
        default=20,
        ge=0,
        le=500,
        description="Max messages in CE projection ledger output (0 = unlimited)",
    )
    projection_max_lineage_chars: int = Field(
        default=2000,
        ge=0,
        le=100_000,
        description="Max chars for lineage context in CE projection (0 = unlimited)",
    )
    projection_max_project_instructions_chars: int = Field(
        default=8000,
        ge=0,
        le=500_000,
        description="Max chars for project instructions in CE projection (0 = unlimited)",
    )

    def to_projection_config(self) -> Any:
        """Build a ``ProjectionConfig`` from these settings."""
        from soothe.foundation.context.projection import ProjectionConfig

        return ProjectionConfig(
            max_goals=self.projection_max_goals,
            max_steps_per_goal=self.projection_max_steps_per_goal,
            max_ledger_chars=self.projection_max_ledger_chars,
            max_ledger_messages=self.projection_max_ledger_messages,
            max_lineage_chars=self.projection_max_lineage_chars,
            max_project_instructions_chars=self.projection_max_project_instructions_chars,
        )


class ToolTimeoutConfig(BaseModel):
    """Tool timeout middleware configuration (IG-511).

    Wraps tool invocations with configurable timeouts, preventing indefinite hangs
    from tools that lack internal timeout guards.

    Args:
        enabled: Enable tool timeout middleware.
        default_seconds: Default timeout for tools without specific override.
        per_tool: Per-tool timeout overrides (tool_name -> seconds).
        skip_tools_with_internal_timeout: Skip wrapping tools with robust internal timeout.
    """

    enabled: bool = Field(
        default=True,
        description="Enable tool timeout middleware",
    )
    default_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=3600.0,
        description="Default timeout for tools without specific override (seconds)",
    )
    per_tool: dict[str, float] = Field(
        default_factory=lambda: {
            "grep": 30.0,
            "read_file": 30.0,
            "browser_use": 1800.0,  # Browser automation (30 minutes)
            "task": float(DEFAULT_TASK_TIMEOUT_SECONDS),
        },
        description="Per-tool timeout overrides (tool_name -> seconds)",
    )
    skip_tools_with_internal_timeout: bool = Field(
        default=True,
        description="Skip wrapping tools that already have robust internal timeout (glob)",
    )


class CompletionRulesConfig(BaseModel):
    """Declarative completion heuristics (RFC-624)."""

    dag_dependency_threshold: int = Field(default=3, ge=1)
    low_success_rate_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    simple_ledger_direct_max_steps: int = Field(default=1, ge=1)
    ledger_direct_max_tool_calls: int = Field(
        default=50,
        ge=0,
        description=(
            "Max tool calls in the last execute wave for ledger_direct eligibility "
            "(0 = no cap; structural gate only)"
        ),
    )


class ScenarioRulesConfig(BaseModel):
    """Declarative scenario classifier fast-path rules."""

    skip_llm_when_single_step: bool = True
    skip_llm_when_all_failed: bool = True
    high_step_count_threshold: int = Field(default=4, ge=2)
    low_evidence_volume_threshold: int = Field(default=2000, ge=0)


class PlanSafetyRulesConfig(BaseModel):
    """Declarative plan step safety rules."""

    banned_step_patterns: list[str] = Field(
        default_factory=lambda: [
            r"^(wrap up|conclude|terminate|stop|halt|cease|end process|close|exit|quit|"
            r"finish up|complete process|final step|last step|the end)$"
        ]
    )
    simple_evidence_min_chars: int = Field(default=200, ge=0)
    no_tool_evidence_retry_limit: int = Field(
        default=2,
        ge=1,
        description=(
            "Consecutive successful verify-only steps with zero tool calls before "
            "plan_assess stops replanning and routes to goal completion."
        ),
    )


class StrangeLoopRulesConfig(BaseModel):
    """Declarative StrangeLoop routing and completion rules."""

    completion: CompletionRulesConfig = Field(default_factory=CompletionRulesConfig)
    scenario: ScenarioRulesConfig = Field(default_factory=ScenarioRulesConfig)
    plan_safety: PlanSafetyRulesConfig = Field(default_factory=PlanSafetyRulesConfig)


class StrangeLoopConfig(BaseModel):
    """Configuration for agent loop execution mode (RFC-201, IG-407: unified config).

    Unified configuration consolidating agentic behavior fields and loop execution controls.
    Behavior fields are placed directly under loop.* for easy access.

    Args:
        enabled: Enable agent loop mode.
        max_iterations: Maximum agent loop iterations.
        max_subagent_tasks_per_wave: Cap ``task`` tool completions per Act wave (0 = unlimited).
        max_tool_calls_per_step: Cap tool results consumed per execute step from the Act stream (0 = unlimited).
        execute_action_retry_max: Extra Execute passes when the step deliverable gate fails (0 = disabled).
        execute_min_answer_chars: Minimum final assistant text length for deliverable satisfaction.
        execute_deliverable_assess: Fast LLM assess mode when structural deliverable checks are inconclusive.
        strange_loop_output_contract_enabled: Append anti-repetition instructions to sequential Act prompts.
        final_response: Whether to always synthesize a final CoreAgent report, reuse last Execute
            assistant text when structurally eligible, or use auto heuristics (IG-199, IG-631).
        working_memory: Working memory / spill configuration (RFC-203).
        goal_context: Goal context injection for Plan/Execute phases (RFC-217).
        report_output: Goal report display and synthesis limits.
        output_streaming: Enable streaming mode for all AI outputs (true=stream, false=batch).
        goal_completion_mode: How planner completion (`require_goal_completion`) combines with
            execution heuristics when the goal is assessed as done (IG-298).
        plan_prompt_ledger: Ledger projection caps for Plan-phase LLM prompts (IG-380).
        checkpoint: Progressive checkpoint persistence and startup resume (RFC-203).
        concurrency: Parallelism caps and step scheduling strategy.
        tool_output: Tool result size caps for graph state and model context.
        tool_call_limit: Tool call count limits per thread/run.
        tool_retry: Tool failure retry policy.
        llm_rate_limit: LLM rate limiting, per-call timeouts, and retry escalation.
        tool_timeout: Tool timeout middleware configuration (IG-511).
        plan_assess_model_role: Router role for plan-assess LLM calls (default ``think``).
        plan_generate_model_role: Router role for plan-generate LLM calls (default ``think``).
        goal_synthesis_model_role: Router role for goal-completion synthesis streaming (default ``default``).

    Note: Performance optimizations (intent/routing classification pipeline, optimize_system_prompts,
    parallel_pre_stream) are always enabled by design and not configurable.
    """

    enabled: bool = Field(
        default=True,
        description="Enable agent loop mode",
    )

    max_iterations: int = Field(
        default=DEFAULT_STRANGE_LOOP_MAX_ITERATIONS,
        description="Maximum agent loop iterations",
        ge=1,
        le=500,
    )

    max_plan_steps_per_wave: int = Field(
        default=10,
        description="Maximum plan-generate steps emitted per planning wave (all iterations)",
        ge=1,
        le=50,
    )

    max_subagent_tasks_per_wave: int = Field(
        default=4,
        description="Max completed subagent ``task`` tool results per Execute wave (0 = no limit)",
        ge=0,
        le=20,
    )

    max_tool_calls_per_step: int = Field(
        default=DEFAULT_MAX_TOOL_CALLS_PER_STEP,
        description=(
            "Max tool results consumed per execute step from the CoreAgent Act stream "
            "(0 = unlimited)"
        ),
        ge=0,
        le=10_000,
    )

    execute_action_retry_max: int = Field(
        default=1,
        description=(
            "Extra Execute passes when the step deliverable gate reports incomplete (0 = disabled)"
        ),
        ge=0,
        le=5,
    )

    execute_min_answer_chars: int = Field(
        default=20,
        description="Minimum final assistant text length for execute deliverable satisfaction",
        ge=0,
        le=500,
    )

    execute_deliverable_assess: ExecuteDeliverableAssessMode = Field(
        default="auto",
        description=(
            "Fast LLM step-deliverable assess: auto when structural checks are inconclusive, "
            "always on incomplete, never (structural only)"
        ),
    )

    step_completion_report_max_words: int = Field(
        default=50,
        description="Target word limit for execute-step completion cognition summaries (LLM prompt only)",
        ge=5,
        le=100,
    )

    strange_loop_output_contract_enabled: bool = Field(
        default=True,
        description="Instruct CoreAgent not to paste full tool outputs again during StrangeLoop Execute phase",
    )

    final_response: AgenticFinalResponseMode = Field(
        default="auto",
        description=(
            "On goal completion: auto uses structural heuristics to choose ledger direct vs "
            "a final CoreAgent report; always_synthesize always runs the report. "
            "Legacy alias: adaptive → auto."
        ),
    )

    @field_validator("final_response", mode="before")
    @classmethod
    def _normalize_final_response(cls, value: Any) -> Any:
        return normalize_agentic_final_response_mode(value)

    goal_completion_mode: AgenticGoalCompletionMode = Field(
        default="llm_only",
        description=(
            "When the planner marks the goal done: llm_only trusts StatusAssessment only; "
            "heuristic_only uses execution heuristics only; hybrid uses LLM first with heuristic fallback"
        ),
    )

    step_brief_hydration_enabled: bool = Field(
        default=True,
        description=(
            "When true, dependent steps with vague full_description are hydrated "
            "between execute waves using predecessor evidence (LLM when available)."
        ),
    )

    prior_conversation_limit: int = Field(
        default=10,
        description=(
            "Maximum prior messages to format for Plan prompts when Execute phase uses isolated threads"
        ),
        ge=1,
        le=50,
    )

    context_window_limit: int = Field(
        default=200_000,
        description="Model context window token limit for percentage calculation",
        ge=10_000,
        le=1_000_000,
    )

    # RFC-224: Automatic context window management
    context_overflow_threshold_pct: float = Field(
        default=0.80,
        ge=0.5,
        le=0.95,
        description=(
            "Percentage of context_window_limit at which automatic "
            "in-place compaction is triggered."
        ),
    )
    """RFC-224: Trigger threshold for context compaction (0.80 = 80%)."""

    context_compaction_target_pct: float = Field(
        default=0.60,
        ge=0.30,
        le=0.70,
        description=(
            "Target context percentage after compaction. "
            "Provides buffer for subsequent execute waves."
        ),
    )
    """RFC-224: Compaction target (0.60 = 60% of context_limit)."""

    step_context_check_enabled: bool = Field(
        default=False,
        description=(
            "Check context on step threads (loop_id__step_{step_id}). "
            "Usually unnecessary; step threads are short-lived."
        ),
    )
    """RFC-224: Enable step thread context checking."""

    output_streaming: OutputStreamingConfig = Field(
        default_factory=OutputStreamingConfig,
        description="Output streaming configuration",
    )

    loop_orchestrator_evidence_validate: bool = Field(
        default=True,
        description=(
            "Enable plan evidence validation node in the loop orchestrator (RFC-220; currently a no-op)."
        ),
    )

    working_memory: LoopWorkingMemoryConfig = Field(
        default_factory=LoopWorkingMemoryConfig,
        description="Loop working memory",
    )

    goal_context: GoalContextConfig = Field(
        default_factory=GoalContextConfig,
        description="Goal context injection for Plan/Execute phases",
    )

    report_output: ReportOutputConfig = Field(
        default_factory=ReportOutputConfig,
        description="Terminal/file behavior for synthesized goal reports",
    )

    plan_prompt_ledger: PlanPromptLedgerConfig = Field(
        default_factory=PlanPromptLedgerConfig,
        description="Plan-phase ledger projection limits; zeros = full ledger passthrough",
    )

    plan_assess_prompt: PlanAssessPromptConfig = Field(
        default_factory=PlanAssessPromptConfig,
        description="Assess-only projection and envelope settings (IG-557)",
    )

    execute_prompt_ledger: ExecutePromptLedgerConfig = Field(
        default_factory=ExecutePromptLedgerConfig,
        description="Execute-step CoreAgent ledger projection (IG-542)",
    )

    checkpoint: LoopCheckpointConfig = Field(
        default_factory=LoopCheckpointConfig,
        description="Progressive checkpoint persistence and startup resume",
    )

    concurrency: LoopConcurrencyConfig = Field(
        default_factory=LoopConcurrencyConfig,
        description="Parallelism caps and step scheduling strategy",
    )

    tool_output: LoopToolOutputConfig = Field(
        default_factory=LoopToolOutputConfig,
        description="Tool result size caps for graph state and model context",
    )

    tool_call_limit: ToolCallLimitConfig = Field(
        default_factory=ToolCallLimitConfig,
        description="Tool call count limits per thread/run",
    )

    tool_retry: ToolRetryConfig = Field(
        default_factory=ToolRetryConfig,
        description="Tool failure retry policy",
    )

    llm_rate_limit: LLMRateLimitConfig = Field(
        default_factory=LLMRateLimitConfig,
        description="LLM rate limiting, per-call timeouts, and retry escalation",
    )

    tool_timeout: ToolTimeoutConfig = Field(
        default_factory=ToolTimeoutConfig,
        description="Tool timeout middleware configuration",
    )
    """Wrap tool calls with configurable timeout to prevent indefinite hangs."""

    plan_assess_model_role: ModelRole = Field(
        default="think",
        description=(
            "Router model role for plan-assess structured LLM calls "
            "(status assessment and continuation routing)."
        ),
    )

    plan_gap_analysis_enabled: bool = Field(
        default=True,
        description="Run plan-gap-analysis before plan-assess on mid-goal paths (IG-557).",
    )

    plan_generate_model_role: ModelRole = Field(
        default="think",
        description="Router model role for plan-generate structured LLM calls.",
    )

    goal_synthesis_model_role: ModelRole = Field(
        default="default",
        description="Router model role for goal-completion synthesis streaming.",
    )

    context_engine: ContextEngineConfig = Field(
        default_factory=lambda: ContextEngineConfig(),
        description="Context Engine integration",
    )

    rules: StrangeLoopRulesConfig = Field(
        default_factory=StrangeLoopRulesConfig,
        description="Declarative completion, scenario, and plan-safety thresholds",
    )


class FileLoggingConfig(BaseModel):
    """File logging configuration.

    Args:
        level: Logging level for file output.
        path: Log file path (empty = SOOTHE_HOME/logs/soothe.log).
        max_bytes: Maximum file size before rotation.
        backup_count: Number of rotating backup files.
    """

    level: str = "INFO"
    path: str | None = None
    max_bytes: int = 5242880  # 5 MB
    backup_count: int = 3


class ConsoleLoggingConfig(BaseModel):
    """Console logging configuration.

    Args:
        enabled: Whether to output logs to console (disabled by default for TUI compatibility).
        level: Logging level for console output.
        stream: Output stream ('stdout' or 'stderr').
        format: Log format string for console output.
    """

    enabled: bool = False
    level: str = "WARNING"
    stream: Literal["stdout", "stderr"] = "stderr"
    format: str = "%(level_short)s %(name)s %(message)s"


class GlobalHistoryConfig(BaseModel):
    """Global cross-thread input history configuration.

    Args:
        enabled: Enable global input history storage and TUI navigation.
        max_size: Maximum entries in global history file.
        dedup_window: Number of recent entries to check for duplicate prevention.
        retention_days: Days to retain global history before cleanup.
    """

    enabled: bool = True
    max_size: int = 5000
    dedup_window: int = 10
    retention_days: int = 90


class ThreadLoggingConfig(BaseModel):
    """Thread logging configuration.

    Args:
        enabled: Whether thread logging is enabled.
        dir: Directory for thread logs.
        retention_days: Days to retain thread logs.
        max_size_mb: Maximum total size for thread logs.
    """

    enabled: bool = True
    dir: str | None = None
    retention_days: int = 30
    max_size_mb: int = 100


class LangfuseIntegrationConfig(BaseModel):
    """Langfuse OpenTelemetry + LangChain callback integration (install ``langfuse`` package).

    When ``enabled`` is true, Soothe attaches Langfuse's LangChain ``CallbackHandler`` to
    LangGraph ``astream`` calls. Credentials may be set here (values support ``${ENV}``) or
    omitted to use standard Langfuse environment variables (``LANGFUSE_PUBLIC_KEY``,
    ``LANGFUSE_SECRET_KEY``, ``LANGFUSE_HOST``).

    Args:
        enabled: Turn Langfuse tracing on for graph runs.
        public_key: Langfuse public key (optional if set via environment).
        secret_key: Langfuse secret key (optional if set via environment).
        host: Langfuse API base URL (e.g. ``https://cloud.langfuse.com`` or self-hosted origin).
        environment: Langfuse ``environment`` tag (e.g. ``production``, ``dev``).
        release: Langfuse ``release`` tag for deployment correlation.
        sample_rate: Client-side sampling rate ``0.0``–``1.0`` (passed to the Langfuse client).
        trace_name: Optional LangGraph ``run_name`` for the root run when set.
        tags: Optional list of trace tags (Langfuse ``langfuse_tags`` metadata) for
            dashboard filters and cost breakdowns.
        user_id: Optional Langfuse ``user_id`` (``langfuse_user_id`` metadata); supports
            ``${ENV_VAR}``. Prefer non-PII stable tenant ids in production.
    """

    enabled: bool = Field(
        default=False,
        description="Enable Langfuse LangChain callbacks on CoreAgent LangGraph streams",
    )
    public_key: str | None = Field(
        default=None,
        description="Langfuse public key; supports ${ENV_VAR}",
    )
    secret_key: str | None = Field(
        default=None,
        description="Langfuse secret key; supports ${ENV_VAR}",
    )
    host: str | None = Field(
        default=None,
        description="Langfuse API host / base URL; supports ${ENV_VAR}",
    )
    environment: str | None = Field(
        default=None,
        description="Langfuse environment label (e.g. production, staging)",
    )
    release: str | None = Field(
        default=None,
        description="Langfuse release / version label",
    )
    sample_rate: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional Langfuse client sample rate between 0.0 and 1.0",
    )
    trace_name: str | None = Field(
        default=None,
        description="If set, used as RunnableConfig run_name for traced graph invocations",
    )
    tags: list[str] | None = Field(
        default=None,
        description="Optional Langfuse trace tags (langfuse_tags in Runnable metadata)",
    )
    user_id: str | None = Field(
        default=None,
        description="Optional Langfuse user id (langfuse_user_id); supports ${ENV_VAR}",
    )


class ObservabilityConfig(BaseModel):
    """Unified observability configuration for debugging and monitoring.

    Consolidates logging, verbosity, thread logs, and Langfuse tracing into one section.

    Args:
        log_file_level: Logging level for file output (DEBUG, INFO, WARNING, ERROR).
        log_file_path: Log file path (empty = SOOTHE_HOME/logs/soothe.log).
        log_file_max_bytes: Maximum file size before rotation (default: 5 MB).
        log_file_backup_count: Number of rotating backup files.
        verbosity: Verbosity level for TUI/headless activity display (quiet, normal, detailed, debug).
        thread_logging_enabled: Whether thread-specific logging is enabled.
        thread_logging_retention_days: Days to retain thread logs before cleanup.
        thread_logging_max_size_mb: Maximum total size for thread logs directory.
        profile_model_calls: Log per-model-call middleware timing for latency debugging.
        langfuse: Langfuse OpenTelemetry / LangChain callback settings.
    """

    # File logging settings
    log_file_level: str = Field(
        default="INFO",
        description="Logging level for file output (DEBUG, INFO, WARNING, ERROR)",
    )

    log_file_path: str | None = Field(
        default=None,
        description="Log file path (empty = SOOTHE_HOME/logs/soothe.log)",
    )

    log_file_max_bytes: int = Field(
        default=5242880,  # 5 MB
        description="Maximum file size before rotation",
    )

    log_file_backup_count: int = Field(
        default=3,
        description="Number of rotating backup files",
    )

    console: ConsoleLoggingConfig = Field(
        default_factory=ConsoleLoggingConfig,
        description="Console logging for daemon foreground and optional stderr/stdout logging",
    )

    global_history: GlobalHistoryConfig = Field(
        default_factory=GlobalHistoryConfig,
        description="Global cross-thread input history (TUI navigation)",
    )

    # Verbosity settings
    verbosity: Literal["quiet", "normal", "debug"] = Field(
        default="normal",
        description="Verbosity level for TUI/headless activity display",
    )

    # Thread logging settings
    thread_logging_enabled: bool = Field(
        default=True,
        description="Whether thread-specific logging is enabled",
    )

    thread_logging_retention_days: int = Field(
        default=30,
        ge=1,
        description="Days to retain thread logs before cleanup",
    )

    thread_logging_max_size_mb: int = Field(
        default=100,
        ge=1,
        description="Maximum total size for thread logs directory",
    )

    profile_model_calls: bool = Field(
        default=False,
        description=(
            "Enable model-call profiler middleware (logs pre/post-handler timing per LLM call)"
        ),
    )

    langfuse: LangfuseIntegrationConfig = Field(
        default_factory=LangfuseIntegrationConfig,
        description="Langfuse tracing (install `langfuse` package)",
    )


class FailureIntentConfig(BaseModel):
    """Failure intent classification for reflection (IG-433)."""

    enabled: bool = True
    llm_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Deprecated: LLM is primary when enabled; keyword path is offline fallback only.",
    )


class StructuredPlanConfig(BaseModel):
    """Structured LLM plan parsing (IG-433)."""

    enabled: bool = True


class OptimizationConfig(BaseModel):
    """Keyword/heuristic optimization settings (IG-433)."""

    failure_intent: FailureIntentConfig = Field(default_factory=FailureIntentConfig)
    structured_plan: StructuredPlanConfig = Field(default_factory=StructuredPlanConfig)


class FilesystemMiddlewareConfig(BaseModel):
    """Configuration for SootheFilesystemMiddleware.

    Path sandboxing (``virtual_mode``) is derived from
    ``security.allow_paths_outside_workspace`` — set that flag, not a field here.

    Args:
        backup_enabled: Enable automatic backup before file deletion.
        backup_dir: Directory for backup files.
        workspace_root: Root directory for workspace operations.
        max_file_size_mb: Maximum file size for operations.
        tool_token_limit_before_evict: Token limit for large result eviction.
    """

    backup_enabled: bool = True
    """Enable automatic file backup on delete operations."""

    backup_dir: str | None = None
    """Directory for backup files. Defaults to .backups in each file's parent."""

    workspace_root: str | None = None
    """Root directory for workspace operations."""

    max_file_size_mb: int = 10
    """Maximum file size for operations (MB) - passed to FilesystemBackend."""

    tool_token_limit_before_evict: int | None = 20000
    """Token limit before evicting large tool results (inherited from FilesystemMiddleware)."""


class WorkspaceMountConfig(BaseModel):
    """Path mapping for containerized daemon deployments (RFC-621).

    When the daemon runs inside a Docker container, client workspace paths
    must be translated to container paths. Set both host_root and
    container_root to enable; leave both unset for local runs.
    """

    host_root: str | None = None
    """Parent directory on the host machine that is volume-mounted into the container."""

    container_root: str | None = None
    """Mount point inside the container where host_root is mounted."""

    @model_validator(mode="after")
    def _validate_pair(self) -> WorkspaceMountConfig:
        """Both fields must be set together, or neither."""
        has_host = bool(self.host_root and self.host_root.strip())
        has_container = bool(self.container_root and self.container_root.strip())
        if has_host != has_container:
            msg = (
                "workspace_mount.host_root and workspace_mount.container_root "
                "must both be set or both be unset"
            )
            raise ValueError(msg)
        return self

    @property
    def is_configured(self) -> bool:
        """True when both host_root and container_root are non-empty."""
        return bool(self.host_root) and bool(self.container_root)


class CodeInterpreterConfig(BaseModel):
    """Configuration for CodeInterpreterMiddleware (IG-423).

    Enables embedded QuickJS interpreter for programmatic tool calling and
    stateful code execution within the agent loop.

    Reference: https://www.langchain.com/blog/give-your-agents-an-interpreter

    Args:
        enabled: Enable the code interpreter middleware (default: False, opt-in).
        ptc_allowlist: List of tool names exposed to interpreter via tools.* namespace.
            Empty list means no tools are exposed (security-first default).
        memory_limit_mb: Interpreter memory limit in MB.
        timeout_seconds: Per-eval timeout in seconds.
        max_ptc_calls: Maximum programmatic tool calls per eval.
        max_result_size: Maximum result size in characters.
        console_capture: Capture console.log output.
        snapshot_between_turns: Preserve interpreter state between conversation turns.
    """

    enabled: bool = False
    """Enable the code interpreter middleware. Disabled by default (opt-in)."""

    ptc_allowlist: list[str] = Field(default_factory=list)
    """Tools exposed to interpreter via tools.* namespace. Empty = security-first default."""

    memory_limit_mb: int = 128
    """Interpreter memory limit in MB."""

    timeout_seconds: int = 30
    """Per-eval timeout in seconds."""

    max_ptc_calls: int = 50
    """Maximum programmatic tool calls per eval."""

    max_result_size: int = Field(
        default=DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS,
        ge=1000,
        le=1_000_000,
    )
    """Maximum result size in characters (code_exec / interpreter)."""

    console_capture: bool = True
    """Capture console.log output from interpreter."""

    snapshot_between_turns: bool = False
    """Preserve interpreter state between conversation turns."""


class ProgressiveSkillsConfig(BaseModel):
    """RFC-105 / IG-543: Tunables for progressive skill listing and discovery."""

    budget_pct: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of StrangeLoopConfig.context_window_limit (chars, not tokens) "
            "available for the <AVAILABLE_SKILLS> listing per turn."
        ),
    )
    max_listing_chars_per_entry: int = Field(
        default=250,
        ge=0,
        description="Hard per-entry character cap for description in the listing.",
    )
    min_listing_chars_per_entry: int = Field(
        default=20,
        ge=0,
        description="Below this, non-builtin entries fall back to names-only mode.",
    )
    core_skills: list[str] | None = Field(
        default=None,
        description=(
            "Skill names always listed on turn 0 (core tier). When null, built-in defaults apply."
        ),
    )
    search_skills_enabled: bool = Field(
        default=True,
        description="Register search_skills and invoke_skill tools for deferred discovery.",
    )
    semantic_search_enabled: bool = Field(
        default=True,
        description="Use Skillify vector search to supplement substring search_skills results.",
    )
    semantic_search_min_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum vector similarity score for semantic search_skills matches.",
    )
    intent_prefetch_enabled: bool = Field(
        default=True,
        description=(
            "Auto-discover deferred skills and auto-invoke matched core/builtin skills "
            "from the first user message on a cold thread."
        ),
    )
    core_intent_auto_invoke_enabled: bool = Field(
        default=True,
        description=(
            "When intent prefetch matches a core-tier skill, load its SKILL.md body "
            "into SKILL_CONTEXT on turn 0 (no invoke_skill tool call required)."
        ),
    )
    intent_prefetch_top_k: int = Field(
        default=2,
        ge=0,
        le=10,
        description="Maximum skills to match per tier on turn-0 intent prefetch.",
    )
    intent_prefetch_min_query_chars: int = Field(
        default=4,
        ge=0,
        description="Skip intent prefetch when the user message is shorter than this.",
    )
    max_concurrent_vector_searches: int = Field(
        default=4,
        ge=1,
        le=32,
        description=("Process-wide limit on concurrent pgvector searches from Skillify retrieval."),
    )


class ProgressiveToolsConfig(BaseModel):
    """Progressive builtin-tool loading: core tier bound, deferred tools listed."""

    enabled: bool = Field(
        default=True,
        description="When true, bind only core tools on cold start; list deferred tools in prompt",
    )
    budget_pct: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        description="Fraction of context_window_limit for <AVAILABLE_TOOLS> listing per turn",
    )
    max_listing_chars_per_entry: int = Field(
        default=120,
        ge=0,
        description="Hard per-entry character cap for deferred tool descriptions",
    )
    min_listing_chars_per_entry: int = Field(
        default=20,
        ge=0,
        description="Below this, deferred entries fall back to names-only mode",
    )
    core_tools: list[str] | None = Field(
        default=None,
        description="Explicit core-tier tool names; null uses built-in defaults",
    )
    search_tools_enabled: bool = Field(
        default=True,
        description="Include search_tools in core tier for discovering deferred tools",
    )


class ProgressiveMCPConfig(BaseModel):
    """RFC-412: Tunables for progressive MCP tool listing budget."""

    budget_pct: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of StrangeLoopConfig.context_window_limit (chars, not tokens) "
            "available for the <AVAILABLE_MCP_TOOLS> listing per turn."
        ),
    )
    max_listing_chars_per_entry: int = Field(
        default=250,
        ge=0,
        description="Hard per-entry character cap for tool description in the listing.",
    )
    min_listing_chars_per_entry: int = Field(
        default=20,
        ge=0,
        description="Below this, non-essential entries fall back to names-only mode.",
    )


class RoleRoutingConfig(BaseModel):
    """Per-hop model role routing for CoreAgent ReAct loop (IG-545).

    Args:
        enabled: When true, ``RoleRoutingMiddleware`` swaps the chat model per hop.
        orchestration_model_role: Router role for tool-orchestration hops.
        generation_model_role: Router role for synthesis and post-cap hops.
        max_orchestration_hops: Use orchestration role for the first N model hops
            after each user message (hop 0 = first call in the segment).
    """

    enabled: bool = Field(
        default=False,
        description="Enable per-hop orchestration vs generation model routing in CoreAgent",
    )
    orchestration_model_role: ModelRole = Field(
        default="fast",
        description="Router role for tool-orchestration model hops",
    )
    generation_model_role: ModelRole = Field(
        default="default",
        description="Router role for content synthesis and hops after the orchestration cap",
    )
    max_orchestration_hops: int = Field(
        default=1,
        ge=1,
        le=50,
        description="Orchestration role applies while hop index since last user message is below this",
    )


class AgentRuntimeConfig(BaseModel):
    """CoreAgent startup and materialization tuning (IG-506).

    Args:
        lazy_core_agent: Defer ``create_deep_agent`` until first Layer-1 execution.
        general_purpose_subagent: Expose deepagents ``general-purpose`` delegate via ``task``.
        role_routing: Per-hop orchestration vs generation model roles (IG-545).
    """

    lazy_core_agent: bool = Field(
        default=True,
        description="Defer CoreAgent graph compile until first execute access",
    )
    general_purpose_subagent: bool = Field(
        default=False,
        description=(
            "When true, register deepagents general-purpose subagent on the task tool. "
            "When false (default), general-purpose is hidden and blocked."
        ),
    )
    role_routing: RoleRoutingConfig = Field(
        default_factory=RoleRoutingConfig,
        description="Per-hop model role routing for CoreAgent ReAct loop",
    )


def _default_agent_system_prompt_body() -> str:
    """Lazy import to avoid pulling prompt fragments at config import time."""
    from soothe.foundation.sloop.prompts.system_templates import default_agent_system_prompt_body

    return default_agent_system_prompt_body()


class AgentConfig(BaseModel):
    """Unified agent configuration with progressive disclosure.

    Consolidates all agent-related settings into one section:
    - Basic: name, system_prompt (user identity)
    - Behavior: goal_completion_mode, final_response (response mode)
    - Autopilot: self-driving configuration
    - Loop: StrangeLoop internal tuning
    - Protocols: Planner, Policy, Durability backend selection

    Args:
        name: Display name for the assistant identity in system prompts.
        system_prompt: System prompt override. None generates default using name.
        goal_completion_mode: How planner completion combines with execution heuristics.
        final_response: Whether to always synthesize final report or use auto heuristics.
        autopilot: Autopilot scheduling and self-running configuration.
        loop: StrangeLoop configuration (IG-407: unified agentic+execution).
        protocols: Protocol backends configuration (planner, policy, durability).
    """

    @model_validator(mode="before")
    @classmethod
    def _strip_legacy_claude_core_agent(cls, data: Any) -> Any:
        """Drop removed Claude Code core-agent YAML keys."""
        if not isinstance(data, dict):
            return data
        for key in (
            "core_agent_backend",
            "claude_permission_mode",
            "claude_max_turns",
            "claude_model",
        ):
            data.pop(key, None)
        return data

    # === BASIC (User Identity) ===
    name: str = "Soothe"
    """Display name for the assistant identity in system prompts."""

    system_prompt: str | None = Field(
        default_factory=_default_agent_system_prompt_body,
        description=(
            "Behavioral system prompt body; supports {assistant_name}. "
            "null or the built-in default body uses default_system_body.xml plus the "
            "runtime tool-orchestration guide. Any other value replaces the body only."
        ),
    )

    agent_instructions_max_chars: int = Field(
        default=8000,
        ge=500,
        le=100_000,
        description="Max chars inlined from AGENTS.md/CLAUDE.md in AGENT_INSTRUCTIONS",
    )

    @model_validator(mode="after")
    def _normalize_system_prompt_whitespace(self) -> AgentConfig:
        """Strip YAML block-scalar trailing newlines so defaults match the XML fragment."""
        if self.system_prompt is not None:
            object.__setattr__(self, "system_prompt", self.system_prompt.rstrip())
        return self

    # === BEHAVIOR (Response Mode) ===
    goal_completion_mode: AgenticGoalCompletionMode = Field(
        default="llm_only",
        description=(
            "When planner marks goal done: llm_only trusts StatusAssessment only; "
            "heuristic_only uses execution heuristics only; hybrid uses LLM first with fallback"
        ),
    )
    """How planner completion (require_goal_completion) combines with execution heuristics."""

    final_response: AgenticFinalResponseMode = Field(
        default="auto",
        description=(
            "On goal completion: auto uses structural heuristics to choose ledger direct vs "
            "a final CoreAgent report; always_synthesize always runs the report. "
            "Legacy alias: adaptive → auto."
        ),
    )
    """Whether to always synthesize a final CoreAgent report or use auto heuristics."""

    @field_validator("final_response", mode="before")
    @classmethod
    def _normalize_agent_final_response(cls, value: Any) -> Any:
        return normalize_agentic_final_response_mode(value)

    # === AUTOPILOT (Self-Driving) ===
    autopilot: AutopilotConfig = Field(
        default_factory=AutopilotConfig,
        description="Autopilot scheduling and self-running configuration",
    )
    """Controls 24/7 self-running behavior for both goal-level and daemon-level."""

    # === LOOP (StrangeLoop Internal Tuning) ===
    loop: StrangeLoopConfig = Field(
        default_factory=StrangeLoopConfig,
        description="StrangeLoop configuration (unified agentic+execution)",
    )
    """Internal tuning for the agent loop execution mode."""

    # === PROTOCOLS (Backend Selection) ===
    protocols: ProtocolsConfig = Field(
        default_factory=ProtocolsConfig,
        description="Protocol backends configuration (planner, policy, durability)",
    )
    """Backend protocol selection for planner, policy, and durability."""

    # === CODE INTERPRETER ===
    code_interpreter: CodeInterpreterConfig = Field(
        default_factory=CodeInterpreterConfig,
        description="Code interpreter middleware configuration",
    )
    """Embedded QuickJS interpreter for programmatic tool calling (opt-in)."""

    # === RUNTIME PERFORMANCE (IG-506) ===
    runtime: AgentRuntimeConfig = Field(
        default_factory=AgentRuntimeConfig,
        description="CoreAgent cold-start and materialization tuning",
    )

    # === CLARIFICATION RELAY (RFC-622) ===
    clarification: ClarificationConfig = Field(
        default_factory=lambda: ClarificationConfig(),
        description="Clarification relay configuration",
    )
    """How CoreAgent clarification questions are routed (manual TUI vs auto/veritas)."""

    # === VERITAS (Clarification auto-answerer, RFC-622) ===
    veritas: VeritasConfig = Field(
        default_factory=lambda: VeritasConfig(),
        description="Veritas auto-answerer configuration",
    )
    """Settings for the intent-grounded clarification answerer."""


class ClarificationConfig(BaseModel):
    """RFC-622: configuration for the clarification relay.

    Only structured ``ask_user`` LangGraph interrupts are detected. Plain-text
    questions in assistant messages are NOT treated as clarifications —
    callers that want a clarification must emit an ``ask_user`` interrupt.
    """

    auto_policy: Literal["veritas"] = "veritas"
    """Auto-mode policy. Only ``veritas`` is supported today."""

    auto_min_confidence: float = Field(default=0.4, ge=0.0, le=1.0)
    """Below this confidence, ``AutoClarificationPolicy`` defers rather than answers."""

    max_defer_age_hours: int = Field(default=168, ge=1)
    """Autopilot scrubs goals stuck in ``awaiting_clarification`` past this age."""

    default_mode: Literal["auto", "manual"] = "auto"
    """Mode used when a request payload does not specify ``clarification_mode``.

    ``auto`` routes clarifications through the veritas auto-answerer.
    ``manual`` routes them through the TUI relay (interactive policy).
    Autopilot always forces ``auto`` regardless of this setting.
    """


class VeritasConfig(BaseModel):
    """RFC-622: configuration for the veritas auto-answerer subagent."""

    model_role: Literal["default", "fast", "think", "image", "ocr", "embedding"] = "think"
    """Which ``ModelRole`` to use for veritas calls; defaults to ``think``."""

    max_context_steps: int = Field(default=8, ge=0)
    """How many recent step outputs to include in the veritas user prompt."""


class SkillifyConfig(BaseModel):
    """Configuration for the daemon-shared Skillify semantic skill search service."""

    enabled: bool = False
    model_role: ModelRole = Field(
        default="embedding",
        description="Router model role used for Skillify embedding calls.",
    )
    warehouse_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Extra SKILL.md roots for vector indexing. "
            "Defaults (~/.soothe/skills and ~/.agents/skills) are always prepended when absent."
        ),
    )
    index_collection: str = "soothe_skillify"
    index_interval_seconds: int = 300
    retrieval_top_k: int = 10


class CronConfig(BaseModel):
    """RFC-229: configuration for the cron service.

    Natural language scheduled job submission for Autopilot.

    Args:
        max_jobs: Maximum scheduled jobs per user.
        poll_interval: Seconds between due-job monitoring ticks.
        extraction_model: LLM role for natural language extraction.
        extraction_timeout: Timeout for LLM extraction calls.
        default_priority: Default job priority when not specified.
    """

    max_jobs: int = Field(default=100, ge=1, le=1000, description="Max scheduled jobs per user")
    poll_interval: int = Field(
        default=60, ge=10, le=3600, description="Monitoring tick interval in seconds"
    )
    extraction_model: Literal["default", "fast", "think", "image", "ocr", "embedding"] = Field(
        default="fast", description="LLM role for NL extraction"
    )
    extraction_timeout: int = Field(
        default=30, ge=5, le=120, description="Extraction timeout in seconds"
    )
    default_priority: int = Field(default=50, ge=1, le=100, description="Default job priority")
    timezone: str = Field(
        default="local",
        description=(
            "Timezone for cron/at wall-clock schedules: 'local' (system), 'UTC', "
            "or an IANA name such as 'Asia/Shanghai'"
        ),
    )


class SecurityConfig(BaseModel):
    """Security policy configuration for filesystem access control.

    Args:
        allow_paths_outside_workspace: Allow access to paths outside workspace root.
        require_approval_for_outside_paths: Require user approval for outside paths.

        denied_paths: Glob patterns for explicitly denied paths.
            Examples: ["~/.ssh/**", "~/.gnupg/**", "**/.env", "**/credentials.json"]
            Priority: High (evaluated first)

        allowed_paths: Glob patterns for explicitly allowed paths (overrides denied).
            Examples: ["**"] (allow all), ["/tmp/**"] (only /tmp)
            Priority: Medium (evaluated after denied)

        denied_file_types: File extensions that require approval or are denied.
            Examples: [".env", ".pem", ".key", ".p12", ".pfx"]

        require_approval_for_file_types: File types that need user approval.
            Examples: [".env", ".pem", ".key"] - User will be prompted before access

    Path Evaluation Order:
    1. Check denied_paths - if matched, deny immediately
    2. Check allowed_paths - if matched, allow
    3. Check workspace boundary
    4. Apply file type restrictions
    5. Default deny
    """

    allow_paths_outside_workspace: bool = False
    require_approval_for_outside_paths: bool = True

    denied_paths: list[str] = Field(
        default_factory=lambda: [
            "/etc/**",
            "/bin/**",
            "/sbin/**",
            "/usr/**",
            "/System/**",
            "/Library/**",
            "/private/etc/**",
            "~/.ssh/**",
            "~/.gnupg/**",
            "~/.aws/**",
            "**/.env",
            "**/credentials.json",
            "**/secrets.json",
        ]
    )
    allowed_paths: list[str] = Field(default_factory=lambda: ["**"])

    denied_file_types: list[str] = Field(default_factory=list)
    require_approval_for_file_types: list[str] = Field(
        default_factory=lambda: [".env", ".pem", ".key", ".p12", ".pfx", ".crt"]
    )
    whitelist_paths_bypass: list[str] = Field(default_factory=list)
    """Path patterns that bypass default deny checks in operation security."""
    whitelist_commands_bypass: list[str] = Field(default_factory=list)
    """Regex patterns that bypass default command deny checks in operation security."""


# ---------------------------------------------------------------------------
# Model Knowledge Cutoff Constants (RFC-104)
# ---------------------------------------------------------------------------

MODEL_KNOWLEDGE_CUTOFFS: dict[str, str] = {
    # Claude 4.x family
    "claude-opus-4-6": "2025-05",
    "claude-sonnet-4-6": "2025-05",
    "claude-haiku-4-5": "2025-10",
    # Claude 3.5 family
    "claude-3-5-sonnet": "2025-04",
    "claude-3-5-haiku": "2025-04",
    # Claude 3 family
    "claude-3-opus": "2025-02",
    "claude-3-sonnet": "2024-08",
    "claude-3-haiku": "2024-08",
    # OpenAI models
    "gpt-4o": "2025-03",
    "gpt-4o-mini": "2025-03",
    "gpt-4-turbo": "2025-01",
    "gpt-4": "2025-01",
    "o1": "2025-04",
    "o1-mini": "2025-04",
    "o3-mini": "2025-04",
    # DeepSeek
    "deepseek-chat": "2025-02",
    "deepseek-reasoner": "2025-02",
    # Default fallback
    "default": "2025-01",
}
"""Knowledge cutoff dates for known models (YYYY-MM format)."""


def get_knowledge_cutoff(model_id: str) -> str:
    """Get knowledge cutoff date for a model.

    Args:
        model_id: Model identifier string (e.g., "claude-opus-4-6" or "openai:claude-opus-4-6").

    Returns:
        Knowledge cutoff date string in YYYY-MM format.
    """
    # Handle provider:model format
    if ":" in model_id:
        model_id = model_id.rsplit(":", maxsplit=1)[-1]

    return MODEL_KNOWLEDGE_CUTOFFS.get(model_id, MODEL_KNOWLEDGE_CUTOFFS["default"])

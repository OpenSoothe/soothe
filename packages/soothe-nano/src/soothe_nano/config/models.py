"""Pydantic configuration models for Soothe."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from soothe_nano.config.constants import (
    DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS,
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
        name: Provider name (e.g., ``openai``, ``openrouter``, ``ollama``).
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
    """

    default: str = "openai:gpt-4o-mini"
    think: str | None = None
    fast: str | None = None
    image: str | None = None
    ocr: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_embedding_role(cls, data: Any) -> Any:
        """Reject removed ``router.embedding`` mappings."""
        if isinstance(data, dict) and "embedding" in data:
            msg = (
                "router.embedding has been removed. "
                "Configure embeddings via top-level embedding_profile instead."
            )
            raise ValueError(msg)
        return data


class RouterProfile(BaseModel):
    """Named preset combining a :class:`ModelRouter`.

    Use with ``active_router_profile`` on :class:`~soothe.config.settings.SootheConfig`
    to switch between deployment targets (cloud vs local) without editing role mappings.

    Args:
        name: Unique profile identifier (e.g. ``production``, ``local-deploy``).
        router: Role → ``provider:model`` mapping for this preset.
    """

    name: str
    router: ModelRouter

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_embedding_dims(cls, data: Any) -> Any:
        """Reject removed ``router_profiles[].embedding_dims`` values."""
        if isinstance(data, dict) and "embedding_dims" in data:
            msg = (
                "router_profiles[].embedding_dims has been removed. "
                "Configure embeddings via top-level embedding_profile instead."
            )
            raise ValueError(msg)
        return data


class EmbeddingProfile(BaseModel):
    """Embedding model + vector dimension configuration.

    Args:
        model_role: Embedding model spec in ``provider:model`` form.
        embedding_dims: Output vector dimension for the embedding model.
    """

    model_role: str = "openai:text-embedding-3-small"
    embedding_dims: int = 1536

    @field_validator("model_role")
    @classmethod
    def _validate_model_role(cls, value: str) -> str:
        spec = str(value or "").strip()
        if ":" not in spec:
            msg = "embedding_profile.model_role must use 'provider:model' format."
            raise ValueError(msg)
        return spec


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
    """Configuration for a single subagent.

    Args:
        enabled: Whether this subagent is enabled.
        model: Optional explicit ``provider:model`` override.
        model_role: Optional router role for model selection.
        transport: Subagent transport mode.
        endpoint: Remote endpoint URL when using remote transports.
        config: Subagent-specific nested configuration.
        runtime_dir: Runtime directory for subagent artifacts.
    """

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
    endpoint: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    runtime_dir: str = ""
    """Runtime directory for subagent. Defaults to SOOTHE_HOME/agents/<name>/."""

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_url_field(cls, data: Any) -> Any:
        """Accept legacy ``url`` input and map it to ``endpoint``."""
        if isinstance(data, dict) and "endpoint" not in data and "url" in data:
            data = dict(data)
            data["endpoint"] = data.get("url")
        return data

    @property
    def url(self) -> str | None:
        """Backward-compatible alias for ``endpoint``."""
        return self.endpoint

    @url.setter
    def url(self, value: str | None) -> None:
        self.endpoint = value


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
        proxy: Optional HTTP(S) proxy URL for wizsearch engines/crawl
            (e.g. ``http://127.0.0.1:7890``). Applied for the duration of each
            search/crawl call; process-wide ``HTTP(S)_PROXY`` still wins if set.

    Note: The crawler runs in headless mode by default (BrowserConfig default in wizsearch backend).
    """

    default_engines: list[str] = Field(default_factory=lambda: ["tavily"])
    max_results_per_engine: int = 10
    timeout: int = 30
    proxy: str | None = None


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

    Note: LangGraph checkpoints share the process checkpoints database
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
            "Used by LangGraph checkpointer and durable metadata stores; "
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
            "Fraction of CoreAgentMiddlewareConfig.context_window_limit (chars, not tokens) "
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
            "Fraction of CoreAgentMiddlewareConfig.context_window_limit (chars, not tokens) "
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
        general_purpose_subagent: Expose soothe_deepagents ``general-purpose`` delegate via ``task``.
        recursion_limit: LangGraph recursion limit for CoreAgent graph execution.
        role_routing: Per-hop orchestration vs generation model roles (IG-545).
    """

    lazy_core_agent: bool = Field(
        default=True,
        description="Defer CoreAgent graph compile until first execute access",
    )
    general_purpose_subagent: bool = Field(
        default=False,
        description=(
            "When true, register soothe_deepagents general-purpose subagent on the task tool. "
            "When false (default), general-purpose is hidden and blocked."
        ),
    )
    recursion_limit: int = Field(
        default=200,
        ge=1,
        le=10_000,
        description=(
            "LangGraph recursion limit for CoreAgent runs; higher values allow deeper "
            "ReAct/tool-call loops before GraphRecursionError."
        ),
    )
    role_routing: RoleRoutingConfig = Field(
        default_factory=RoleRoutingConfig,
        description="Per-hop model role routing for CoreAgent ReAct loop",
    )


def _default_agent_system_prompt_body() -> str:
    """Lazy import to avoid pulling prompt fragments at config import time."""
    from soothe_nano.prompts.system_templates import default_agent_system_prompt_body

    return default_agent_system_prompt_body()


class CoreAgentMiddlewareConfig(BaseModel):
    """CoreAgent middleware tuning (context limits, tool caps, rate limits).

    Replaces legacy ``agent.loop.*`` fields used by Coding CoreAgent middleware.
    """

    context_window_limit: int = Field(
        default=200_000,
        description="Model context window token limit for percentage calculation",
        ge=10_000,
        le=1_000_000,
    )
    tool_output: LoopToolOutputConfig = Field(
        default_factory=LoopToolOutputConfig,
        description="Tool result size caps for graph state and model context",
    )
    llm_rate_limit: LLMRateLimitConfig = Field(
        default_factory=LLMRateLimitConfig,
        description="LLM rate limiting, per-call timeouts, and retry escalation",
    )
    tool_timeout: ToolTimeoutConfig = Field(
        default_factory=ToolTimeoutConfig,
        description="Tool timeout middleware configuration",
    )
    tool_call_limit: ToolCallLimitConfig = Field(
        default_factory=ToolCallLimitConfig,
        description="Tool call count limits per thread/run",
    )
    tool_retry: ToolRetryConfig = Field(
        default_factory=ToolRetryConfig,
        description="Tool failure retry policy",
    )
    report_output: ReportOutputConfig = Field(
        default_factory=ReportOutputConfig,
        description="Terminal/file behavior for synthesized reports",
    )


class AgentConfig(BaseModel):
    """Slim Coding CoreAgent configuration (identity, protocols, middleware tuning).

    Args:
        name: Display name for the assistant identity in system prompts.
        system_prompt: System prompt override. None generates default using name.
        protocols: Protocol backends configuration (planner, policy, durability).
        code_interpreter: Code interpreter middleware configuration.
        runtime: CoreAgent cold-start and materialization tuning.
        middleware: Context limits, tool output caps, and middleware guards.
    """

    model_config = ConfigDict(extra="ignore")

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

    protocols: ProtocolsConfig = Field(
        default_factory=ProtocolsConfig,
        description="Protocol backends configuration (planner, policy, durability)",
    )

    code_interpreter: CodeInterpreterConfig = Field(
        default_factory=CodeInterpreterConfig,
        description="Code interpreter middleware configuration",
    )

    runtime: AgentRuntimeConfig = Field(
        default_factory=AgentRuntimeConfig,
        description="CoreAgent cold-start and materialization tuning",
    )

    middleware: CoreAgentMiddlewareConfig = Field(
        default_factory=CoreAgentMiddlewareConfig,
        description="CoreAgent middleware tuning (context limits, tool caps, rate limits)",
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

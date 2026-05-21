"""Pydantic configuration models for Soothe."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


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
            - ``openai``: Standard OpenAI API (full compatibility)
            - ``limited_openai``: Limited OpenAI-compatible APIs with:
              * Accept json_schema response_format but return empty content field
              * Return structured JSON in reasoning_content field (thinking tokens)
              * Limited tool_choice support (string values: "none", "auto", "required")
              Examples: LMStudio, MLXServer, certain GLM deployments
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
        pool_size: Connection pool size (pgvector).
        index_type: Index type (pgvector): hnsw, ivfflat, none.
        url: Weaviate server URL. Supports ${ENV_VAR}.
        api_key: Weaviate Cloud API key. Supports ${ENV_VAR}.
        grpc_port: Weaviate gRPC port.
    """

    name: str
    provider_type: Literal["pgvector", "weaviate", "in_memory", "sqlite_vec"] = "sqlite_vec"

    # pgvector options
    dsn: str | None = None
    pool_size: int = 5
    index_type: Literal["hnsw", "ivfflat", "none"] = "hnsw"

    # Weaviate options
    url: str | None = None
    api_key: str | None = None
    grpc_port: int = 50051


ModelRole = Literal["default", "fast", "think", "image", "embedding"]
"""Valid purpose-based model roles.

- ``default``: Main orchestrator reasoning (CoreAgent, failure analysis, system context).
- ``fast``: Cheap/fast operations (intent classification, routing, scenario classification,
  explore/tacitus subagents, memory extraction, document/audio tooling).
- ``think``: Stronger reasoning (planning, consensus validation, backoff reasoning).
- ``image``: Vision-capable model (image analysis, daemon vision preflight).
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
        embedding: Embedding model for vector operations.
    """

    default: str = "openai:gpt-4o-mini"
    think: str | None = None
    fast: str | None = None
    image: str | None = None
    embedding: str | None = None


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
    model: str | None = None
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


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server.

    Supports both stdio (command + args) and HTTP/SSE (url + transport).
    Compatible with Claude Desktop ``.mcp.json`` format.
    """

    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    transport: str = "stdio"


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
        description="Enable requests_get / requests_post / ... tools (IG-339).",
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
        image: Image analysis tools config.
        audio: Audio transcription tools config.
        video: Video analysis tools config.
        http_requests: LangChain Requests toolkit (HTTP GET/POST/PATCH/PUT/DELETE).
    """

    execution: ToolConfig = Field(default_factory=ToolConfig)
    file_ops: ToolConfig = Field(default_factory=ToolConfig)
    datetime: ToolConfig = Field(default_factory=ToolConfig)
    data: ToolConfig = Field(default_factory=ToolConfig)
    wizsearch: WebSearchConfig = Field(default_factory=WebSearchConfig)
    image: ToolConfig = Field(default_factory=ToolConfig)
    audio: ToolConfig = Field(default_factory=ToolConfig)
    video: ToolConfig = Field(default_factory=ToolConfig)
    http_requests: HttpRequestsToolsConfig = Field(default_factory=HttpRequestsToolsConfig)


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
        metadata_sqlite_path: Path for ThreadInfo metadata storage (SQLitePersistStore).
            None defaults to $SOOTHE_DATA_DIR/metadata.db.
        checkpoint_sqlite_path: Path for shared checkpoints database (LangGraph + AgentLoop).
            None defaults to $SOOTHE_DATA_DIR/soothe_checkpoints.db (IG-055 unified SQLite).
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

    Note: AgentLoop checkpoints use the same 'checkpoints' database as LangGraph
    with separate table names for schema isolation.
    """

    soothe_postgres_dsn: str = "postgresql://postgres:postgres@localhost:5432/soothe"
    """Single-database PostgreSQL DSN when ``postgres_base_dsn`` is not set."""

    default_backend: Literal["postgresql", "sqlite"] = "sqlite"

    checkpointer_pool_size: int = Field(
        default=2,
        ge=1,
        le=64,
        description=(
            "LangGraph PostgreSQL checkpointer pool max_size per process. "
            "Worker pool mode: each worker process has its own pool (N workers × pool_size connections). "
            "Thread pool mode: pool is shared across threads (daemon-level singleton via IG-406). "
            "Default 2 suits worker_pool mode; thread_pool can use 8-12 for higher concurrency."
        ),
    )
    agentloop_pool_size: int = Field(
        default=4,
        ge=1,
        le=128,
        description=(
            "Shared AgentLoop persistence pool max_size per process (checkpoints DB). "
            "Thread pool mode: single daemon-level singleton shared by all threads (IG-406). "
            "Worker pool mode: each worker process creates its own singleton (not cross-process shared). "
            "Default 4 suits worker_pool; thread_pool can use 12-30 for 200+ thread scenarios."
        ),
    )

    # IG-055: Unified SQLite architecture (metadata.db + soothe_checkpoints.db)
    metadata_sqlite_path: str | None = None  # None = $SOOTHE_DATA_DIR/metadata.db
    checkpoint_sqlite_path: str | None = (
        None  # None = $SOOTHE_DATA_DIR/soothe_checkpoints.db (shared)
    )


class MemUConfig(BaseModel):
    """MemU memory backend configuration.

    Args:
        enabled: Whether MemU memory backend is enabled.
        persist_dir: Directory for memory files. Defaults to ~/.soothe/memory.
        llm_chat_role: Router role for chat model (extraction/categorization).
        llm_embed_role: Router role for embedding model (vector search).
        enable_embeddings: Enable embedding-based similarity search.
        enable_auto_categorization: Enable automatic categorization using LLM.
        enable_category_summaries: Enable category summary generation.
        memory_categories: Predefined memory categories.
    """

    enabled: bool = True
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
        use_fast_model: Use fast model for structured output (default: True).
        routing: Routing strategy for planner selection.
        planner_model: Model role alias for planning (same as model).
    """

    model: str = "think"
    use_fast_model: bool = True

    # Config fields (IG-150 Phase 4)
    routing: Literal["auto", "always_direct", "always_planner", "always_claude"] = "auto"
    planner_model: str = "think"


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


class AutonomousConfig(BaseModel):
    """Autonomous operation configuration.

    Args:
        enabled_by_default: Whether new runs default to autonomous mode.
        max_iterations: Maximum iterations per autonomous thread.
        max_retries: Maximum retries per goal on failure.
        max_total_goals: Maximum goals allowed (RFC-0007 §5.6).
        max_goal_depth: Maximum hierarchy depth (RFC-0007 §5.6).
        enable_dynamic_goals: Enable/disable dynamic creation (RFC-0007 §5.4).
    """

    enabled_by_default: bool = False
    max_iterations: int = 10
    max_retries: int = 2
    max_total_goals: int = Field(default=50, ge=1, le=500)
    max_goal_depth: int = Field(default=5, ge=1, le=10)
    enable_dynamic_goals: bool = Field(default=True)


class PlanningConfig(BaseModel):
    """Adaptive planning configuration (RFC-0008).

    Args:
        simple_max_tokens: Skip planning for queries < N tokens.
        complexity_threshold: Tokens threshold for complex planning.
        force_keywords: Keywords that force comprehensive planning.
        adaptive_escalation: Escalate planning if iteration shows complexity.
    """

    simple_max_tokens: int = Field(
        default=50,
        description="Skip planning for queries < N tokens",
    )
    complexity_threshold: int = Field(
        default=160,
        description="Tokens threshold for complex planning",
    )

    force_keywords: list[str] = Field(
        default=["plan for", "create a plan", "steps to"],
        description="Keywords that force comprehensive planning",
    )

    adaptive_escalation: bool = Field(
        default=True,
        description="Escalate planning if iteration shows complexity",
    )


class LoopWorkingMemoryConfig(BaseModel):
    """Agentic loop working memory (RFC-203).

    In-memory scratchpad for the agentic loop; large entries spill under
    ``SOOTHE_HOME/data/threads/{thread_id}/working_memory/``.

    Args:
        enabled: Enable working memory for Layer 2 Reason prompts.
        max_inline_chars: Max size of the aggregated block injected into Reason.
        max_entry_chars_before_spill: Per-step output larger than this is written to disk.
    """

    enabled: bool = Field(default=True, description="Enable RFC-203 working memory")
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


class EarlyTerminationConfig(BaseModel):
    """Early termination configuration (RFC-0008).

    Args:
        enabled: Enable early termination based on completion signals.
        completion_signals: Signals that indicate task completion.
        error_threshold: Max errors before stopping iteration.
    """

    enabled: bool = Field(
        default=True,
        description="Enable early termination based on completion signals",
    )
    completion_signals: list[str] = Field(
        default=["task complete", "done", "finished successfully"],
        description="Signals that indicate task completion",
    )
    error_threshold: int = Field(
        default=3,
        description="Max errors before stopping iteration",
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


AgenticFinalResponseMode = Literal["adaptive", "always_synthesize"]

AgenticGoalCompletionMode = Literal["llm_only", "heuristic_only", "hybrid"]


class PlanPromptLedgerConfig(BaseModel):
    """Caps for RFC-214 ledger copies sent to plan-assess / plan-generate (IG-380).

    All limits use 0 to mean unlimited (preserve legacy behavior: full ledger, no copies).
    When any limit is positive, the plan phase uses deep-copied, trimmed messages only.
    """

    plan_ledger_max_messages: int = Field(
        default=0,
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


class RecoveryConfig(BaseModel):
    """Failure recovery configuration (RFC-0010).

    Args:
        progressive_checkpoints: Save checkpoint after each step/goal.
        auto_resume_on_start: Auto-resume incomplete threads on daemon start.
    """

    progressive_checkpoints: bool = True
    auto_resume_on_start: bool = False


class ToolCallLimitConfig(BaseModel):
    """Tool call limit configuration for ToolCallLimitMiddleware.

    Args:
        global_thread_limit: Maximum tool calls allowed per thread across all tools.
        global_run_limit: Maximum tool calls allowed per single agent invocation.
        tool_specific_limits: Tool-specific limit overrides (tool_name -> limits).
    """

    global_thread_limit: int = Field(
        default=150, ge=1, description="Global thread-level tool call limit"
    )
    global_run_limit: int = Field(default=56, ge=1, description="Global run-level tool call limit")
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


class InfrastructureLimitsConfig(BaseModel):
    """Infrastructure limits configuration (IG-407: unified agent_loop.limits).

    Consolidates execution limits and concurrency controls into flat structure.
    ConcurrencyPolicy fields are flattened directly into this config (no nested concurrency).

    Args:
        max_parallel_goals: Maximum goals running simultaneously (autonomous mode).
        max_parallel_steps: Maximum plan steps running concurrently per execute batch (executor
            schedules further batches until ready steps are exhausted).
        max_parallel_subagents: Maximum subagents running simultaneously.
        global_max_llm_calls: Cross-level circuit breaker for concurrent LLM calls.
        step_parallelism: Scheduling strategy for plan steps (sequential/dependency/max).
        llm_rpm_limit: Soft cap on LLM HTTP requests per minute.
        llm_concurrent_limit: Max concurrent in-flight LLM calls per thread.
        llm_call_timeout_seconds: Per-LLM-call timeout floor.
        llm_call_timeout_adaptive: Scale timeout based on prompt size.
        llm_call_timeout_max_seconds: Upper bound for adaptive timeout.
        llm_retry_on_timeout: Enable retry with timeout escalation (IG-295).
        llm_max_timeout_retries: Max retry attempts after timeout (IG-295).
        llm_timeout_retry_multiplier: Timeout multiplier on retry (IG-295).
        recovery: Failure recovery settings.
        tool_call_limit: Tool call limit configuration.
        tool_retry: Tool retry configuration.
    """

    # Concurrency controls (flattened from ConcurrencyPolicy)
    max_parallel_goals: int = Field(
        default=1, ge=0, description="Maximum parallel goals (0=unlimited)"
    )
    max_parallel_steps: int = Field(
        default=2,
        ge=0,
        description="Max concurrent plan steps per batch; 0=unlimited; multiple batches per execute",
    )
    max_parallel_subagents: int = Field(
        default=4, ge=0, description="Maximum parallel subagents (0=unlimited)"
    )
    global_max_llm_calls: int = Field(
        default=5, ge=0, description="Global LLM call cap (0=unlimited)"
    )
    step_parallelism: Literal["sequential", "dependency", "max"] = Field(
        default="dependency", description="Step scheduling strategy"
    )
    # IG-XXX: Tool-level concurrency limit
    max_parallel_tools: int = Field(
        default=5, ge=0, description="Maximum concurrent tool calls per thread (0=unlimited)"
    )

    # Rate limiting
    llm_rpm_limit: int = Field(default=120, ge=1, le=10_000)
    llm_concurrent_limit: int = Field(default=10, ge=1, le=500)

    # Timeout controls
    llm_call_timeout_seconds: int = Field(default=120, ge=5, le=3600)
    llm_call_timeout_adaptive: bool = True
    llm_call_timeout_max_seconds: int = Field(default=120, ge=60, le=3600)

    # IG-295: Retry with timeout escalation
    llm_retry_on_timeout: bool = True
    llm_max_timeout_retries: int = Field(default=2, ge=0, le=5)
    llm_timeout_retry_multiplier: float = Field(default=2.0, ge=1.0, le=5.0)

    # Tool limits
    recovery: RecoveryConfig = Field(default_factory=RecoveryConfig)
    tool_call_limit: ToolCallLimitConfig = Field(default_factory=ToolCallLimitConfig)
    tool_retry: ToolRetryConfig = Field(default_factory=ToolRetryConfig)


class OutputStreamingConfig(BaseModel):
    """Configuration for output streaming behavior (RFC-614).

    Controls how goal_completion synthesis and other assistant outputs are
    delivered from daemon to client. Supports batch (coalesce all) and adaptive
    (stream small outputs, batch large outputs) modes.

    Args:
        mode: Streaming mode - "batch" (coalesce all) or "adaptive" (stream small, batch large).
        streaming_interval_ms: Daemon WebSocket batching interval (milliseconds).
        tui_flush_interval_ms: TUI rendering flush interval (milliseconds).
        adaptive_threshold_chars: Threshold for adaptive mode switching (chars).
        file_output_threshold_chars: Threshold to write goal_completion to file (0 = never).
        file_output_preview_chars: Preview chars in TUI when output saved to file.
        file_output_dir: Directory for output files (default: current workspace root/.soothe/output).
    """

    mode: Literal["batch", "adaptive"] = Field(
        default="adaptive",
        description="Streaming mode - batch: coalesce all, adaptive: stream small, batch large",
    )
    streaming_interval_ms: int = Field(
        default=200,
        ge=50,
        le=1000,
        description="Daemon WebSocket batching interval (milliseconds)",
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
        description="Chars threshold for adaptive mode switching",
    )
    file_output_threshold_chars: int = Field(
        default=5000,
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


class AgentLoopConfig(BaseModel):
    """Configuration for agent loop execution mode (RFC-201, IG-407: unified config).

    Unified configuration consolidating agentic behavior fields and infrastructure limits.
    Behavior fields are placed directly under agent_loop.* for easy access (max 2 levels nesting).
    Infrastructure limits are grouped in dedicated agent_loop.limits.* subsection.

    Args:
        enabled: Enable agent loop mode.
        max_iterations: Maximum agent loop iterations.
        max_subagent_tasks_per_wave: Cap ``task`` tool completions per Act wave (0 = unlimited).
        agent_loop_output_contract_enabled: Append anti-repetition instructions to sequential Act prompts.
        final_response: Whether to always synthesize a final CoreAgent report, reuse last Execute
            assistant text when appropriate, or use adaptive heuristics (IG-199).
        planning: Planning configuration.
        early_termination: Early termination configuration.
        working_memory: Working memory / spill configuration (RFC-203).
        goal_context: Goal context injection for Plan/Execute phases (RFC-217).
        report_output: Goal report display and synthesis limits.
        output_streaming: Enable streaming mode for all AI outputs (true=stream, false=batch).
        goal_completion_mode: How planner completion (`require_goal_completion`) combines with
            execution heuristics when the goal is assessed as done (IG-298).
        plan_prompt_ledger: Ledger projection caps for Plan-phase LLM prompts (IG-380).
        limits: Infrastructure limits configuration (rate limiting, concurrency, timeouts, tool limits).

    Note: Performance optimizations (intent/routing classification pipeline, optimize_system_prompts,
    parallel_pre_stream) are always enabled by design and not configurable.
    """

    enabled: bool = Field(
        default=True,
        description="Enable agent loop mode",
    )

    max_iterations: int = Field(
        default=10,
        description="Maximum agent loop iterations",
        ge=1,
        le=500,
    )

    max_subagent_tasks_per_wave: int = Field(
        default=4,
        description="Max completed subagent ``task`` tool results per Execute wave (0 = no limit)",
        ge=0,
        le=20,
    )

    agent_loop_output_contract_enabled: bool = Field(
        default=True,
        description="Instruct CoreAgent not to paste full tool outputs again during AgentLoop Execute phase",
    )

    final_response: AgenticFinalResponseMode = Field(
        default="adaptive",
        description=(
            "On goal completion: adaptive uses heuristics to choose ledger direct vs "
            "a final CoreAgent report; always_synthesize always runs the report"
        ),
    )

    goal_completion_mode: AgenticGoalCompletionMode = Field(
        default="llm_only",
        description=(
            "When the planner marks the goal done: llm_only trusts StatusAssessment only; "
            "heuristic_only uses execution heuristics only; hybrid uses LLM first with heuristic fallback"
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

    output_streaming: OutputStreamingConfig = Field(
        default_factory=OutputStreamingConfig,
        description="Output streaming configuration (RFC-614)",
    )

    loop_orchestrator_evidence_validate: bool = Field(
        default=True,
        description=(
            "When evidence_ledger is non-empty, require valid StepAction.evidence_refs (RFC-220)."
        ),
    )

    planning: PlanningConfig = Field(
        default_factory=PlanningConfig,
        description="Planning configuration",
    )

    early_termination: EarlyTerminationConfig = Field(
        default_factory=EarlyTerminationConfig,
        description="Early termination configuration",
    )

    working_memory: LoopWorkingMemoryConfig = Field(
        default_factory=LoopWorkingMemoryConfig,
        description="Loop working memory (RFC-203)",
    )

    goal_context: GoalContextConfig = Field(
        default_factory=GoalContextConfig,
        description="Goal context injection for Plan/Execute phases (RFC-217)",
    )

    report_output: ReportOutputConfig = Field(
        default_factory=ReportOutputConfig,
        description="Terminal/file behavior for synthesized goal reports",
    )

    plan_prompt_ledger: PlanPromptLedgerConfig = Field(
        default_factory=PlanPromptLedgerConfig,
        description="Plan-phase ledger projection limits (IG-380); zeros = full ledger passthrough",
    )

    # IG-407: Infrastructure limits subsection
    limits: InfrastructureLimitsConfig = Field(
        default_factory=InfrastructureLimitsConfig,
        description="Infrastructure limits (rate limiting, concurrency, timeouts, tool limits)",
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


class PreviewDefaults(BaseModel):
    """Default settings for the unified text preview utility.

    Args:
        chars: Default character limit for char-based previews.
        lines: Default line limit for line-based previews.
    """

    chars: int = Field(default=200, ge=50, le=1000)
    """Default character limit for char-based previews."""

    lines: int = Field(default=5, ge=1, le=20)
    """Default line limit for line-based previews."""


class LangfuseIntegrationConfig(BaseModel):
    """Langfuse OpenTelemetry + LangChain callback integration (optional extra ``soothe[langfuse]``).

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

    langfuse: LangfuseIntegrationConfig = Field(
        default_factory=LangfuseIntegrationConfig,
        description="Langfuse tracing (install optional extra soothe[langfuse])",
    )


class AutopilotConfig(BaseModel):
    """Autopilot mode configuration (RFC-204)."""

    max_iterations: int = Field(default=50, ge=1, le=500)
    """Maximum iterations for autonomous goal execution."""

    max_send_backs: int = Field(default=3, ge=1, le=10)
    """Per-goal send-back budget for consensus validation."""

    max_parallel_goals: int = Field(default=3, ge=1, le=10)
    """Maximum number of goals executed in parallel."""

    dreaming_enabled: bool = True
    """Whether to enter dreaming mode when all goals complete."""

    dreaming_consolidation_interval: int = Field(default=300, ge=10)
    """Seconds between memory consolidation during dreaming."""

    dreaming_health_check_interval: int = Field(default=60, ge=5)
    """Seconds between health checks during dreaming."""

    checkpoint_interval: int = Field(default=10, ge=1, le=100)
    """Iterations between periodic checkpoints."""

    scheduler_enabled: bool = True
    """Whether scheduler service is active."""

    max_scheduled_tasks: int = Field(default=100, ge=1, le=1000)
    """Maximum number of pending scheduled tasks."""

    webhooks: dict[str, str | None] = Field(default_factory=dict)
    """Webhook URLs by event type (e.g., on_goal_completed, on_goal_failed)."""


class FilesystemMiddlewareConfig(BaseModel):
    """Configuration for SootheFilesystemMiddleware.

    Args:
        backup_enabled: Enable automatic backup before file deletion.
        backup_dir: Directory for backup files.
        workspace_root: Root directory for workspace operations.
        virtual_mode: Enable path sandboxing to workspace (passed to FilesystemBackend).
        max_file_size_mb: Maximum file size for operations.
        tool_token_limit_before_evict: Token limit for large result eviction.
    """

    backup_enabled: bool = True
    """Enable automatic file backup on delete operations."""

    backup_dir: str | None = None
    """Directory for backup files. Defaults to .backups in each file's parent."""

    workspace_root: str | None = None
    """Root directory for workspace operations."""

    virtual_mode: bool = False
    """Enable path sandboxing to workspace directory (FilesystemBackend parameter)."""

    max_file_size_mb: int = 10
    """Maximum file size for operations (MB) - passed to FilesystemBackend."""

    tool_token_limit_before_evict: int | None = 20000
    """Token limit before evicting large tool results (inherited from FilesystemMiddleware)."""


class CodeInterpreterConfig(BaseModel):
    """Configuration for CodeInterpreterMiddleware (IG-423).

    Enables embedded QuickJS interpreter for programmatic tool calling and
    stateful code execution within the agent loop.

    Reference: https://www.langchain.com/blog/give-your-agents-an-interpreter

    Args:
        enabled: Enable the code interpreter middleware.
        ptc_allowlist: List of tool names exposed to interpreter via tools.* namespace.
            Empty list means no tools are exposed (security-first default).
        memory_limit_mb: Interpreter memory limit in MB.
        timeout_seconds: Per-eval timeout in seconds.
        max_ptc_calls: Maximum programmatic tool calls per eval.
        max_result_size: Maximum result size in characters.
        console_capture: Capture console.log output.
        snapshot_between_turns: Preserve interpreter state between conversation turns.
    """

    enabled: bool = True
    """Enable the code interpreter middleware. Enabled by default."""

    ptc_allowlist: list[str] = Field(default_factory=list)
    """Tools exposed to interpreter via tools.* namespace. Empty = security-first default."""

    memory_limit_mb: int = 128
    """Interpreter memory limit in MB."""

    timeout_seconds: int = 30
    """Per-eval timeout in seconds."""

    max_ptc_calls: int = 50
    """Maximum programmatic tool calls per eval."""

    max_result_size: int = 10000
    """Maximum result size in characters."""

    console_capture: bool = True
    """Capture console.log output from interpreter."""

    snapshot_between_turns: bool = False
    """Preserve interpreter state between conversation turns."""


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

        sandbox: Enable sandboxed execution via SandboxBackendProtocol. When True,
            the deepagents ``execute`` tool (sandbox-backed) is available. When False,
            the ``execute`` tool is removed. Host-execution tools (run_command,
            run_python, run_background) are always available regardless of this flag.
            Default: False

    Path Evaluation Order:
    1. Check denied_paths - if matched, deny immediately
    2. Check allowed_paths - if matched, allow
    3. Check workspace boundary
    4. Apply file type restrictions
    5. Default deny
    """

    sandbox: bool = Field(
        default=False,
        description="Enable sandboxed execution (deepagents `execute` tool via SandboxBackendProtocol). Host-execution tools (run_command, etc.) are always available. Default: False",
    )

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

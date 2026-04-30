"""Pydantic configuration models for Soothe."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from soothe.protocols.concurrency import ConcurrencyPolicy


class UIConfig(BaseModel):
    """Configuration for UI preferences.

    Args:
        theme: Theme name for the TUI (e.g., 'langchain', 'langchain-light').
    """

    theme: str | None = None
    """Theme preference for the TUI."""


class UpdateConfig(BaseModel):
    """Configuration for auto-update preferences.

    Args:
        auto_update: Whether auto-update is enabled.
    """

    auto_update: bool = False
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


class ModelRouter(BaseModel):
    """Maps purpose-based roles to ``provider_name:model_name`` strings.

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


class BrowserSubagentConfig(BaseModel):
    """Configuration for the browser subagent runtime.

    Args:
        runtime_dir: Base directory for browser runtime files.
        downloads_dir: Directory for browser downloads.
        user_data_dir: Persistent browser profile directory.
        extensions_dir: Browser extensions directory.
        cleanup_on_exit: Clean up temporary files when session ends.
        disable_extensions: Disable browser extensions.
        disable_cloud: Disable browser-use cloud service.
        disable_telemetry: Disable usage telemetry.
        enable_existing_browser: Allow connecting to existing Chrome instance via CDP.
        browser_start_timeout: Timeout in seconds for browser launch events.
        profile_mode: Browser profile lifecycle. ``persistent`` reuses a shared
            profile across invocations (keeps cookies/sessions).  ``ephemeral``
            creates a fresh UUID-named profile per invocation and deletes it on
            exit -- safe for concurrent browser tasks.
        max_steps: Maximum browser automation steps per delegated task (browser-use
            loop). Override via ``create_browser_subagent(..., max_steps=...)`` or
            YAML ``subagents.browser.config.max_steps``.
    """

    max_steps: int = Field(
        default=10, ge=1, description="Maximum browser automation steps per task."
    )
    runtime_dir: str = ""
    downloads_dir: str = ""
    user_data_dir: str = ""
    extensions_dir: str = ""
    cleanup_on_exit: bool = True
    disable_extensions: bool = True
    disable_cloud: bool = True
    disable_telemetry: bool = True
    enable_existing_browser: bool = True
    browser_start_timeout: int = 90
    profile_mode: Literal["persistent", "ephemeral"] = "ephemeral"


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
        research: Research tools config.
        image: Image analysis tools config.
        audio: Audio transcription tools config.
        video: Video analysis tools config.
    """

    execution: ToolConfig = Field(default_factory=ToolConfig)
    file_ops: ToolConfig = Field(default_factory=ToolConfig)
    datetime: ToolConfig = Field(default_factory=ToolConfig)
    data: ToolConfig = Field(default_factory=ToolConfig)
    wizsearch: WebSearchConfig = Field(default_factory=WebSearchConfig)
    research: ToolConfig = Field(default_factory=ToolConfig)
    image: ToolConfig = Field(default_factory=ToolConfig)
    audio: ToolConfig = Field(default_factory=ToolConfig)
    video: ToolConfig = Field(default_factory=ToolConfig)


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
        soothe_postgres_dsn: Legacy single-database DSN (deprecated).
            Use postgres_base_dsn + postgres_databases instead.
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

    # Legacy single-database DSN (deprecated, kept for backward compatibility)
    soothe_postgres_dsn: str = "postgresql://postgres:postgres@localhost:5432/soothe"
    """Legacy single-database DSN (deprecated). Use postgres_base_dsn instead."""

    default_backend: Literal["postgresql", "sqlite"] = "sqlite"

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
        medium_max_steps: Lightweight planning step limit.
        complexity_threshold: Tokens threshold for complex planning.
        force_keywords: Keywords that force comprehensive planning.
        adaptive_escalation: Escalate planning if iteration shows complexity.
    """

    simple_max_tokens: int = Field(
        default=50,
        description="Skip planning for queries < N tokens",
    )
    medium_max_steps: int = Field(
        default=3,
        description="Lightweight planning step limit",
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
    """Goal context injection configuration (RFC-609).

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


AgenticFinalResponseMode = Literal["adaptive", "always_synthesize", "always_last_execute"]


class AgenticLoopConfig(BaseModel):
    """Configuration for agentic loop execution mode (RFC-201).

    Args:
        enabled: Enable agentic loop mode.
        max_iterations: Maximum agentic loop iterations.
        max_subagent_tasks_per_wave: Cap ``task`` tool completions per Act wave (0 = unlimited).
        agent_loop_output_contract_enabled: Append anti-repetition instructions to sequential Act prompts.
        final_response: Whether to always synthesize a final CoreAgent report, reuse last Execute
            assistant text when appropriate, or use adaptive heuristics (IG-199).
        planning: Planning configuration.
        early_termination: Early termination configuration.
        working_memory: Working memory / spill configuration (RFC-203).
        goal_context: Goal context injection for Plan/Execute phases (RFC-609).
        report_output: Goal report display and synthesis limits.
        output_streaming: Enable streaming mode for all AI outputs (true=stream, false=batch).
        reject_done_at_iteration_zero: Guard against premature completion at iteration 0.

    Note: Performance optimizations (unified_classification, optimize_system_prompts, parallel_pre_stream)
    are always enabled by design and not configurable.
    """

    enabled: bool = Field(
        default=True,
        description="Enable agentic loop mode",
    )

    max_iterations: int = Field(
        default=10,
        description="Maximum agentic loop iterations",
        ge=1,
        le=50,
    )

    max_subagent_tasks_per_wave: int = Field(
        default=2,
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
            "On goal completion: adaptive uses heuristics to choose last Execute text vs "
            "a final CoreAgent report; always_synthesize always runs the report; always_last_execute "
            "skips the report when last Execute text exists"
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

    output_streaming: bool = Field(
        default=True,
        description="Enable streaming mode for all AI outputs (true=stream chunks, false=batch final only)",
    )

    # Performance optimization fields (simplified - only essential user-facing controls)
    reject_done_at_iteration_zero: bool = Field(
        default=False,
        description="Guard: Reject 'done' at iteration 0 with no execution (IG-053)",
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
        description="Goal context injection for Plan/Execute phases (RFC-609)",
    )

    report_output: ReportOutputConfig = Field(
        default_factory=ReportOutputConfig,
        description="Terminal/file behavior for synthesized goal reports",
    )


class FileLoggingConfig(BaseModel):
    """File logging configuration.

    Args:
        level: Logging level for file output.
        path: Log file path (empty = SOOTHE_HOME/logs/soothed.log).
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
    format: str = "%(levelname)-8s %(name)s %(message)s"


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


class ObservabilityConfig(BaseModel):
    """Unified observability configuration for debugging and monitoring.

    Consolidates LLM tracing, logging, and verbosity settings into a single section
    for better discoverability and simplified configuration.

    Args:
        llm_tracing_enabled: Enable LLM request/response tracing middleware for debugging.
        llm_tracing_preview_length: Maximum characters to log for message previews in trace logs.
        log_file_level: Logging level for file output (DEBUG, INFO, WARNING, ERROR).
        log_file_path: Log file path (empty = SOOTHE_HOME/logs/soothed.log).
        log_file_max_bytes: Maximum file size before rotation (default: 5 MB).
        log_file_backup_count: Number of rotating backup files.
        verbosity: Verbosity level for TUI/headless activity display (quiet, normal, detailed, debug).
        thread_logging_enabled: Whether thread-specific logging is enabled.
        thread_logging_retention_days: Days to retain thread logs before cleanup.
        thread_logging_max_size_mb: Maximum total size for thread logs directory.
    """

    # LLM tracing settings
    llm_tracing_enabled: bool = Field(
        default=False,
        description="Enable LLM request/response tracing middleware for debugging",
    )

    llm_tracing_preview_length: int = Field(
        default=200,
        ge=50,
        le=1000,
        description="Maximum characters to log for message previews in trace logs",
    )

    # File logging settings
    log_file_level: str = Field(
        default="INFO",
        description="Logging level for file output (DEBUG, INFO, WARNING, ERROR)",
    )

    log_file_path: str | None = Field(
        default=None,
        description="Log file path (empty = SOOTHE_HOME/logs/soothed.log)",
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
    verbosity: Literal["quiet", "normal", "detailed", "debug"] = Field(
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


class RecoveryConfig(BaseModel):
    """Failure recovery configuration (RFC-0010).

    Args:
        progressive_checkpoints: Save checkpoint after each step/goal.
        auto_resume_on_start: Auto-resume incomplete threads on daemon start.
    """

    progressive_checkpoints: bool = True
    auto_resume_on_start: bool = False


class ToolResultCacheConfig(BaseModel):
    """Configuration for tool result caching (RFC-211).

    Args:
        enabled: Enable file system caching for large tool results.
        size_threshold_bytes: Minimum size (bytes) to trigger caching.
        cleanup_on_completion: Remove cache after goal completes.
        cleanup_after_days: Remove old caches after N days.
    """

    enabled: bool = True
    """Enable file system caching for large tool results."""

    size_threshold_bytes: int = Field(default=50000, ge=1000)
    """Minimum size (bytes) to trigger caching (default: 50KB)."""

    cleanup_on_completion: bool = True
    """Remove cache after goal completes."""

    cleanup_after_days: int = Field(default=7, ge=1)
    """Remove old caches after N days."""


class ExecutionConfig(BaseModel):
    """Execution limits configuration.

    Args:
        concurrency: Concurrency limits for parallel execution.
        recovery: Failure recovery settings.
        tool_result_cache: Tool result cache settings (RFC-211).
        llm_rpm_limit: Soft cap on LLM HTTP requests per minute (middleware sliding window).
        llm_concurrent_limit: Max concurrent in-flight LLM calls per thread.
        llm_call_timeout_seconds: Per-LLM-call timeout for rate-limit middleware (floor when adaptive).
        llm_call_timeout_adaptive: Scale timeout up from the floor based on estimated prompt size.
        llm_call_timeout_max_seconds: Upper bound for adaptive per-call timeout.
    """

    concurrency: ConcurrencyPolicy = Field(default_factory=ConcurrencyPolicy)
    recovery: RecoveryConfig = Field(default_factory=RecoveryConfig)
    tool_result_cache: ToolResultCacheConfig = Field(default_factory=ToolResultCacheConfig)

    llm_rpm_limit: int = Field(default=120, ge=1, le=10_000)
    llm_concurrent_limit: int = Field(default=10, ge=1, le=500)
    llm_call_timeout_seconds: int = Field(default=120, ge=5, le=3600)
    llm_call_timeout_adaptive: bool = True
    llm_call_timeout_max_seconds: int = Field(default=900, ge=60, le=3600)


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

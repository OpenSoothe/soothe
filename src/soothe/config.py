"""Declarative configuration for Soothe agents."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from soothe.protocols.concurrency import ConcurrencyPolicy

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings
    from langchain_core.language_models import BaseChatModel

SOOTHE_HOME: str = os.environ.get("SOOTHE_HOME", str(Path.home() / ".soothe"))

_DEFAULT_SYSTEM_PROMPT = """\
You are {assistant_name}, a proactive AI assistant invented by Dr. Xiaming Chen, \
designed for continuous, around-the-clock operation.

You excel at long-running, complex problem-solving -- multi-step projects, \
deep research, large-scale code changes, and tasks that require sustained \
attention across many iterations. You break down ambitious goals into \
manageable steps, track progress, and see work through to completion.

You help users by researching information, exploring codebases, automating \
browsers, generating specialist agents, and coordinating multiple capabilities \
as needed. You take initiative -- anticipating what users need, suggesting \
next steps, and following through without requiring constant direction.

Guidelines:
- Be direct and concise. Lead with answers, not preambles.
- For multi-step tasks, outline your approach briefly, then execute.
- Use your specialist capabilities proactively when they produce better results.
- If you encounter an obstacle, explain what happened and suggest alternatives.
- Never reference your internal architecture, frameworks, or technical stack.
- Maintain context across the conversation and build on prior results.
- For complex tasks, create a structured plan before diving into implementation.\
"""
"""Default Soothe home directory. Overridable via ``SOOTHE_HOME`` env var."""

_ENV_VAR_RE = re.compile(r"^\$\{(\w+)\}$")


def _resolve_env(value: str) -> str:
    """Resolve ``${ENV_VAR}`` references in config values."""
    m = _ENV_VAR_RE.match(value)
    if m:
        return os.environ.get(m.group(1), value)
    return value


def _resolve_provider_env(value: str, *, provider_name: str, field_name: str) -> str:
    """Resolve provider field env placeholders and fail fast if missing.

    Args:
        value: Raw configured field value.
        provider_name: Provider name (for error messages).
        field_name: Field name on provider config.

    Returns:
        Resolved value.

    Raises:
        ValueError: If the value is a ``${ENV_VAR}`` placeholder that could not
            be resolved from the environment.
    """
    resolved = _resolve_env(value)
    m = _ENV_VAR_RE.match(resolved)
    if m:
        env_name = m.group(1)
        msg = (
            f"Provider '{provider_name}' has unresolved env var '{env_name}' in "
            f"providers[].{field_name}. Set {env_name} or replace it with a literal value."
        )
        raise ValueError(msg)
    return resolved


class ModelProviderConfig(BaseModel):
    """Configuration for a single model provider.

    Args:
        name: Provider name (e.g., ``dashscope``, ``openrouter``, ``ollama``).
        api_base_url: Base URL for the provider's API endpoint.
        api_key: API key. Supports ``${ENV_VAR}`` syntax for env var references.
        provider_type: langchain provider type for ``init_chat_model`` /
            ``init_embeddings`` (e.g., ``openai``, ``anthropic``).
        models: Model names available from this provider (for documentation).
    """

    name: str
    api_base_url: str | None = None
    api_key: str | None = None
    provider_type: str = "openai"
    models: list[str] = Field(default_factory=list)


class ModelRouter(BaseModel):
    """Maps purpose-based roles to ``provider_name:model_name`` strings.

    Unset roles fall back to ``default``.

    Args:
        default: Default model for orchestrator reasoning.
        think: Stronger model for planning and complex reasoning.
        fast: Cheap/fast model for classification and scoring.
        image: Vision-capable model for image understanding.
        embedding: Embedding model for vector operations.
        web_search: Model for web search tasks.
    """

    default: str = "openai:gpt-4o-mini"
    think: str | None = None
    fast: str | None = None
    image: str | None = None
    embedding: str | None = None
    web_search: str | None = None


class SubagentConfig(BaseModel):
    """Configuration for a single subagent."""

    enabled: bool = True
    model: str | None = None
    transport: Literal["local", "acp", "a2a", "langgraph"] = "local"
    url: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    runtime_dir: str = ""
    """Runtime directory for subagent. Defaults to SOOTHE_HOME/agents/<name>/."""


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


class SkillifyConfig(BaseModel):
    """Configuration for the Skillify subagent (RFC-0004).

    Args:
        enabled: Whether Skillify is active.
        warehouse_paths: Additional warehouse paths beyond the default.
        index_interval_seconds: Seconds between background indexing passes.
        index_collection: Vector store collection name for skill embeddings.
        retrieval_top_k: Default number of results for retrieval queries.
    """

    enabled: bool = False
    warehouse_paths: list[str] = Field(default_factory=list)
    index_interval_seconds: int = 300
    index_collection: str = "soothe_skillify"
    retrieval_top_k: int = 10


class WeaverConfig(BaseModel):
    """Configuration for the Weaver subagent (RFC-0005).

    Args:
        enabled: Whether Weaver is active.
        generated_agents_dir: Directory for generated agent packages.
        reuse_threshold: Minimum confidence for reuse-first matching.
        reuse_collection: Vector store collection for reuse index.
        max_generation_attempts: Maximum retries for agent generation.
        allowed_tool_groups: Tool groups available to generated agents.
        allowed_mcp_servers: MCP servers available to generated agents.
    """

    enabled: bool = False
    generated_agents_dir: str = ""
    reuse_threshold: float = 0.85
    reuse_collection: str = "soothe_weaver_reuse"
    max_generation_attempts: int = 2
    allowed_tool_groups: list[str] = Field(default_factory=list)
    allowed_mcp_servers: list[str] = Field(default_factory=list)
    cleanup_old_agents_days: int = 100  # Delete agents not accessed for N days
    max_generated_agents: int = 100  # Max number of generated agents to keep


class ComplexityThresholds(BaseModel):
    """Query complexity classification thresholds.

    Args:
        trivial_words: Maximum words for a query to be classified as trivial.
        simple_words: Maximum words for a query to be classified as simple.
        medium_words: Maximum words for a query to be classified as medium.
    """

    trivial_words: int = 5
    simple_words: int = 15
    medium_words: int = 30


class PerformanceConfig(BaseModel):
    """Performance optimization configuration (RFC-0008).

    Args:
        enabled: Master switch for all performance optimizations.
        complexity_detection: Enable query complexity classification.
        skip_memory_for_simple: Skip memory recall for trivial/simple queries.
        skip_context_for_simple: Skip context projection for trivial/simple queries.
        template_planning: Use template plans for simple queries.
        parallel_pre_stream: Run memory/context operations in parallel.
        cache_size: LRU cache size for embeddings (future).
        log_timing: Log detailed timing information.
        slow_query_threshold_ms: Threshold for slow query warnings.
        thresholds: Query classification thresholds.
    """

    enabled: bool = True
    complexity_detection: bool = True
    skip_memory_for_simple: bool = True
    skip_context_for_simple: bool = True
    template_planning: bool = True
    parallel_pre_stream: bool = True
    cache_size: int = 100
    log_timing: bool = False
    slow_query_threshold_ms: int = 3000
    thresholds: ComplexityThresholds = Field(default_factory=ComplexityThresholds)


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
    """

    runtime_dir: str = ""
    downloads_dir: str = ""
    user_data_dir: str = ""
    extensions_dir: str = ""
    cleanup_on_exit: bool = True
    disable_extensions: bool = True
    disable_cloud: bool = True
    disable_telemetry: bool = True


class SootheConfig(BaseSettings):
    """Top-level configuration for a Soothe agent.

    Can be driven by environment variables (prefix ``SOOTHE_``) or passed directly.
    """

    model_config = {"env_prefix": "SOOTHE_"}

    # Model instance cache for performance
    _model_cache: dict[str, BaseChatModel] = {}
    _embedding_cache: dict[str, Embeddings] = {}

    @classmethod
    def from_yaml_file(cls, path: str) -> SootheConfig:
        """Load configuration from a YAML file.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            A configured SootheConfig instance.
        """
        import yaml

        with Path(path).open() as f:
            config_data = yaml.safe_load(f) or {}
        return cls(**config_data)

    # --- Multi-provider model config ---

    providers: list[ModelProviderConfig] = Field(default_factory=list)
    """Model provider configurations."""

    router: ModelRouter = Field(default_factory=ModelRouter)
    """Maps purpose roles to ``provider:model`` pairs."""

    embedding_dims: int = 1536
    """Embedding vector dimensions. Must match the embedding model output."""

    # --- Agent behaviour ---

    assistant_name: str = "Soothe"
    """Display name for the assistant identity in system prompts."""

    system_prompt: str | None = None
    """System prompt override. When ``None``, a default prompt is generated using ``assistant_name``."""

    subagents: dict[str, SubagentConfig] = Field(
        default_factory=lambda: {
            "research": SubagentConfig(),
            "planner": SubagentConfig(),
            "scout": SubagentConfig(),
            "browser": SubagentConfig(),
            "claude": SubagentConfig(),
            "skillify": SubagentConfig(),
            "weaver": SubagentConfig(),
        }
    )
    """Subagent name to config mapping. Set ``enabled: false`` to disable."""

    tools: list[str] = Field(
        default_factory=lambda: [
            "datetime",
            "file_edit",
            "python_executor",
            "bash",
            "tabular",
            "document",
            "wizsearch",
        ]
    )
    """Enabled tool group names (e.g. ``["jina", "serper", "image"]``)."""

    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)
    """MCP server configurations (Claude Desktop JSON format)."""

    skills: list[str] = Field(default_factory=list)
    """SKILL.md source paths passed to deepagents SkillsMiddleware."""

    memory: list[str] = Field(default_factory=list)
    """AGENTS.md file paths passed to deepagents MemoryMiddleware."""

    workspace_dir: str = "."
    """Root directory for filesystem operations. Defaults to current directory."""

    debug: bool = False
    """Enable debug mode for the underlying LangGraph agent."""

    # --- Logging ---

    log_level: str = "INFO"
    """Python logging level for the ``soothe`` logger hierarchy."""

    log_file: str | None = None
    """Log file path. Defaults to ``SOOTHE_HOME/logs/soothe.log``."""

    # --- TUI ---

    activity_max_lines: int = 300
    """Maximum number of activity lines retained in the TUI Activity Panel."""

    progress_verbosity: Literal["minimal", "normal", "detailed", "debug"] = "normal"
    """Progress visibility level for TUI and headless execution.

    - ``minimal``: assistant text and critical errors only.
    - ``normal``: protocol progress events (default).
    - ``detailed``: adds subagent custom events and tool activity.
    - ``debug``: shows all available progress events.
    """

    # --- Skillify and Weaver config (RFC-0004, RFC-0005) ---

    skillify: SkillifyConfig = Field(default_factory=SkillifyConfig)
    """Skillify subagent configuration."""

    weaver: WeaverConfig = Field(default_factory=WeaverConfig)
    """Weaver subagent configuration."""

    # --- Protocol config (RFC-0002) ---

    context_backend: Literal["keyword", "vector", "none"] = "keyword"
    """ContextProtocol implementation: ``keyword`` (tag/keyword matching),
    ``vector`` (semantic via VectorStore), or ``none`` (disabled)."""

    context_persist_dir: str | None = None
    """Directory for context persistence. Defaults to ``SOOTHE_HOME/context/``."""

    context_persist_backend: Literal["json", "rocksdb"] = "rocksdb"
    """Persistence backend for context data."""

    memory_backend: Literal["keyword", "vector", "none"] = "keyword"
    """MemoryProtocol implementation: ``keyword`` (keyword matching with
    JSON/RocksDB persistence), ``vector`` (semantic via VectorStore),
    or ``none`` (disabled)."""

    memory_persist_path: str | None = None
    """Directory for memory persistence. Defaults to ``SOOTHE_HOME/memory/``."""

    memory_persist_backend: Literal["json", "rocksdb"] = "rocksdb"
    """Persistence backend for memory data."""

    planner_routing: Literal["auto", "always_direct", "always_planner", "always_claude"] = "auto"
    """PlannerProtocol routing strategy: ``auto`` (hybrid complexity router),
    ``always_direct`` (LLM structured output), ``always_planner`` (planner subagent),
    ``always_claude`` (Claude CLI planner)."""

    policy_profile: str = "standard"
    """Active policy profile name."""

    concurrency: ConcurrencyPolicy = Field(default_factory=ConcurrencyPolicy)
    """Concurrency limits for parallel execution."""

    durability_backend: Literal["langgraph", "rocksdb"] = "rocksdb"
    """Durability backend for thread lifecycle and metadata persistence."""

    checkpointer_backend: Literal["postgres"] = "postgres"
    """LangGraph checkpoint backend. Only PostgreSQL is supported for persistence."""

    checkpointer_postgres_dsn: str = "postgresql://postgres:postgres@localhost:5432/soothe"
    """Postgres DSN for checkpoints. Default: local pgvector instance."""

    durability_metadata_path: str | None = None
    """Metadata/state path for durability backends that persist locally."""

    # Thread logging configuration
    thread_log_dir: str | None = None  # Default: SOOTHE_HOME/threads
    """Directory for thread logs. Defaults to ``SOOTHE_HOME/threads/``."""

    thread_log_retention_days: int = 100  # Auto-delete threads older than N days
    """Days to retain thread logs before cleanup."""

    thread_log_max_size_mb: int = 100  # Max total size for thread logs (not enforced yet)
    """Maximum total size for thread logs (not enforced yet)."""

    # --- Autonomous iteration (RFC-0007) ---

    autonomous_enabled_by_default: bool = False
    """Whether new runs should default to autonomous mode unless explicitly overridden."""

    autonomous_max_iterations: int = 10
    """Maximum iterations per autonomous thread before forcing stop."""

    autonomous_max_retries: int = 2
    """Maximum retries per goal on failure before marking permanently failed."""

    # --- Performance optimization (RFC-0008) ---

    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    """Performance optimization configuration."""

    # --- Vector store config ---

    vector_store_provider: Literal["pgvector", "weaviate", "none"] = "none"
    """Vector store backend for VectorContext/VectorMemory."""

    vector_store_collection: str = "soothe_default"
    """Default collection name for the vector store."""

    vector_store_config: dict[str, Any] = Field(default_factory=dict)
    """Provider-specific vector store configuration (dsn, url, etc.)."""

    # --- Model resolution ---

    def resolve_model(self, role: str = "default") -> str:
        """Resolve a model string for a given role.

        Looks up the role in the router. Falls back to ``default`` if the
        role has no explicit mapping.

        Args:
            role: Purpose role (default, think, image, embedding, fast, web_search).

        Returns:
            A ``provider_name:model_name`` string.
        """
        value = getattr(self.router, role, None)
        if value:
            return value
        return self.router.default

    def _find_provider(self, provider_name: str) -> ModelProviderConfig | None:
        """Find a provider config by name.

        Args:
            provider_name: The provider name to look up.

        Returns:
            The matching provider config, or None.
        """
        for p in self.providers:
            if p.name == provider_name:
                return p
        return None

    def _provider_kwargs(self, provider_name: str) -> tuple[str, dict[str, Any]]:
        """Build init string and kwargs for a provider:model pair.

        Args:
            provider_name: Provider name from the router string.

        Returns:
            Tuple of (model_name portion after ``:``, kwargs dict with
            ``base_url``, ``api_key``, etc.).
        """
        provider = self._find_provider(provider_name)
        kwargs: dict[str, Any] = {}
        provider_type = provider_name
        if provider:
            provider_type = provider.provider_type
            if provider.api_base_url:
                kwargs["base_url"] = _resolve_provider_env(
                    provider.api_base_url,
                    provider_name=provider.name,
                    field_name="api_base_url",
                )
                if provider_type == "openai":
                    kwargs["use_responses_api"] = False
            if provider.api_key:
                kwargs["api_key"] = _resolve_provider_env(
                    provider.api_key,
                    provider_name=provider.name,
                    field_name="api_key",
                )
        return provider_type, kwargs

    def create_chat_model(self, role: str = "default") -> BaseChatModel:
        """Create a ``BaseChatModel`` for a given role with caching.

        Resolves the role to a ``provider:model`` pair, looks up the
        provider's credentials, and calls ``init_chat_model()``.
        Caches the result to avoid recreating models.

        Args:
            role: Purpose role (default, think, fast, image, web_search).

        Returns:
            A configured ``BaseChatModel`` instance.
        """
        import logging

        from langchain.chat_models import init_chat_model

        logger = logging.getLogger(__name__)

        model_str = self.resolve_model(role)
        provider_name, _, model_name = model_str.partition(":")
        if not model_name:
            model_name = provider_name
            provider_name = ""

        # Check cache first
        cache_key = model_str
        if cache_key in self._model_cache:
            logger.debug("Using cached model for '%s'", model_str)
            return self._model_cache[cache_key]

        provider_type, kwargs = self._provider_kwargs(provider_name)
        init_str = f"{provider_type}:{model_name}" if provider_name else model_str

        # Create and cache the model
        model = init_chat_model(init_str, **kwargs)
        self._model_cache[cache_key] = model
        logger.debug("Created and cached model for '%s'", model_str)

        return model

    def create_embedding_model(self) -> Embeddings:
        """Create an ``Embeddings`` instance using the ``embedding`` role with caching.

        Returns:
            A configured langchain ``Embeddings`` instance.
        """
        import logging

        from langchain.embeddings import init_embeddings

        logger = logging.getLogger(__name__)

        model_str = self.resolve_model("embedding")
        provider_name, _, model_name = model_str.partition(":")
        if not model_name:
            model_name = provider_name
            provider_name = ""

        # Check cache first
        cache_key = model_str
        if cache_key in self._embedding_cache:
            logger.debug("Using cached embedding model for '%s'", model_str)
            return self._embedding_cache[cache_key]

        provider_type, kwargs = self._provider_kwargs(provider_name)
        kwargs.pop("use_responses_api", None)
        init_str = f"{provider_type}:{model_name}" if provider_name else model_str

        # Create and cache the embedding model
        embeddings = init_embeddings(init_str, **kwargs)
        self._embedding_cache[cache_key] = embeddings
        logger.debug("Created and cached embedding model for '%s'", model_str)

        return embeddings

    def resolve_system_prompt(self) -> str:
        """Return the effective system prompt.

        Uses ``system_prompt`` if set, otherwise generates a default prompt
        using ``assistant_name``.

        Returns:
            The system prompt string.
        """
        if self.system_prompt:
            return self.system_prompt
        return _DEFAULT_SYSTEM_PROMPT.format(assistant_name=self.assistant_name)

    def propagate_env(self) -> None:
        """Set provider-specific env vars for downstream libraries.

        Examines providers and sets conventional env vars
        (``OPENAI_API_KEY``, ``OLLAMA_HOST``, etc.) if not already present.
        """
        for provider in self.providers:
            if provider.provider_type == "openai" and provider.api_key:
                resolved_key = _resolve_provider_env(
                    provider.api_key,
                    provider_name=provider.name,
                    field_name="api_key",
                )
                os.environ.setdefault("OPENAI_API_KEY", resolved_key)
                if provider.api_base_url:
                    resolved_base_url = _resolve_provider_env(
                        provider.api_base_url,
                        provider_name=provider.name,
                        field_name="api_base_url",
                    )
                    os.environ.setdefault("OPENAI_BASE_URL", resolved_base_url)
            elif provider.provider_type == "ollama" and provider.api_base_url:
                resolved_base_url = _resolve_provider_env(
                    provider.api_base_url,
                    provider_name=provider.name,
                    field_name="api_base_url",
                )
                os.environ.setdefault("OLLAMA_HOST", resolved_base_url)

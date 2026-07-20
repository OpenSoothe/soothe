"""SootheConfig -- top-level configuration for a Soothe agent."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from soothe_nano.config.env import _expand_env_in_config, _resolve_env, _resolve_provider_env
from soothe_nano.config.models import (
    AgentConfig,
    ConsoleLoggingConfig,
    EmbeddingProfile,
    FilesystemMiddlewareConfig,
    GlobalHistoryConfig,
    MCPServerConfig,
    ModelProviderConfig,
    ModelRole,
    ModelRouter,
    ObservabilityConfig,
    OptimizationConfig,
    PersistenceConfig,
    PluginConfig,
    ProgressiveMCPConfig,
    ProgressiveSkillsConfig,
    ProgressiveToolsConfig,
    ReportOutputConfig,
    RouterProfile,
    SecurityConfig,
    SubagentConfig,
    ToolsConfig,
    UIConfig,
    UpdateConfig,
    VectorStoreProviderConfig,
    VectorStoreRouter,
    WorkspaceMountConfig,
)

# Lazy import to avoid circular dependency - _DEFAULT_SYSTEM_PROMPT imported in methods that use it

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings
    from langchain_core.language_models import BaseChatModel


def default_router_profiles() -> list[RouterProfile]:
    """Built-in profile used when YAML omits ``router_profiles``."""
    return [
        RouterProfile(
            name="default",
            router=ModelRouter(default="openai:gpt-4o-mini"),
        )
    ]


def default_embedding_profile() -> list[EmbeddingProfile]:
    """Built-in embedding profile used when YAML omits ``embedding_profile``."""
    return [
        EmbeddingProfile(
            model_role="openai:text-embedding-3-small",
            embedding_dims=1536,
        )
    ]


def default_vector_stores() -> list[VectorStoreProviderConfig]:
    """Built-in sqlite_vec provider used when YAML omits ``vector_stores``."""
    return [
        VectorStoreProviderConfig(
            name="sqlite_vec_default",
            provider_type="sqlite_vec",
        )
    ]


def default_vector_store_router() -> VectorStoreRouter:
    """Built-in vector store routing used when YAML omits ``vector_store_router``."""
    return VectorStoreRouter(default="sqlite_vec_default:soothe_default")


_logger = logging.getLogger(__name__)


class _SootheConfigLoggingFileView:
    """Maps flat ``observability.log_file_*`` fields to the nested ``file`` view shape."""

    __slots__ = ("_cfg",)

    def __init__(self, cfg: SootheConfig) -> None:
        self._cfg = cfg

    @property
    def level(self) -> str:
        return self._cfg.observability.log_file_level

    @property
    def path(self) -> str | None:
        return self._cfg.observability.log_file_path

    @property
    def max_bytes(self) -> int:
        return self._cfg.observability.log_file_max_bytes

    @property
    def backup_count(self) -> int:
        return self._cfg.observability.log_file_backup_count


class SootheConfigLoggingView:
    """Read-through facade for ``config.logging.*``-style access (CLI and flat YAML)."""

    __slots__ = ("_cfg",)

    def __init__(self, cfg: SootheConfig) -> None:
        self._cfg = cfg

    @property
    def verbosity(self) -> str:
        return self._cfg.observability.verbosity

    @property
    def file(self) -> _SootheConfigLoggingFileView:
        return _SootheConfigLoggingFileView(self._cfg)

    @property
    def console(self) -> ConsoleLoggingConfig:
        return self._cfg.observability.console

    @property
    def global_history(self) -> GlobalHistoryConfig:
        return self._cfg.observability.global_history

    @property
    def report_output(self) -> ReportOutputConfig:
        return self._cfg.agent.middleware.report_output

    @property
    def level(self) -> str:
        """Top-level file log level (CLI compatibility)."""
        return self._cfg.observability.log_file_level


class SootheConfig(BaseSettings):
    """Top-level configuration for a Soothe agent.

    Can be driven by environment variables (prefix ``SOOTHE_``) or passed directly.
    """

    model_config = SettingsConfigDict(env_prefix="SOOTHE_", extra="ignore")

    _llm_factory: Any = None  # LLMFactory instance (lazy-initialized)

    @property
    def llm_factory(self) -> Any:
        """Lazy-initialized LLM factory.

        Decouples model creation logic from config schema per RFC-627.
        Returns an LLMFactory instance that handles model creation,
        caching, and provider-specific wrapper application.

        Returns:
            LLMFactory instance bound to this config.
        """
        if self._llm_factory is None:
            from soothe_nano.utils.llm import LLMFactory

            self._llm_factory = LLMFactory(self)
        return self._llm_factory

    @classmethod
    def from_yaml_file(cls, path: str) -> SootheConfig:
        """Load configuration from a YAML file.

        Environment variable placeholders (``${ENV_VAR}``) are recursively
        expanded throughout the entire config tree before Pydantic validation.
        This allows env vars in any string field, including nested paths:

        - ``workspace_mount.host_root: ${SOOTHE_WORKSPACE_HOST_ROOT}/subdir``
        - ``providers[].api_key: ${OPENAI_API_KEY}``
        - ``mcp_servers[].auth.headers.Authorization: Bearer ${TOKEN}``

        Unresolved env vars (not found in environment) are left as-is and
        typically fail Pydantic validation or produce warnings at runtime.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            A configured SootheConfig instance.
        """
        import yaml

        with Path(path).open() as f:
            config_data = yaml.safe_load(f) or {}
        # Recursively expand ${ENV_VAR} placeholders throughout the config tree
        config_data = _expand_env_in_config(config_data)
        return cls(**config_data)

    # --- Multi-provider model config ---

    providers: list[ModelProviderConfig] = Field(default_factory=list)
    """Model provider configurations."""

    router_profiles: list[RouterProfile] = Field(default_factory=default_router_profiles)
    """Named router presets for chat/image/ocr roles."""

    embedding_profile: list[EmbeddingProfile] = Field(default_factory=default_embedding_profile)
    """Embedding model + vector dimensions (independent from router profile switching)."""

    active_router_profile: str = "default"
    """Name of the router profile to apply. Overridable via ``SOOTHE_ACTIVE_ROUTER_PROFILE``."""

    router: ModelRouter = Field(default_factory=ModelRouter, init=False)
    """Resolved role → ``provider:model`` map from the active router profile."""

    embedding_dims: int = Field(default=1536, init=False)
    """Resolved embedding width from the active embedding profile."""

    embedding_model: str = Field(default="openai:text-embedding-3-small", init=False)
    """Resolved embedding model spec from the active embedding profile."""

    # --- Agent behaviour (unified) ---

    agent: AgentConfig = Field(default_factory=AgentConfig)
    """Unified agent configuration: identity, protocols, CoreAgent middleware tuning."""

    subagents: dict[str, SubagentConfig] = Field(default_factory=dict)
    """Subagent name to config mapping. Set ``enabled: false`` to disable.

    Builtin subagents (planner, explorer, deep_research, academic_research, browser_use) are added
    automatically. explorer is disabled by default; browser_use is included in base dependencies
    and is enabled by default. Plugin-discovered subagents are merged during config validation.
    """

    @model_validator(mode="before")
    @classmethod
    def _bootstrap_providers_from_env(cls, data: Any) -> Any:
        """Synthesize providers from env when config lists none (zero-config bootstrap)."""
        if not isinstance(data, dict):
            return data
        if data.get("providers"):
            return data

        openai_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        anthropic_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        openai_base = (os.environ.get("OPENAI_BASE_URL") or "").strip() or None

        if openai_key:
            provider: dict[str, Any] = {
                "name": "openai",
                "provider_type": "openai",
                "api_key": openai_key,
            }
            if openai_base:
                provider["api_base_url"] = openai_base
            data["providers"] = [provider]
            _logger.info("No providers in config; using OPENAI_API_KEY from environment.")
            return data

        if anthropic_key:
            data["providers"] = [
                {
                    "name": "anthropic",
                    "provider_type": "anthropic",
                    "api_key": anthropic_key,
                }
            ]
            if not data.get("router_profiles"):
                data["router_profiles"] = [
                    {
                        "name": "default",
                        "router": {"default": "anthropic:claude-sonnet-4-20250514"},
                    }
                ]
            _logger.info("No providers in config; using ANTHROPIC_API_KEY from environment.")
            return data

        return data

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_flat_router(cls, data: Any) -> Any:
        """Reject removed top-level ``router`` / ``embedding_dims`` YAML keys.

        When ``router_profiles`` is present (including ``model_dump`` round-trips),
        drop resolved ``router`` / ``embedding_dims`` copies so profile application
        remains the single source of truth.
        """
        if not isinstance(data, dict):
            return data
        if data.get("router_profiles"):
            data.pop("router", None)
            data.pop("embedding_dims", None)
            return data
        removed = [key for key in ("router", "embedding_dims") if key in data]
        if removed:
            joined = ", ".join(removed)
            msg = (
                f"Top-level {joined} removed. "
                "Define models under router_profiles and select with active_router_profile."
            )
            raise ValueError(msg)
        return data

    @model_validator(mode="before")
    @classmethod
    def _strip_daemon_top_level(cls, data: Any) -> Any:
        """Drop ``daemon:`` from agent YAML or kwargs.

        Daemon transport and server limits live in ``daemon.yml`` (``SootheDaemonConfig``).
        Older unified configs sometimes nested those keys under ``daemon`` here; they are ignored
        for ``SootheConfig`` so startup does not fail with extra_forbidden.
        """
        if isinstance(data, dict):
            data.pop("daemon", None)
        return data

    @model_validator(mode="before")
    @classmethod
    def _merge_top_level_logging_yaml(cls, data: Any) -> Any:
        """Fold top-level ``logging:`` YAML into ``observability`` and ``agent.middleware.report_output``."""
        if not isinstance(data, dict):
            return data
        logging_block = data.pop("logging", None)
        if not isinstance(logging_block, dict):
            return data
        obs: dict[str, Any] = dict(data.get("observability") or {})
        if "verbosity" in logging_block:
            obs["verbosity"] = logging_block["verbosity"]
        file_cfg = logging_block.get("file")
        if isinstance(file_cfg, dict):
            if "level" in file_cfg:
                obs["log_file_level"] = file_cfg["level"]
            if "path" in file_cfg:
                obs["log_file_path"] = file_cfg["path"]
            if "max_bytes" in file_cfg:
                obs["log_file_max_bytes"] = file_cfg["max_bytes"]
            if "backup_count" in file_cfg:
                obs["log_file_backup_count"] = file_cfg["backup_count"]
        console_cfg = logging_block.get("console")
        if isinstance(console_cfg, dict):
            obs["console"] = {**(obs.get("console") or {}), **console_cfg}
        gh_cfg = logging_block.get("global_history")
        if isinstance(gh_cfg, dict):
            obs["global_history"] = {**(obs.get("global_history") or {}), **gh_cfg}
        data["observability"] = obs
        ro = logging_block.get("report_output")
        if isinstance(ro, dict):
            agent = dict(data.get("agent") or {})
            middleware = dict(agent.get("middleware") or {})
            prev_ro = middleware.get("report_output")
            merged_ro = {**(prev_ro if isinstance(prev_ro, dict) else {}), **ro}
            middleware["report_output"] = merged_ro
            agent["middleware"] = middleware
            data["agent"] = agent
        return data

    @model_validator(mode="after")
    def _validate_router_profile_names(self) -> SootheConfig:
        """Ensure router profile names are unique."""
        if self.router_profiles:
            names = [p.name for p in self.router_profiles]
            duplicates = [n for n in names if names.count(n) > 1]
            if duplicates:
                raise ValueError(
                    f"Router profile names must be unique. Duplicates: {set(duplicates)}"
                )
        return self

    @model_validator(mode="after")
    def _apply_active_router_profile(self) -> SootheConfig:
        """Apply the selected router profile to ``router``.

        ``SOOTHE_ACTIVE_ROUTER_PROFILE`` overrides the YAML ``active_router_profile`` value
        when set, so deployments can switch presets without editing config files.
        """
        if not self.router_profiles:
            msg = "router_profiles must contain at least one profile."
            raise ValueError(msg)

        env_profile = os.environ.get("SOOTHE_ACTIVE_ROUTER_PROFILE")
        effective_profile = (
            env_profile.strip()
            if env_profile and env_profile.strip()
            else self.active_router_profile
        )
        if not effective_profile:
            msg = "active_router_profile is required."
            raise ValueError(msg)

        profile_by_name = {p.name: p for p in self.router_profiles}
        profile = profile_by_name.get(effective_profile)
        if profile is None:
            available = sorted(profile_by_name)
            msg = f"Router profile '{effective_profile}' not found. Available profiles: {available}"
            raise ValueError(msg)

        object.__setattr__(self, "active_router_profile", effective_profile)
        object.__setattr__(self, "router", profile.router)
        return self

    @model_validator(mode="after")
    def _apply_embedding_profile(self) -> SootheConfig:
        """Apply the active embedding profile to ``embedding_model`` + ``embedding_dims``."""
        if not self.embedding_profile:
            msg = "embedding_profile must contain at least one profile."
            raise ValueError(msg)
        profile = self.embedding_profile[0]
        object.__setattr__(self, "embedding_model", profile.model_role)
        object.__setattr__(self, "embedding_dims", profile.embedding_dims)
        return self

    @model_validator(mode="after")
    def _resolve_mcp_builtins(self) -> SootheConfig:
        """Merge opt-in ``mcp_builtins`` names into ``mcp_servers`` (RFC-412)."""
        if not self.mcp_builtins:
            return self

        from soothe_nano.mcp.mcp_config import resolve_mcp_builtins

        resolved = resolve_mcp_builtins(self.mcp_builtins)
        existing_names = {s.name for s in self.mcp_servers}
        merged = list(self.mcp_servers)
        for server in resolved:
            if server.name not in existing_names:
                merged.append(server)
                existing_names.add(server.name)
        object.__setattr__(self, "mcp_servers", merged)
        return self

    @model_validator(mode="after")
    def _validate_mcp_server_names(self) -> SootheConfig:
        """Ensure MCP server names are unique (RFC-412)."""
        if self.mcp_servers:
            names = [s.name for s in self.mcp_servers]
            duplicates = [n for n in names if names.count(n) > 1]
            if duplicates:
                raise ValueError(f"MCP server names must be unique. Duplicates: {set(duplicates)}")
        return self

    @model_validator(mode="after")
    def _merge_subagents(self) -> SootheConfig:
        """Merge builtin and plugin-discovered subagents with user configs."""
        # Built-in subagent entries merged before user YAML and plugin registry.
        # browser_use ships in core dependencies.
        builtin_subagents = {
            "planner": SubagentConfig(model_role="think"),
            "explorer": SubagentConfig(
                enabled=False,
                model_role="fast",
                config={"recursion_limit": 999},
            ),
            "deep_research": SubagentConfig(),
            "academic_research": SubagentConfig(),
            "browser_use": SubagentConfig(enabled=True, model_role="default"),
        }

        # Import here to avoid circular dependency
        try:
            from soothe_nano.plugin.global_registry import get_plugin_registry, is_plugins_loaded

            # Add plugin-discovered subagents if plugins are loaded
            if is_plugins_loaded():
                registry = get_plugin_registry()
                for name in registry.list_subagent_names():
                    if name not in builtin_subagents:
                        default_config = registry.get_subagent_default_config(name)
                        builtin_subagents[name] = SubagentConfig(config=default_config)
        except RuntimeError:
            # Plugins not loaded yet, use builtin only
            pass

        # Override with user-provided configs
        builtin_subagents.update(self.subagents)

        self.subagents = builtin_subagents
        return self

    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    """Tool group configurations. Each tool can be enabled/disabled and configured."""

    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)
    """MCP server configurations (RFC-412). Server names must be unique."""

    mcp_builtins: list[str] = Field(default_factory=list)
    """Opt-in builtin MCP server names (playwright, github, slack, postgres, gdrive).

    Resolved into ``mcp_servers`` at config load. Empty by default — no MCP servers
    connect until you list names here or add explicit ``mcp_servers`` entries.
    All builtins use ``defer: true`` (progressive tool loading).
    """

    progressive_mcp: ProgressiveMCPConfig = Field(default_factory=ProgressiveMCPConfig)
    """RFC-412: Progressive MCP tool listing budget tunables."""

    plugins: list[PluginConfig] = Field(default_factory=list)
    """Plugin configurations. Third-party plugins can be loaded via entry points, config, or filesystem."""

    skills: list[str] = Field(default_factory=list)
    """SKILL.md source paths passed to SkillsMiddleware."""

    progressive_skills: ProgressiveSkillsConfig = Field(default_factory=ProgressiveSkillsConfig)
    """RFC-105: Progressive skill listing budget and per-entry caps."""

    progressive_tools: ProgressiveToolsConfig = Field(default_factory=ProgressiveToolsConfig)
    """Progressive builtin-tool loading: core tier bound, deferred tools listed."""

    memory: list[str] = Field(default_factory=list)
    """AGENTS.md file paths passed to MemoryMiddleware."""

    debug: bool = False
    """Enable debug mode for the underlying LangGraph agent."""

    # --- TUI ---

    activity_max_lines: int = 300
    """Maximum number of activity lines retained in the TUI Activity Panel."""

    tui_debug: bool = False
    """Emit structured TUI trace logs (logger ``soothe.ux.tui.trace``) for EventProcessor + TuiRenderer."""

    ui: UIConfig = Field(default_factory=UIConfig)
    """UI preferences configuration (theme, etc.)."""

    update: UpdateConfig = Field(default_factory=UpdateConfig)
    """Auto-update preferences configuration."""

    # --- Nested Configuration Objects ---

    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    """Unified persistence settings for all backends."""

    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    """Unified observability configuration for debugging and monitoring."""

    security: SecurityConfig = Field(default_factory=SecurityConfig)
    """Security policy configuration."""

    filesystem_middleware: FilesystemMiddlewareConfig = Field(
        default_factory=FilesystemMiddlewareConfig
    )
    """Filesystem middleware configuration."""

    workspace_mount: WorkspaceMountConfig = Field(default_factory=WorkspaceMountConfig)
    """Container workspace path mapping (RFC-621)."""

    optimization: OptimizationConfig = Field(default_factory=OptimizationConfig)
    """Semantic optimization for risk and relationship heuristics (IG-433)."""

    # --- Vector store config ---

    vector_stores: list[VectorStoreProviderConfig] = Field(default_factory=default_vector_stores)
    """Vector store provider configurations."""

    vector_store_router: VectorStoreRouter = Field(default_factory=default_vector_store_router)
    """Maps component roles to provider:collection pairs."""

    _vector_store_cache: dict[str, Any] = {}
    """Cache for vector store instances."""

    @property
    def logging(self) -> SootheConfigLoggingView:
        """Maps CLI-style logging fields to ``observability`` and ``agent.middleware.report_output``."""
        return SootheConfigLoggingView(self)

    # --- Persistence helpers ---

    def resolve_postgres_dsn_for_database(self, db_key: str) -> str:
        """Resolve PostgreSQL DSN for a specific database component (RFC-612).

        Constructs full DSN from base_dsn + database name, with environment
        variable resolution.

        Args:
            db_key: Database component key (e.g., "checkpoints", "metadata", "vectors", "memory").

        Returns:
            Full PostgreSQL DSN for the specified database.

        Raises:
            ValueError: If db_key is not in postgres_databases mapping.
        """
        # Check for RFC-612 multi-database configuration
        if self.persistence.postgres_base_dsn:
            base_dsn = _resolve_env(self.persistence.postgres_base_dsn)

            # Get database name for the key
            db_name = self.persistence.postgres_databases.get(db_key)
            if not db_name:
                raise ValueError(
                    f"Database key '{db_key}' not found in postgres_databases mapping. "
                    f"Available keys: {list(self.persistence.postgres_databases.keys())}"
                )

            # Construct full DSN: base_dsn/database_name
            return f"{base_dsn}/{db_name}"

        return _resolve_env(self.persistence.soothe_postgres_dsn)

    def resolve_persistence_postgres_dsn(self) -> str:
        """Resolve the effective PostgreSQL DSN for persistence components.

        Uses RFC-612 multi-database architecture when ``postgres_base_dsn`` is set;
        otherwise uses ``soothe_postgres_dsn``.

        Returns:
            The configured DSN for context/memory/durability/checkpointer.
        """
        # Prefer RFC-612 multi-database configuration
        if self.persistence.postgres_base_dsn:
            # Use checkpoints database as default for checkpointer
            return self.resolve_postgres_dsn_for_database("checkpoints")

        return _resolve_env(self.persistence.soothe_postgres_dsn)

    # --- Vector store helpers ---

    def resolve_vector_store_role(self, role: str) -> str | None:
        """Resolve a vector store assignment for a given role.

        Falls back to default if role is unset.

        Args:
            role: Component role (e.g. context).

        Returns:
            "provider:collection" string or None.
        """
        value = getattr(self.vector_store_router, role, None)
        if value:
            return value
        return self.vector_store_router.default

    def _find_vector_store_provider(self, provider_name: str) -> VectorStoreProviderConfig | None:
        """Find a vector store provider config by name.

        Args:
            provider_name: Provider name to look up.

        Returns:
            Provider config or None if not found.
        """
        for p in self.vector_stores:
            if p.name == provider_name:
                return p
        return None

    def _vector_store_provider_kwargs(self, provider_name: str) -> tuple[str, dict[str, Any]]:
        """Build provider_type and kwargs for a provider.

        Handles environment variable resolution.

        Args:
            provider_name: Provider name from router string.

        Returns:
            Tuple of (provider_type, kwargs_dict).

        Raises:
            ValueError: If provider name is not found in vector_stores list.
        """
        provider = self._find_vector_store_provider(provider_name)
        kwargs: dict[str, Any] = {}

        if not provider:
            msg = (
                f"Vector store provider '{provider_name}' not found. "
                f"Add it to the vector_stores list in your configuration."
            )
            raise ValueError(msg)

        provider_type = provider.provider_type

        if provider_type == "pgvector":
            if provider.dsn:
                resolved = _resolve_provider_env(
                    provider.dsn,
                    provider_name=provider.name,
                    field_name="dsn",
                )
                if resolved:
                    kwargs["dsn"] = resolved
            # RFC-612: Auto-resolve vectors database if no explicit DSN
            elif self.persistence.postgres_base_dsn:
                kwargs["dsn"] = self.resolve_postgres_dsn_for_database("vectors")

            kwargs["pool_size"] = self.persistence.vectors_pool_size
            kwargs["index_type"] = provider.index_type
            kwargs["vector_size"] = self.embedding_dims

            if self.persistence.default_backend == "postgresql":
                try:
                    from soothe_nano.persistence.postgres_pool_lifecycle import (
                        postgres_pool_timing_from_config,
                    )
                    from soothe_nano.persistence.postgres_pool_registry import (
                        PostgresPoolRegistry,
                    )

                    registry = PostgresPoolRegistry.try_get_instance()
                    if registry is not None:
                        vectors_pool = registry.try_get_pool("vectors")
                        if vectors_pool is not None:
                            kwargs["shared_pool"] = vectors_pool
                            kwargs["pool_size"] = 0
                    kwargs["pool_timing"] = postgres_pool_timing_from_config(
                        self,
                        max_size=kwargs["pool_size"] or self.persistence.vectors_pool_size,
                    )
                except Exception:
                    logging.getLogger(__name__).debug(
                        "PGVector registry pool unavailable",
                        exc_info=True,
                    )

        elif provider_type == "weaviate":
            if provider.url:
                resolved = _resolve_provider_env(
                    provider.url,
                    provider_name=provider.name,
                    field_name="url",
                )
                if resolved:
                    kwargs["url"] = resolved
            if provider.api_key:
                resolved = _resolve_provider_env(
                    provider.api_key,
                    provider_name=provider.name,
                    field_name="api_key",
                )
                if resolved:
                    kwargs["api_key"] = resolved
            kwargs["grpc_port"] = provider.grpc_port

        elif provider_type == "sqlite_vec":
            kwargs["vector_size"] = self.embedding_dims

        return provider_type, kwargs

    def create_vector_store_for_role(
        self,
        role: str,
    ) -> Any:
        """Create a vector store instance for a given role with caching.

        Args:
            role: Component role (e.g. context).

        Returns:
            Cached or newly created VectorStoreProtocol instance.

        Raises:
            ValueError: If role has no assignment and no default is set.
        """
        import logging

        from soothe_nano.backends.vector_store import create_vector_store

        logger = logging.getLogger(__name__)

        router_str = self.resolve_vector_store_role(role)
        if not router_str:
            msg = (
                f"Vector store role '{role}' has no assignment and no default is set. "
                f"Configure vector_store_router.{role} or vector_store_router.default."
            )
            raise ValueError(msg)

        if ":" not in router_str:
            msg = f"Invalid router format '{router_str}'. Expected 'provider_name:collection_name'."
            raise ValueError(msg)

        provider_name, collection_name = router_str.split(":", 1)

        cache_key = router_str
        if cache_key in self._vector_store_cache:
            return self._vector_store_cache[cache_key]

        provider_type, kwargs = self._vector_store_provider_kwargs(provider_name)
        vs = create_vector_store(provider_type, collection_name, kwargs)

        self._vector_store_cache[cache_key] = vs
        logger.debug("Created and cached vector store for '%s'", router_str)

        return vs

    # --- Model resolution ---

    def resolve_model(self, role: ModelRole = "default") -> str:
        """Resolve a model string for a given role.

        Looks up the role in the router. Falls back to ``default`` if the
        role has no explicit mapping.

        When a stream router-profile overlay is active (loop-scoped
        ``/model-router``), chat roles resolve against that profile's
        ``ModelRouter``. The ``embedding`` role always uses the process
        active profile so vector indexes stay consistent.

        Args:
            role: Purpose role — one of the :data:`~soothe.config.models.ModelRole` values.

        Returns:
            A ``provider_name:model_name`` string.
        """
        if role == "embedding":
            return self.embedding_model

        router = self.router
        from soothe_nano.utils.runtime import get_stream_router_profile

        overlay = get_stream_router_profile()
        if overlay:
            profile = next((p for p in self.router_profiles if p.name == overlay), None)
            if profile is not None:
                router = profile.router
        value = getattr(router, role, None)
        if value:
            return value
        return router.default

    def resolve_backend(self, backend: str) -> str:
        """Resolve backend value, inheriting from persistence.default_backend if 'default'.

        Args:
            backend: Backend value from protocol config ('postgresql', 'sqlite', 'default').

        Returns:
            Concrete backend value ('postgresql' or 'sqlite').

        Example:
            config.persistence.default_backend = "postgresql"
            config.protocols.durability.backend = "default"
            config.resolve_backend("default")  # Returns "postgresql"
        """
        if backend == "default":
            return self.persistence.default_backend
        return backend

    def resolve_checkpointer_backend(self) -> str:
        """Resolve checkpointer backend from protocols.durability.checkpointer.

        Returns:
            Concrete backend value ('postgresql' or 'sqlite').
        """
        return self.resolve_backend(self.agent.protocols.durability.checkpointer)

    def resolve_durability_backend(self) -> str:
        """Resolve durability backend from protocols.durability.backend.

        Returns:
            Concrete backend value ('postgresql' or 'sqlite').
        """
        return self.resolve_backend(self.agent.protocols.durability.backend)

    def get_plugin_config(self, name: str) -> dict[str, Any]:
        """Get plugin-specific configuration.

        Args:
            name: Plugin name.

        Returns:
            Configuration dictionary for the plugin, or empty dict if not found.
        """
        for plugin in self.plugins:
            if plugin.name == name:
                return plugin.config
        return {}

    def create_chat_model(
        self,
        role: ModelRole = "default",
        *,
        fallback_role: ModelRole | None = None,
    ) -> BaseChatModel:
        """Create a ``BaseChatModel`` for a given role with caching.

        Delegates to ``llm_factory.create_chat_model``. When ``fallback_role`` is
        omitted and ``role`` is not ``default``, instantiation failure for the
        primary role retries the ``default`` router role if it resolves to a
        different ``provider:model`` spec.

        Args:
            role: Purpose role — one of the :data:`~soothe.config.models.ModelRole` values.
            fallback_role: Optional explicit fallback role. ``None`` enables automatic
                ``default`` fallback for non-``default`` primary roles.

        Returns:
            A configured ``BaseChatModel`` instance, possibly wrapped for provider compatibility.
        """
        return self.llm_factory.create_chat_model(role, fallback_role=fallback_role)

    def create_chat_model_for_spec(
        self,
        model_spec: str,
        *,
        model_params: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        """Create a chat model from an explicit ``provider:model`` string (per-turn overrides).

        Delegates to ``llm_factory.create_chat_model_for_spec``. All model creation logic
        is handled by LLMFactory per RFC-627.

        Args:
            model_spec: Resolved model string, e.g. ``anthropic:claude-sonnet-4-5``.
            model_params: Optional extra kwargs for ``init_chat_model`` (caller-validated).

        Returns:
            A configured ``BaseChatModel`` instance.

        Raises:
            ValueError: If ``model_spec`` is empty after stripping.
        """
        return self.llm_factory.create_chat_model_for_spec(model_spec, model_params)

    def create_embedding_model(self, role: ModelRole = "embedding") -> Embeddings:
        """Create an ``Embeddings`` instance for the requested role with caching.

        Delegates to ``llm_factory.create_embedding_model``. All embedding creation logic
        (DashScope special handling, caching) is handled by LLMFactory per RFC-627.

        Returns:
            A configured langchain ``Embeddings`` instance.
        """
        return self.llm_factory.create_embedding_model(role)

    def resolve_system_prompt(self) -> str:
        """Return the effective system prompt with current date context.

        Uses ``system_prompt`` if set, otherwise generates a default prompt
        using ``assistant_name``. Automatically injects the current date
        to help the agent understand time-sensitive queries like "latest"
        or "recent".

        Returns:
            The system prompt string.
        """
        from soothe_nano.prompts.identity import prepend_assistant_identity
        from soothe_nano.prompts.system_templates import (
            format_complex_agent_system_prompt_core,
        )
        from soothe_nano.utils.prompt_clock import local_date_str, local_timezone_label

        current_date = local_date_str()
        tz_label = local_timezone_label()

        base_prompt = format_complex_agent_system_prompt_core(
            self.agent.system_prompt,
            self.agent.name,
        )
        body = f"{base_prompt}\n\nToday's date is {current_date} ({tz_label})."
        return prepend_assistant_identity(body, self.agent.name)

    def propagate_env(self) -> None:
        """Set provider-specific env vars for downstream libraries.

        Examines providers and sets conventional env vars
        (``OPENAI_API_KEY``, ``OLLAMA_HOST``, etc.) if not already present.

        NOTE: Only sets env vars for providers using the standard OpenAI endpoint.
        Custom OpenAI-compatible providers (DashScope, Coding-Plan, etc.) should
        rely on explicit configuration, not environment variables.
        """
        for provider in self.providers:
            # Limited OpenAI providers use OpenAI API format
            provider_type = provider.provider_type
            if provider_type == "openai" and provider.api_key:
                # Resolve api_base_url first to check if this is a custom endpoint
                api_base_url = None
                if provider.api_base_url:
                    resolved_base_url = _resolve_provider_env(
                        provider.api_base_url,
                        provider_name=provider.name,
                        field_name="api_base_url",
                    )
                    api_base_url = resolved_base_url

                # Only set OPENAI_* env vars for standard OpenAI endpoint
                # Custom providers (DashScope, Coding-Plan, etc.) should use explicit config
                is_standard_openai = api_base_url is None or api_base_url.startswith(
                    "https://api.openai.com"
                )

                if is_standard_openai:
                    # Standard OpenAI provider - set env vars for downstream libs
                    resolved_key = _resolve_provider_env(
                        provider.api_key,
                        provider_name=provider.name,
                        field_name="api_key",
                    )
                    if resolved_key:
                        os.environ.setdefault("OPENAI_API_KEY", resolved_key)
                    if api_base_url:
                        os.environ.setdefault("OPENAI_BASE_URL", api_base_url)
                # else: Custom OpenAI-compatible endpoint - do NOT set env vars

            elif provider_type == "ollama" and provider.api_base_url:
                resolved_base_url = _resolve_provider_env(
                    provider.api_base_url,
                    provider_name=provider.name,
                    field_name="api_base_url",
                )
                if resolved_base_url:
                    os.environ.setdefault("OLLAMA_HOST", resolved_base_url)

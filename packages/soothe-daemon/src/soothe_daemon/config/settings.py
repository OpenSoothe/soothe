"""SootheConfig -- top-level configuration for a Soothe agent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

from soothe_daemon.config.daemon_config import DaemonConfig
from soothe_daemon.config.env import _resolve_env, _resolve_provider_env
from soothe_daemon.config.models import (
    AgenticLoopConfig,
    AutonomousConfig,
    AutopilotConfig,
    ExecutionConfig,
    LLMTracingConfig,
    LoggingConfig,
    MCPServerConfig,
    ModelProviderConfig,
    ModelRouter,
    PerformanceConfig,
    PersistenceConfig,
    PluginConfig,
    ProtocolsConfig,
    SecurityConfig,
    SubagentConfig,
    ToolsConfig,
    UIConfig,
    UpdateConfig,
    VectorStoreProviderConfig,
    VectorStoreRouter,
)
from soothe_daemon.config.prompts import _DEFAULT_SYSTEM_PROMPT

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings
    from langchain_core.language_models import BaseChatModel


class SootheConfig(BaseSettings):
    """Top-level configuration for a Soothe agent.

    Can be driven by environment variables (prefix ``SOOTHE_``) or passed directly.
    """

    model_config = {"env_prefix": "SOOTHE_"}

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

    subagents: dict[str, SubagentConfig] = Field(default_factory=dict)
    """Subagent name to config mapping. Set ``enabled: false`` to disable.

    Builtin subagents (browser, claude) are added automatically.
    Plugin-discovered subagents are merged during config validation.
    """

    @model_validator(mode="after")
    def _merge_subagents(self) -> SootheConfig:
        """Merge builtin and plugin-discovered subagents with user configs."""
        # Start with builtin defaults
        builtin_subagents = {
            "browser": SubagentConfig(),
            "claude": SubagentConfig(),
        }

        # Import here to avoid circular dependency
        try:
            from soothe_daemon.plugin.global_registry import get_plugin_registry, is_plugins_loaded

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
    """MCP server configurations (Claude Desktop JSON format)."""

    plugins: list[PluginConfig] = Field(default_factory=list)
    """Plugin configurations. Third-party plugins can be loaded via entry points, config, or filesystem."""

    skills: list[str] = Field(default_factory=list)
    """SKILL.md source paths passed to deepagents SkillsMiddleware."""

    memory: list[str] = Field(default_factory=list)
    """AGENTS.md file paths passed to deepagents MemoryMiddleware."""

    workspace_dir: str = "."
    """Root directory for filesystem operations. Defaults to current directory."""

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

    protocols: ProtocolsConfig = Field(default_factory=ProtocolsConfig)
    """Protocol backends configuration."""

    autonomous: AutonomousConfig = Field(default_factory=AutonomousConfig)
    """Autonomous operation configuration."""

    agentic: AgenticLoopConfig = Field(default_factory=AgenticLoopConfig)
    """Agentic loop configuration (RFC-0008)."""

    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    """Logging and observability configuration."""

    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    """Execution limits configuration."""

    llm_tracing: LLMTracingConfig = Field(default_factory=LLMTracingConfig)
    """LLM request/response tracing configuration for debugging."""

    security: SecurityConfig = Field(default_factory=SecurityConfig)
    """Security policy configuration."""

    # --- Performance optimization (RFC-0008) ---

    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    """Performance optimization configuration."""

    # --- Daemon configuration (RFC-0013) ---

    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    """Daemon multi-transport configuration."""

    autopilot: AutopilotConfig = Field(default_factory=AutopilotConfig)
    """Autopilot mode configuration (RFC-204)."""

    # --- Vector store config ---

    vector_stores: list[VectorStoreProviderConfig] = Field(default_factory=list)
    """Vector store provider configurations."""

    vector_store_router: VectorStoreRouter = Field(default_factory=VectorStoreRouter)
    """Maps component roles to provider:collection pairs."""

    _vector_store_cache: dict[str, Any] = {}
    """Cache for vector store instances."""

    # --- Persistence helpers ---

    def resolve_persistence_postgres_dsn(self) -> str:
        """Resolve the effective PostgreSQL DSN for persistence components.

        Returns:
            The configured DSN for context/memory/durability/checkpointer.
        """
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
            kwargs["pool_size"] = provider.pool_size
            kwargs["index_type"] = provider.index_type

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

        from soothe_daemon.backends.vector_store import create_vector_store

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
            logger.debug("Using cached vector store for '%s'", router_str)
            return self._vector_store_cache[cache_key]

        provider_type, kwargs = self._vector_store_provider_kwargs(provider_name)
        vs = create_vector_store(provider_type, collection_name, kwargs)

        self._vector_store_cache[cache_key] = vs
        logger.debug("Created and cached vector store for '%s'", router_str)

        return vs

    # --- Model resolution ---

    def resolve_model(self, role: str = "default") -> str:
        """Resolve a model string for a given role.

        Looks up the role in the router. Falls back to ``default`` if the
        role has no explicit mapping.

        Args:
            role: Purpose role (default, think, image, embedding, fast).

        Returns:
            A ``provider_name:model_name`` string.
        """
        value = getattr(self.router, role, None)
        if value:
            return value
        return self.router.default

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
                resolved = _resolve_provider_env(
                    provider.api_base_url,
                    provider_name=provider.name,
                    field_name="api_base_url",
                )
                if resolved:
                    kwargs["base_url"] = resolved
                    if provider_type == "openai":
                        kwargs["use_responses_api"] = False
            if provider.api_key:
                resolved = _resolve_provider_env(
                    provider.api_key,
                    provider_name=provider.name,
                    field_name="api_key",
                )
                if resolved:
                    kwargs["api_key"] = resolved
        return provider_type, kwargs

    def create_chat_model(self, role: str = "default") -> BaseChatModel:
        """Create a ``BaseChatModel`` for a given role with caching.

        Resolves the role to a ``provider:model`` pair, looks up the
        provider's credentials, and calls ``init_chat_model()``.
        Caches the result to avoid recreating models.

        For limited OpenAI-compatible providers (LMStudio, Ollama, etc.)
        that don't support the full ``tool_choice`` object format, the model
        is wrapped to force ``json_mode`` for structured output.

        Args:
            role: Purpose role (default, think, fast, image).

        Returns:
            A configured ``BaseChatModel`` instance, possibly wrapped for provider compatibility.
        """
        import logging

        from langchain.chat_models import init_chat_model

        logger = logging.getLogger(__name__)

        model_str = self.resolve_model(role)
        provider_name, _, model_name = model_str.partition(":")
        if not model_name:
            model_name = provider_name
            provider_name = ""

        cache_key = model_str
        if cache_key in self._model_cache:
            logger.debug("Using cached model for '%s'", model_str)
            return self._model_cache[cache_key]

        provider_type, kwargs = self._provider_kwargs(provider_name)
        init_str = f"{provider_type}:{model_name}" if provider_name else model_str

        model = init_chat_model(init_str, **kwargs)

        # Check provider capability for advanced tool_choice support (LMStudio compatibility)
        supports_advanced_tool_choice = True  # Default assumption
        if provider_name:
            provider = self._find_provider(provider_name)
            if provider:
                supports_advanced_tool_choice = provider.supports_advanced_tool_choice
                if not supports_advanced_tool_choice:
                    logger.info(
                        "Provider '%s' doesn't support advanced tool_choice objects, wrapping model for compatibility",
                        provider_name,
                    )
                    from soothe_daemon.core.model_wrapper import wrap_model_if_needed

                    model = wrap_model_if_needed(
                        model, provider_name, supports_advanced_tool_choice
                    )

        self._model_cache[cache_key] = model
        logger.debug("Created and cached model for '%s'", model_str)

        return model

    def create_chat_model_for_spec(
        self,
        model_spec: str,
        *,
        model_params: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        """Create a chat model from an explicit ``provider:model`` string (per-turn overrides).

        Unlike `create_chat_model(role=...)`, this does not resolve router roles.
        Results are cached under a key derived from the spec and merged params.

        Args:
            model_spec: Resolved model string, e.g. ``anthropic:claude-sonnet-4-5``.
            model_params: Optional extra kwargs for ``init_chat_model`` (caller-validated).

        Returns:
            A configured ``BaseChatModel`` instance.

        Raises:
            ValueError: If ``model_spec`` is empty after stripping.
        """
        import json
        import logging

        from langchain.chat_models import init_chat_model

        logger = logging.getLogger(__name__)

        model_str = (model_spec or "").strip()
        if not model_str:
            msg = "model_spec is required for create_chat_model_for_spec"
            raise ValueError(msg)

        merged_params = dict(model_params or {})
        cache_key = f"spec:{model_str}:{json.dumps(merged_params, sort_keys=True, default=str)}"
        if cache_key in self._model_cache:
            logger.debug("Using cached model for override key '%s'", cache_key[:120])
            return self._model_cache[cache_key]

        provider_name, _, model_name = model_str.partition(":")
        if not model_name:
            model_name = provider_name
            provider_name = ""

        provider_type, kwargs = self._provider_kwargs(provider_name)
        init_str = f"{provider_type}:{model_name}" if provider_name else model_str
        merged_kwargs = {**kwargs, **merged_params}

        model = init_chat_model(init_str, **merged_kwargs)

        supports_advanced_tool_choice = True
        if provider_name:
            provider = self._find_provider(provider_name)
            if provider:
                supports_advanced_tool_choice = provider.supports_advanced_tool_choice
                if not supports_advanced_tool_choice:
                    logger.info(
                        "Provider '%s' doesn't support advanced tool_choice objects, wrapping model for compatibility",
                        provider_name,
                    )
                    from soothe_daemon.core.model_wrapper import wrap_model_if_needed

                    model = wrap_model_if_needed(
                        model, provider_name, supports_advanced_tool_choice
                    )

        self._model_cache[cache_key] = model
        logger.debug("Created model for explicit spec '%s'", model_str)
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

        cache_key = model_str
        if cache_key in self._embedding_cache:
            logger.debug("Using cached embedding model for '%s'", model_str)
            return self._embedding_cache[cache_key]

        provider_type, kwargs = self._provider_kwargs(provider_name)
        kwargs.pop("use_responses_api", None)

        # Check if DashScope is using OpenAI-compatible endpoint
        if provider_name == "dashscope":
            base_url = kwargs.get("base_url", "")
            # If using OpenAI-compatible endpoint, use custom wrapper
            if "compatible-mode" in base_url:
                logger.debug(
                    "DashScope provider using OpenAI-compatible endpoint, using custom wrapper"
                )
                from soothe_daemon.utils.embeddings_dashscope_openai import (
                    DashScopeOpenAIEmbeddings,
                )

                # Remove base_url from kwargs to avoid duplicate parameter
                embedding_kwargs = {k: v for k, v in kwargs.items() if k != "base_url"}
                embeddings = DashScopeOpenAIEmbeddings(
                    model=model_name,
                    dimension=self.embedding_dims,
                    base_url=base_url,
                    **embedding_kwargs,
                )
            else:
                # Use native DashScope SDK for non-compatible endpoints
                from soothe_daemon.utils.embeddings_dashscope import DashScopeEmbeddings

                embeddings = DashScopeEmbeddings(
                    model=model_name, dimension=self.embedding_dims, **kwargs
                )
            self._embedding_cache[cache_key] = embeddings
            logger.debug("Created and cached DashScope embedding model for '%s'", model_str)
            return embeddings

        init_str = f"{provider_type}:{model_name}" if provider_name else model_str

        embeddings = init_embeddings(init_str, **kwargs)
        self._embedding_cache[cache_key] = embeddings
        logger.debug("Created and cached embedding model for '%s'", model_str)

        return embeddings

    def resolve_system_prompt(self) -> str:
        """Return the effective system prompt with current date context.

        Uses ``system_prompt`` if set, otherwise generates a default prompt
        using ``assistant_name``. Automatically injects the current date
        to help the agent understand time-sensitive queries like "latest"
        or "recent".

        Returns:
            The system prompt string.
        """
        import datetime as dt

        now = dt.datetime.now(dt.UTC).astimezone()
        current_date = now.strftime("%Y-%m-%d")

        base_prompt = self.system_prompt or _DEFAULT_SYSTEM_PROMPT.format(
            assistant_name=self.assistant_name
        )

        return f"{base_prompt}\n\nToday's date is {current_date}."

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
                if resolved_key:
                    os.environ.setdefault("OPENAI_API_KEY", resolved_key)
                if provider.api_base_url:
                    resolved_base_url = _resolve_provider_env(
                        provider.api_base_url,
                        provider_name=provider.name,
                        field_name="api_base_url",
                    )
                    if resolved_base_url:
                        os.environ.setdefault("OPENAI_BASE_URL", resolved_base_url)
            elif provider.provider_type == "ollama" and provider.api_base_url:
                resolved_base_url = _resolve_provider_env(
                    provider.api_base_url,
                    provider_name=provider.name,
                    field_name="api_base_url",
                )
                if resolved_base_url:
                    os.environ.setdefault("OLLAMA_HOST", resolved_base_url)

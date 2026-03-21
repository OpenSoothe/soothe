"""SootheConfig -- top-level configuration for a Soothe agent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import Field
from pydantic_settings import BaseSettings

from soothe.config.env import _resolve_env, _resolve_provider_env
from soothe.config.models import (
    AutonomousConfig,
    ExecutionConfig,
    LoggingConfig,
    MCPServerConfig,
    ModelProviderConfig,
    ModelRouter,
    PerformanceConfig,
    PersistenceConfig,
    ProtocolsConfig,
    SecurityConfig,
    SkillifyConfig,
    SubagentConfig,
    ToolsConfig,
    VectorStoreProviderConfig,
    VectorStoreRouter,
    WeaverConfig,
)
from soothe.config.prompts import _DEFAULT_SYSTEM_PROMPT

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

    subagents: dict[str, SubagentConfig] = Field(
        default_factory=lambda: {
            "browser": SubagentConfig(),
            "claude": SubagentConfig(),
            "skillify": SubagentConfig(),
            "weaver": SubagentConfig(),
        }
    )
    """Subagent name to config mapping. Set ``enabled: false`` to disable."""

    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    """Tool group configurations. Each tool can be enabled/disabled and configured."""

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

    # --- TUI ---

    activity_max_lines: int = 300
    """Maximum number of activity lines retained in the TUI Activity Panel."""

    # --- Skillify and Weaver config (RFC-0004, RFC-0005) ---

    skillify: SkillifyConfig = Field(default_factory=SkillifyConfig)
    """Skillify subagent configuration."""

    weaver: WeaverConfig = Field(default_factory=WeaverConfig)
    """Weaver subagent configuration."""

    # --- Nested Configuration Objects ---

    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    """Unified persistence settings for all backends."""

    protocols: ProtocolsConfig = Field(default_factory=ProtocolsConfig)
    """Protocol backends configuration."""

    autonomous: AutonomousConfig = Field(default_factory=AutonomousConfig)
    """Autonomous operation configuration."""

    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    """Logging and observability configuration."""

    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    """Execution limits configuration."""

    security: SecurityConfig = Field(default_factory=SecurityConfig)
    """Security policy configuration."""

    # --- Performance optimization (RFC-0008) ---

    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    """Performance optimization configuration."""

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
            role: Component role (context, skillify, weaver_reuse).

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
                kwargs["dsn"] = _resolve_provider_env(
                    provider.dsn,
                    provider_name=provider.name,
                    field_name="dsn",
                )
            kwargs["pool_size"] = provider.pool_size
            kwargs["index_type"] = provider.index_type

        elif provider_type == "weaviate":
            if provider.url:
                kwargs["url"] = _resolve_provider_env(
                    provider.url,
                    provider_name=provider.name,
                    field_name="url",
                )
            if provider.api_key:
                kwargs["api_key"] = _resolve_provider_env(
                    provider.api_key,
                    provider_name=provider.name,
                    field_name="api_key",
                )
            kwargs["grpc_port"] = provider.grpc_port

        return provider_type, kwargs

    def create_vector_store_for_role(
        self,
        role: str,
    ) -> Any:
        """Create a vector store instance for a given role with caching.

        Args:
            role: Component role (context, skillify, weaver_reuse).

        Returns:
            Cached or newly created VectorStoreProtocol instance.

        Raises:
            ValueError: If role has no assignment and no default is set.
        """
        import logging

        from soothe.backends.vector_store import create_vector_store

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
            role: Purpose role (default, think, fast, image).

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

        cache_key = model_str
        if cache_key in self._model_cache:
            logger.debug("Using cached model for '%s'", model_str)
            return self._model_cache[cache_key]

        provider_type, kwargs = self._provider_kwargs(provider_name)
        init_str = f"{provider_type}:{model_name}" if provider_name else model_str

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

        cache_key = model_str
        if cache_key in self._embedding_cache:
            logger.debug("Using cached embedding model for '%s'", model_str)
            return self._embedding_cache[cache_key]

        provider_type, kwargs = self._provider_kwargs(provider_name)
        kwargs.pop("use_responses_api", None)

        if provider_name == "dashscope":
            from soothe.utils.embeddings_dashscope import DashScopeEmbeddings

            embeddings = DashScopeEmbeddings(model=model_name, dimension=self.embedding_dims, **kwargs)
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

        base_prompt = self.system_prompt or _DEFAULT_SYSTEM_PROMPT.format(assistant_name=self.assistant_name)

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

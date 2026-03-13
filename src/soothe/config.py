"""Declarative configuration for Soothe agents."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from soothe.protocols.concurrency import ConcurrencyPolicy

SOOTHE_HOME: str = os.environ.get("SOOTHE_HOME", str(Path.home() / ".soothe"))
"""Default Soothe home directory. Overridable via ``SOOTHE_HOME`` env var."""

_ENV_VAR_RE = re.compile(r"^\$\{(\w+)\}$")


def _resolve_env(value: str) -> str:
    """Resolve ``${ENV_VAR}`` references in config values."""
    m = _ENV_VAR_RE.match(value)
    if m:
        return os.environ.get(m.group(1), value)
    return value


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


class SootheConfig(BaseSettings):
    """Top-level configuration for a Soothe agent.

    Can be driven by environment variables (prefix ``SOOTHE_``) or passed directly.
    """

    model_config = {"env_prefix": "SOOTHE_"}

    @classmethod
    def from_yaml_file(cls, path: str) -> SootheConfig:
        """Load configuration from a YAML file.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            A configured SootheConfig instance.
        """
        import yaml

        with open(path) as f:
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

    system_prompt: str | None = "You are Soothe, a helpful AI assistant powered by the Soothe multi-agent framework. You have access to various tools and subagents to help users with complex tasks. Be concise, helpful, and honest in your responses."
    """System prompt that identifies you as Soothe agent. Prepended before base agent capabilities."""

    subagents: dict[str, SubagentConfig] = Field(
        default_factory=lambda: {
            "research": SubagentConfig(),
            "planner": SubagentConfig(),
            "scout": SubagentConfig(),
            "browser": SubagentConfig(enabled=False),
            "claude": SubagentConfig(enabled=False),
            "skillify": SubagentConfig(enabled=False),
            "weaver": SubagentConfig(enabled=False),
        }
    )
    """Subagent name to config mapping. Set ``enabled: false`` to disable."""

    tools: list[str] = Field(default_factory=list)
    """Enabled tool group names (e.g. ``["jina", "serper", "image"]``)."""

    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)
    """MCP server configurations (Claude Desktop JSON format)."""

    skills: list[str] = Field(default_factory=list)
    """SKILL.md source paths passed to deepagents SkillsMiddleware."""

    memory: list[str] = Field(default_factory=list)
    """AGENTS.md file paths passed to deepagents MemoryMiddleware."""

    workspace_dir: str | None = None
    """Root directory for filesystem operations. Defaults to ``SOOTHE_HOME``."""

    debug: bool = False
    """Enable debug mode for the underlying LangGraph agent."""

    # --- Skillify and Weaver config (RFC-0004, RFC-0005) ---

    skillify: SkillifyConfig = Field(default_factory=SkillifyConfig)
    """Skillify subagent configuration."""

    weaver: WeaverConfig = Field(default_factory=WeaverConfig)
    """Weaver subagent configuration."""

    # --- Protocol config (RFC-0002) ---

    context_backend: Literal["keyword", "vector", "none"] = "keyword"
    """ContextProtocol implementation."""

    context_persist_dir: str | None = None
    """Directory for context persistence. None for in-memory only."""

    context_persist_backend: Literal["json", "rocksdb"] = "json"
    """Persistence backend for KeywordContext."""

    memory_backend: Literal["store", "vector", "none"] = "none"
    """MemoryProtocol implementation."""

    memory_persist_path: str | None = None
    """Path for memory persistence. None for in-memory only."""

    memory_persist_backend: Literal["json", "rocksdb"] = "json"
    """Persistence backend for StoreBackedMemory."""

    planner_routing: Literal["auto", "always_direct", "always_subagent", "none"] = "none"
    """PlannerProtocol routing strategy."""

    policy_profile: str = "standard"
    """Active policy profile name."""

    concurrency: ConcurrencyPolicy = Field(default_factory=ConcurrencyPolicy)
    """Concurrency limits for parallel execution."""

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
                kwargs["base_url"] = provider.api_base_url
                if provider_type == "openai":
                    kwargs["use_responses_api"] = False
            if provider.api_key:
                kwargs["api_key"] = _resolve_env(provider.api_key)
        return provider_type, kwargs

    def create_chat_model(self, role: str = "default") -> BaseChatModel:
        """Create a ``BaseChatModel`` for a given role.

        Resolves the role to a ``provider:model`` pair, looks up the
        provider's credentials, and calls ``init_chat_model()``.

        Args:
            role: Purpose role (default, think, fast, image, web_search).

        Returns:
            A configured ``BaseChatModel`` instance.
        """
        from langchain.chat_models import init_chat_model

        model_str = self.resolve_model(role)
        provider_name, _, model_name = model_str.partition(":")
        if not model_name:
            model_name = provider_name
            provider_name = ""

        provider_type, kwargs = self._provider_kwargs(provider_name)
        init_str = f"{provider_type}:{model_name}" if provider_name else model_str
        return init_chat_model(init_str, **kwargs)

    def create_embedding_model(self) -> Embeddings:
        """Create an ``Embeddings`` instance using the ``embedding`` role.

        Returns:
            A configured langchain ``Embeddings`` instance.
        """
        from langchain.embeddings import init_embeddings

        model_str = self.resolve_model("embedding")
        provider_name, _, model_name = model_str.partition(":")
        if not model_name:
            model_name = provider_name
            provider_name = ""

        provider_type, kwargs = self._provider_kwargs(provider_name)
        kwargs.pop("use_responses_api", None)
        init_str = f"{provider_type}:{model_name}" if provider_name else model_str
        return init_embeddings(init_str, **kwargs)

    def propagate_env(self) -> None:
        """Set provider-specific env vars for downstream libraries.

        Examines providers and sets conventional env vars
        (``OPENAI_API_KEY``, ``OLLAMA_HOST``, etc.) if not already present.
        """
        for provider in self.providers:
            if provider.provider_type == "openai" and provider.api_key:
                resolved_key = _resolve_env(provider.api_key)
                os.environ.setdefault("OPENAI_API_KEY", resolved_key)
                if provider.api_base_url:
                    os.environ.setdefault("OPENAI_BASE_URL", provider.api_base_url)
            elif provider.provider_type == "ollama" and provider.api_base_url:
                os.environ.setdefault("OLLAMA_HOST", provider.api_base_url)

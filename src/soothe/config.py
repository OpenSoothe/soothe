"""Declarative configuration for Soothe agents."""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class SubagentConfig(BaseModel):
    """Configuration for a single subagent."""

    enabled: bool = True
    model: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server.

    Supports both stdio (command + args) and HTTP/SSE (url + transport).
    Compatible with Claude Desktop `.mcp.json` format.
    """

    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    transport: str = "stdio"


class SootheConfig(BaseSettings):
    """Top-level configuration for a Soothe agent.

    Can be driven by environment variables (prefix `SOOTHE_`) or passed directly.
    """

    model_config = {"env_prefix": "SOOTHE_"}

    model: str | None = None
    """LLM model identifier in `provider:model` format. Overrides llm_provider/llm_chat_model."""

    llm_provider: str = "openai"
    """LLM provider name (e.g. `openai`, `anthropic`, `google-genai`)."""

    llm_api_key: str | None = None
    """API key for the LLM provider. Falls back to provider-specific env vars."""

    llm_base_url: str | None = None
    """Base URL for OpenAI-compatible endpoints (e.g. DashScope, Ollama)."""

    llm_chat_model: str = "qwen3.5-flash"
    """Chat model name within the provider."""

    llm_vision_model: str | None = None
    """Vision model name. Defaults to `llm_chat_model` if not set."""

    system_prompt: str | None = None
    """Optional system prompt prepended before the base deep agent prompt."""

    subagents: dict[str, SubagentConfig] = Field(
        default_factory=lambda: {
            "research": SubagentConfig(),
            "planner": SubagentConfig(),
            "scout": SubagentConfig(),
            "browser": SubagentConfig(enabled=False),
            "claude": SubagentConfig(enabled=False),
        }
    )
    """Subagent name to config mapping. Set `enabled: false` to disable."""

    tools: list[str] = Field(default_factory=list)
    """Enabled tool group names (e.g. `["jina", "serper", "image"]`)."""

    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)
    """MCP server configurations (Claude Desktop JSON format)."""

    skills: list[str] = Field(default_factory=list)
    """SKILL.md source paths passed to deepagents SkillsMiddleware."""

    memory: list[str] = Field(default_factory=list)
    """AGENTS.md file paths passed to deepagents MemoryMiddleware."""

    workspace_dir: str | None = None
    """Root directory for filesystem operations. When set, uses `FilesystemBackend`
    so the agent can read/write real files. Defaults to `None` (ephemeral state)."""

    debug: bool = False
    """Enable debug mode for the underlying LangGraph agent."""

    def resolve_model_string(self) -> str:
        """Resolve the effective model string in `provider:model` format.

        If `model` is explicitly set it takes precedence. Otherwise builds
        from `llm_provider` and `llm_chat_model`.

        Returns:
            Model string suitable for `langchain.chat_models.init_chat_model`.
        """
        if self.model:
            return self.model
        return f"{self.llm_provider}:{self.llm_chat_model}"

    def create_chat_model(self) -> Any:
        """Create a configured LLM instance from Soothe config.

        Uses `init_chat_model` with the resolved model string and passes
        provider-specific kwargs. Disables the Responses API for custom
        base URLs (DashScope, Ollama, etc.) since they typically don't
        support it.

        Returns:
            A `BaseChatModel` instance ready for use.
        """
        from langchain.chat_models import init_chat_model

        model_str = self.resolve_model_string()
        kwargs: dict[str, Any] = {}

        if self.llm_base_url:
            kwargs["base_url"] = self.llm_base_url
            kwargs["use_responses_api"] = False
        if self.llm_api_key:
            kwargs["api_key"] = self.llm_api_key

        return init_chat_model(model_str, **kwargs)

    def propagate_env(self) -> None:
        """Set provider-specific env vars from Soothe config for downstream libraries.

        Libraries like `browser-use` and `langchain` read `OPENAI_API_KEY` /
        `OPENAI_BASE_URL` from the environment. This bridges `SOOTHE_LLM_*`
        config to those conventions.
        """
        if self.llm_api_key and self.llm_provider == "openai":
            os.environ.setdefault("OPENAI_API_KEY", self.llm_api_key)
        if self.llm_base_url and self.llm_provider == "openai":
            os.environ.setdefault("OPENAI_BASE_URL", self.llm_base_url)

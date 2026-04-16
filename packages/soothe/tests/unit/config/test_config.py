"""Tests for SootheConfig."""

import pytest

from soothe.config import (
    MCPServerConfig,
    ModelProviderConfig,
    ModelRouter,
    SootheConfig,
    SubagentConfig,
    ToolsConfig,
    WebSearchConfig,
    _resolve_env,
    _resolve_provider_env,
)


class TestSootheConfig:
    def test_defaults(self) -> None:
        cfg = SootheConfig()
        assert cfg.debug is False
        # Check that tools is a ToolsConfig instance
        assert isinstance(cfg.tools, ToolsConfig)
        # Check that default tools are enabled
        assert cfg.tools.execution.enabled is True
        assert cfg.tools.file_ops.enabled is True
        assert cfg.tools.code_edit.enabled is True
        assert cfg.tools.datetime.enabled is True
        assert cfg.tools.data.enabled is True
        assert cfg.tools.web_search.enabled is True
        assert cfg.tools.research.enabled is True
        # Check that optional tools are enabled by default (but won't work without API keys)
        assert cfg.tools.image.enabled is True
        assert cfg.tools.audio.enabled is True
        assert cfg.tools.video.enabled is True
        assert cfg.tools.github.enabled is True
        assert cfg.mcp_servers == []
        assert cfg.skills == []
        assert cfg.memory == []
        assert cfg.providers == []
        assert cfg.router.default == "openai:gpt-4o-mini"
        assert cfg.embedding_dims == 1536
        assert cfg.autonomous.enabled_by_default is False

    def test_default_subagents(self) -> None:
        cfg = SootheConfig()
        assert "browser" in cfg.subagents
        assert "claude" in cfg.subagents
        # skillify and weaver are community plugins, not built-in
        assert "scout" not in cfg.subagents
        assert "research" not in cfg.subagents
        for name, sub_cfg in cfg.subagents.items():
            assert sub_cfg.enabled is True, f"{name} should be enabled by default"

    def test_assistant_name_default(self) -> None:
        cfg = SootheConfig()
        assert cfg.assistant_name == "Soothe"

    def test_resolve_system_prompt_default(self) -> None:
        cfg = SootheConfig()
        prompt = cfg.resolve_system_prompt()
        assert "Soothe" in prompt
        assert "long-running" in prompt
        assert "around-the-clock" in prompt

    def test_resolve_system_prompt_custom_name(self) -> None:
        cfg = SootheConfig(assistant_name="MyBot")
        prompt = cfg.resolve_system_prompt()
        assert "MyBot" in prompt
        assert "Soothe" not in prompt

    def test_resolve_system_prompt_override(self) -> None:
        cfg = SootheConfig(system_prompt="Custom prompt here")
        result = cfg.resolve_system_prompt()
        assert result.startswith("Custom prompt here")
        assert "Today's date is" in result

    def test_planner_routing_default(self) -> None:
        cfg = SootheConfig()
        assert cfg.protocols.planner.routing == "auto"

    def test_planner_routing_options(self) -> None:
        for routing in ("auto", "always_direct", "always_planner", "always_claude"):
            cfg = SootheConfig(protocols={"planner": {"routing": routing}})
            assert cfg.protocols.planner.routing == routing

    def test_workspace_dir_default(self) -> None:
        cfg = SootheConfig()
        assert cfg.workspace_dir == "."

    def test_verbosity_default(self) -> None:
        cfg = SootheConfig()
        assert cfg.logging.verbosity == "normal"

    def test_verbosity_options(self) -> None:
        for level in ("quiet", "normal", "detailed", "debug"):
            cfg = SootheConfig(logging={"verbosity": level})
            assert cfg.logging.verbosity == level


class TestLoggingConfig:
    """Tests for logging configuration."""

    def test_file_logging_defaults(self) -> None:
        """Test that file logging has correct defaults."""
        cfg = SootheConfig()
        assert cfg.logging.file.level == "INFO"
        assert cfg.logging.file.path is None
        assert cfg.logging.file.max_bytes == 5242880  # 5 MB
        assert cfg.logging.file.backup_count == 3

    def test_console_logging_defaults(self) -> None:
        """Test that console logging is disabled by default."""
        cfg = SootheConfig()
        assert cfg.logging.console.enabled is False
        assert cfg.logging.console.level == "WARNING"
        assert cfg.logging.console.stream == "stderr"
        assert cfg.logging.console.format == "%(levelname)-8s %(name)s %(message)s"

    def test_file_logging_custom_config(self) -> None:
        """Test custom file logging configuration."""
        cfg = SootheConfig(
            logging={
                "file": {
                    "level": "DEBUG",
                    "path": "/custom/path.log",
                    "max_bytes": 20971520,
                    "backup_count": 5,
                }
            }
        )
        assert cfg.logging.file.level == "DEBUG"
        assert cfg.logging.file.path == "/custom/path.log"
        assert cfg.logging.file.max_bytes == 20971520
        assert cfg.logging.file.backup_count == 5

    def test_console_logging_custom_config(self) -> None:
        """Test custom console logging configuration."""
        cfg = SootheConfig(
            logging={
                "console": {
                    "enabled": True,
                    "level": "INFO",
                    "stream": "stdout",
                    "format": "%(name)s: %(message)s",
                }
            }
        )
        assert cfg.logging.console.enabled is True
        assert cfg.logging.console.level == "INFO"
        assert cfg.logging.console.stream == "stdout"
        assert cfg.logging.console.format == "%(name)s: %(message)s"

    def test_custom_subagents(self) -> None:
        cfg = SootheConfig(
            subagents={
                "scout": SubagentConfig(enabled=True),
                "research": SubagentConfig(enabled=False),
            }
        )
        assert cfg.subagents["scout"].enabled is True
        assert cfg.subagents["research"].enabled is False

    def test_mcp_server_config_stdio(self) -> None:
        cfg = MCPServerConfig(command="npx", args=["-y", "@my/server"])
        assert cfg.transport == "stdio"
        assert cfg.command == "npx"
        assert cfg.args == ["-y", "@my/server"]

    def test_mcp_server_config_sse(self) -> None:
        cfg = MCPServerConfig(url="https://example.com/sse", transport="sse")
        assert cfg.transport == "sse"
        assert cfg.url == "https://example.com/sse"

    def test_tools_list(self) -> None:
        # Tools config is now a ToolsConfig object, not a list
        cfg = SootheConfig()
        assert isinstance(cfg.tools, ToolsConfig)
        assert cfg.tools.image.enabled is True

    def test_skills_and_memory(self) -> None:
        cfg = SootheConfig(
            skills=["/skills/user/", "/skills/project/"],
            memory=["/memory/AGENTS.md"],
        )
        assert len(cfg.skills) == 2
        assert len(cfg.memory) == 1


class TestModelRouter:
    def test_resolve_default(self) -> None:
        cfg = SootheConfig(router=ModelRouter(default="dashscope:qwen3.5-flash"))
        assert cfg.resolve_model("default") == "dashscope:qwen3.5-flash"

    def test_resolve_role_fallback(self) -> None:
        cfg = SootheConfig(router=ModelRouter(default="dashscope:qwen3.5-flash"))
        assert cfg.resolve_model("think") == "dashscope:qwen3.5-flash"

    def test_resolve_explicit_role(self) -> None:
        cfg = SootheConfig(
            router=ModelRouter(
                default="dashscope:qwen3.5-flash",
                think="idealab:glm-4.7",
            )
        )
        assert cfg.resolve_model("think") == "idealab:glm-4.7"
        assert cfg.resolve_model("default") == "dashscope:qwen3.5-flash"

    def test_resolve_all_roles(self) -> None:
        cfg = SootheConfig(
            router=ModelRouter(
                default="a:b",
                think="c:d",
                fast="e:f",
                image="g:h",
                embedding="i:j",
            )
        )
        assert cfg.resolve_model("default") == "a:b"
        assert cfg.resolve_model("think") == "c:d"
        assert cfg.resolve_model("fast") == "e:f"
        assert cfg.resolve_model("image") == "g:h"
        assert cfg.resolve_model("embedding") == "i:j"

    def test_unknown_role_fallback(self) -> None:
        cfg = SootheConfig(router=ModelRouter(default="test:model"))
        assert cfg.resolve_model("nonexistent") == "test:model"


class TestModelProvider:
    def test_find_provider(self) -> None:
        cfg = SootheConfig(
            providers=[
                ModelProviderConfig(
                    name="dashscope",
                    api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    api_key="test-key",
                    provider_type="openai",
                ),
            ]
        )
        p = cfg._find_provider("dashscope")
        assert p is not None
        assert p.name == "dashscope"
        assert p.api_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def test_find_provider_missing(self) -> None:
        cfg = SootheConfig()
        assert cfg._find_provider("nonexistent") is None


class TestResolveEnv:
    def test_env_var_substitution(self, monkeypatch) -> None:
        monkeypatch.setenv("MY_KEY", "resolved-value")
        assert _resolve_env("${MY_KEY}") == "resolved-value"

    def test_passthrough_literal(self) -> None:
        assert _resolve_env("literal-key") == "literal-key"

    def test_missing_env_returns_original(self, monkeypatch) -> None:
        monkeypatch.delenv("MISSING_KEY", raising=False)
        assert _resolve_env("${MISSING_KEY}") == "${MISSING_KEY}"

    def test_resolve_provider_env_success(self, monkeypatch) -> None:
        monkeypatch.setenv("MY_BASE_URL", "https://example.test/v1")
        assert (
            _resolve_provider_env(
                "${MY_BASE_URL}",
                provider_name="openai",
                field_name="api_base_url",
            )
            == "https://example.test/v1"
        )

    def test_resolve_provider_env_missing_returns_none(self, monkeypatch, caplog) -> None:
        import logging

        monkeypatch.delenv("MISSING_PROVIDER_KEY", raising=False)
        with caplog.at_level(logging.WARNING):
            result = _resolve_provider_env(
                "${MISSING_PROVIDER_KEY}",
                provider_name="dashscope",
                field_name="api_key",
            )
        assert result is None
        assert "dashscope" in caplog.text
        assert "MISSING_PROVIDER_KEY" in caplog.text
        assert "providers[].api_key" in caplog.text


class TestPropagateEnv:
    def test_propagate_openai_provider(self, monkeypatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        cfg = SootheConfig(
            providers=[
                ModelProviderConfig(
                    name="myopenai",
                    api_base_url="https://test.example.com",
                    api_key="test-key",
                    provider_type="openai",
                ),
            ]
        )
        cfg.propagate_env()
        import os

        assert os.environ["OPENAI_API_KEY"] == "test-key"
        assert os.environ["OPENAI_BASE_URL"] == "https://test.example.com"

    def test_propagate_openai_provider_base_url_from_env(self, monkeypatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "https://proxy.example.com/v1")
        cfg = SootheConfig(
            providers=[
                ModelProviderConfig(
                    name="myopenai",
                    api_base_url="${OPENAI_COMPAT_BASE_URL}",
                    api_key="test-key",
                    provider_type="openai",
                ),
            ]
        )
        cfg.propagate_env()
        import os

        assert os.environ["OPENAI_API_KEY"] == "test-key"
        assert os.environ["OPENAI_BASE_URL"] == "https://proxy.example.com/v1"

    def test_propagate_openai_provider_missing_api_key_warns(self, monkeypatch, caplog) -> None:
        import logging

        monkeypatch.delenv("MISSING_OPENAI_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg = SootheConfig(
            providers=[
                ModelProviderConfig(
                    name="myopenai",
                    api_key="${MISSING_OPENAI_KEY}",
                    provider_type="openai",
                ),
            ]
        )
        with caplog.at_level(logging.WARNING):
            cfg.propagate_env()
        # Should emit a warning log
        assert "myopenai" in caplog.text
        assert "MISSING_OPENAI_KEY" in caplog.text
        assert "providers[].api_key" in caplog.text

    def test_provider_kwargs_base_url_env_substitution(self, monkeypatch) -> None:
        monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://dashscope.example.com/v1")
        cfg = SootheConfig(
            providers=[
                ModelProviderConfig(
                    name="dashscope",
                    provider_type="openai",
                    api_base_url="${DASHSCOPE_BASE_URL}",
                ),
            ]
        )
        provider_type, kwargs = cfg._provider_kwargs("dashscope")
        assert provider_type == "openai"
        assert kwargs["base_url"] == "https://dashscope.example.com/v1"

    def test_provider_kwargs_missing_base_url_env_warns(self, monkeypatch, caplog) -> None:
        import logging

        monkeypatch.delenv("MISSING_BASE_URL", raising=False)
        cfg = SootheConfig(
            providers=[
                ModelProviderConfig(
                    name="dashscope",
                    provider_type="openai",
                    api_base_url="${MISSING_BASE_URL}",
                ),
            ]
        )
        with caplog.at_level(logging.WARNING):
            provider_type, kwargs = cfg._provider_kwargs("dashscope")
        # Should return the provider type
        assert provider_type == "openai"
        # base_url should not be in kwargs since it couldn't be resolved
        assert "base_url" not in kwargs
        # Should emit a warning
        assert "dashscope" in caplog.text
        assert "MISSING_BASE_URL" in caplog.text
        assert "providers[].api_base_url" in caplog.text

    def test_no_propagate_non_openai(self, monkeypatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg = SootheConfig(
            providers=[
                ModelProviderConfig(
                    name="anthropic",
                    api_key="test-key",
                    provider_type="anthropic",
                ),
            ]
        )
        cfg.propagate_env()
        import os

        assert "OPENAI_API_KEY" not in os.environ

    def test_no_providers_no_propagate(self, monkeypatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg = SootheConfig()
        cfg.propagate_env()
        import os

        assert "OPENAI_API_KEY" not in os.environ


class TestProtocolConfig:
    def test_memory_backend_options(self) -> None:
        """Test MemU memory backend configuration."""
        # Test enabled/disabled
        cfg = SootheConfig(protocols={"memory": {"enabled": False}})
        assert cfg.protocols.memory.enabled is False

        cfg = SootheConfig(protocols={"memory": {"enabled": True}})
        assert cfg.protocols.memory.enabled is True

        # Test persist_dir option
        cfg = SootheConfig(protocols={"memory": {"persist_dir": "/custom/memory/dir"}})
        assert cfg.protocols.memory.persist_dir == "/custom/memory/dir"

        # Test LLM role configuration
        cfg = SootheConfig(
            protocols={"memory": {"llm_chat_role": "fast", "llm_embed_role": "embedding"}}
        )
        assert cfg.protocols.memory.llm_chat_role == "fast"
        assert cfg.protocols.memory.llm_embed_role == "embedding"

    def test_combined_backend_options(self) -> None:
        """Test combined backend format for memory."""
        cfg = SootheConfig(
            protocols={
                "memory": {"persist_dir": "/custom/memory/dir"},
            }
        )
        assert cfg.protocols.memory.persist_dir == "/custom/memory/dir"

    def test_vector_store_config(self) -> None:
        """Test vector store multi-provider configuration."""
        cfg = SootheConfig(
            vector_stores=[
                {
                    "name": "pgvector_prod",
                    "provider_type": "pgvector",
                    "dsn": "postgresql://localhost/test",
                    "pool_size": 10,
                }
            ],
            vector_store_router={
                "default": "pgvector_prod:soothe_default",
            },
        )
        assert len(cfg.vector_stores) == 1
        assert cfg.vector_stores[0].name == "pgvector_prod"
        assert cfg.vector_stores[0].provider_type == "pgvector"
        assert cfg.vector_store_router.default == "pgvector_prod:soothe_default"

    def test_resolve_vector_store_role_with_default(self) -> None:
        """Test that role resolution falls back to default."""
        cfg = SootheConfig(
            vector_store_router={
                "default": "in_memory:soothe_default",
            }
        )
        assert cfg.resolve_vector_store_role("unknown_role") == "in_memory:soothe_default"

    def test_resolve_vector_store_role_no_default(self) -> None:
        """Test that role resolution returns None when no assignment and no default."""
        cfg = SootheConfig()
        assert cfg.resolve_vector_store_role("unknown_role") is None

    def test_vector_store_instance_caching(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that vector store instances are cached."""
        from unittest.mock import MagicMock

        mock_create = MagicMock()
        monkeypatch.setattr("soothe.backends.vector_store.create_vector_store", mock_create)

        cfg = SootheConfig(
            vector_stores=[{"name": "test_provider", "provider_type": "in_memory"}],
            vector_store_router={"default": "test_provider:collection1"},
        )

        # First call should create
        vs1 = cfg.create_vector_store_for_role("my_role")
        assert mock_create.call_count == 1

        # Second call should use cache
        vs2 = cfg.create_vector_store_for_role("my_role")
        assert mock_create.call_count == 1
        assert vs1 is vs2

    def test_vector_store_env_var_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test environment variable resolution for vector store fields."""
        monkeypatch.setenv("TEST_DSN", "postgresql://user:pass@host:5432/db")

        cfg = SootheConfig(
            vector_stores=[
                {
                    "name": "pgvector_test",
                    "provider_type": "pgvector",
                    "dsn": "${TEST_DSN}",
                }
            ],
            vector_store_router={"default": "pgvector_test:collection"},
        )

        # Verify that creating the vector store resolves the env var
        from unittest.mock import MagicMock

        mock_create = MagicMock()
        monkeypatch.setattr("soothe.backends.vector_store.create_vector_store", mock_create)

        cfg.create_vector_store_for_role("my_role")
        call_kwargs = mock_create.call_args[0][2]
        assert call_kwargs["dsn"] == "postgresql://user:pass@host:5432/db"

    def test_pgvector_dsn_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that pgvector DSN is required (no fallback)."""
        from unittest.mock import MagicMock

        mock_create = MagicMock()
        monkeypatch.setattr("soothe.backends.vector_store.create_vector_store", mock_create)

        cfg = SootheConfig(
            vector_stores=[
                {
                    "name": "pgvector_no_dsn",
                    "provider_type": "pgvector",
                    # No dsn field - should pass None to create_vector_store
                }
            ],
            vector_store_router={"default": "pgvector_no_dsn:collection"},
        )

        cfg.create_vector_store_for_role("my_role")
        call_kwargs = mock_create.call_args[0][2]
        # DSN should be None if not provided in config
        assert call_kwargs.get("dsn") is None

    def test_invalid_router_format(self) -> None:
        """Test ValueError for malformed router strings."""
        cfg = SootheConfig(vector_store_router={"default": "invalid_format_no_colon"})
        with pytest.raises(ValueError, match="Invalid router format"):
            cfg.create_vector_store_for_role("my_role")

    def test_missing_provider(self) -> None:
        """Test ValueError when provider name not found."""
        cfg = SootheConfig(
            vector_stores=[{"name": "provider1", "provider_type": "in_memory"}],
            vector_store_router={"default": "provider2:collection"},
        )
        with pytest.raises(ValueError, match="Vector store provider 'provider2' not found"):
            cfg.create_vector_store_for_role("my_role")

    def test_missing_role_assignment(self) -> None:
        """Test ValueError when role has no assignment and no default."""
        cfg = SootheConfig(
            vector_store_router={"some_role": "provider:collection"}  # No default
        )
        with pytest.raises(ValueError, match="has no assignment and no default"):
            cfg.create_vector_store_for_role("my_role")

    def test_mixed_providers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test using different providers for different roles."""
        from unittest.mock import MagicMock

        mock_create = MagicMock()
        monkeypatch.setattr("soothe.backends.vector_store.create_vector_store", mock_create)

        cfg = SootheConfig(
            vector_stores=[
                {
                    "name": "pgvector_prod",
                    "provider_type": "pgvector",
                    "dsn": "postgresql://localhost/db",
                },
                {"name": "in_memory_dev", "provider_type": "in_memory"},
            ],
            vector_store_router={
                "default": "in_memory_dev:soothe_default",
            },
        )

        # Create for default role - uses in_memory provider
        cfg.create_vector_store_for_role("default")

        # Verify the call used in_memory provider
        calls = mock_create.call_args_list
        assert calls[0][0][0] == "in_memory"


class TestToolsSettings:
    """Tests for tools configuration."""

    def test_default_tools_config(self) -> None:
        """Test that tools has correct defaults."""
        cfg = SootheConfig()
        assert hasattr(cfg, "tools")
        assert isinstance(cfg.tools, ToolsConfig)
        assert hasattr(cfg.tools, "web_search")
        assert isinstance(cfg.tools.web_search, WebSearchConfig)

    def test_web_search_default_engines(self) -> None:
        """Test that web_search default_engines defaults to ['tavily', 'duckduckgo']."""
        cfg = SootheConfig()
        assert cfg.tools.web_search.default_engines == ["tavily", "duckduckgo"]
        assert cfg.tools.web_search.max_results_per_engine == 10
        assert cfg.tools.web_search.timeout == 30
        assert cfg.tools.web_search.enabled is True

    def test_web_search_custom_config(self) -> None:
        """Test web_search with custom configuration."""
        cfg = SootheConfig(
            tools=ToolsConfig(
                web_search=WebSearchConfig(
                    enabled=True,
                    default_engines=["tavily", "duckduckgo"],
                    max_results_per_engine=15,
                    timeout=45,
                )
            )
        )
        assert cfg.tools.web_search.enabled is True
        assert cfg.tools.web_search.default_engines == ["tavily", "duckduckgo"]
        assert cfg.tools.web_search.max_results_per_engine == 15
        assert cfg.tools.web_search.timeout == 45

    def test_web_search_config_from_dict(self) -> None:
        """Test web_search config from dict."""
        cfg = SootheConfig(
            tools={
                "web_search": {
                    "enabled": True,
                    "default_engines": ["brave", "tavily"],
                    "max_results_per_engine": 20,
                    "timeout": 60,
                }
            }
        )
        assert cfg.tools.web_search.enabled is True
        assert cfg.tools.web_search.default_engines == ["brave", "tavily"]
        assert cfg.tools.web_search.max_results_per_engine == 20
        assert cfg.tools.web_search.timeout == 60

    def test_web_search_partial_config(self) -> None:
        """Test web_search with partial configuration."""
        cfg = SootheConfig(
            tools={
                "web_search": {
                    "default_engines": ["duckduckgo"],
                }
            }
        )
        # Custom value
        assert cfg.tools.web_search.default_engines == ["duckduckgo"]
        # Defaults preserved
        assert cfg.tools.web_search.max_results_per_engine == 10
        assert cfg.tools.web_search.timeout == 30
        assert cfg.tools.web_search.enabled is True

    def test_resolve_persistence_postgres_dsn_prefers_soothe_dsn(self) -> None:
        cfg = SootheConfig(
            persistence={
                "soothe_postgres_dsn": "postgresql://localhost/soothe_new",
            }
        )
        assert cfg.resolve_persistence_postgres_dsn() == "postgresql://localhost/soothe_new"

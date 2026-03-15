"""Tests for SootheConfig."""

from soothe.config import (
    MCPServerConfig,
    ModelProviderConfig,
    ModelRouter,
    SootheConfig,
    SubagentConfig,
    _resolve_env,
    _resolve_provider_env,
)


class TestSootheConfig:
    def test_defaults(self):
        cfg = SootheConfig()
        assert cfg.debug is False
        assert cfg.tools == []
        assert cfg.mcp_servers == []
        assert cfg.skills == []
        assert cfg.memory == []
        assert cfg.providers == []
        assert cfg.router.default == "openai:gpt-4o-mini"
        assert cfg.embedding_dims == 1536

    def test_default_subagents(self):
        cfg = SootheConfig()
        assert "planner" in cfg.subagents
        assert "scout" in cfg.subagents
        assert "research" in cfg.subagents
        assert "browser" in cfg.subagents
        assert "claude" in cfg.subagents
        assert "skillify" in cfg.subagents
        assert "weaver" in cfg.subagents
        for name, sub_cfg in cfg.subagents.items():
            assert sub_cfg.enabled is True, f"{name} should be enabled by default"

    def test_assistant_name_default(self):
        cfg = SootheConfig()
        assert cfg.assistant_name == "Soothe"

    def test_resolve_system_prompt_default(self):
        cfg = SootheConfig()
        prompt = cfg.resolve_system_prompt()
        assert "Soothe" in prompt
        assert "long-running" in prompt
        assert "around-the-clock" in prompt

    def test_resolve_system_prompt_custom_name(self):
        cfg = SootheConfig(assistant_name="MyBot")
        prompt = cfg.resolve_system_prompt()
        assert "MyBot" in prompt
        assert "Soothe" not in prompt

    def test_resolve_system_prompt_override(self):
        cfg = SootheConfig(system_prompt="Custom prompt here")
        assert cfg.resolve_system_prompt() == "Custom prompt here"

    def test_planner_routing_default(self):
        cfg = SootheConfig()
        assert cfg.planner_routing == "auto"

    def test_planner_routing_options(self):
        for routing in ("auto", "always_direct", "always_planner", "always_claude"):
            cfg = SootheConfig(planner_routing=routing)
            assert cfg.planner_routing == routing

    def test_workspace_dir_default(self):
        cfg = SootheConfig()
        assert cfg.workspace_dir == "."

    def test_progress_verbosity_default(self):
        cfg = SootheConfig()
        assert cfg.progress_verbosity == "normal"

    def test_progress_verbosity_options(self):
        for level in ("minimal", "normal", "detailed", "debug"):
            cfg = SootheConfig(progress_verbosity=level)
            assert cfg.progress_verbosity == level

    def test_custom_subagents(self):
        cfg = SootheConfig(
            subagents={
                "planner": SubagentConfig(enabled=True),
                "scout": SubagentConfig(enabled=False),
            }
        )
        assert cfg.subagents["planner"].enabled is True
        assert cfg.subagents["scout"].enabled is False

    def test_mcp_server_config_stdio(self):
        cfg = MCPServerConfig(command="npx", args=["-y", "@my/server"])
        assert cfg.transport == "stdio"
        assert cfg.command == "npx"
        assert cfg.args == ["-y", "@my/server"]

    def test_mcp_server_config_sse(self):
        cfg = MCPServerConfig(url="https://example.com/sse", transport="sse")
        assert cfg.transport == "sse"
        assert cfg.url == "https://example.com/sse"

    def test_tools_list(self):
        cfg = SootheConfig(tools=["jina", "serper", "image"])
        assert cfg.tools == ["jina", "serper", "image"]

    def test_skills_and_memory(self):
        cfg = SootheConfig(
            skills=["/skills/user/", "/skills/project/"],
            memory=["/memory/AGENTS.md"],
        )
        assert len(cfg.skills) == 2
        assert len(cfg.memory) == 1


class TestModelRouter:
    def test_resolve_default(self):
        cfg = SootheConfig(router=ModelRouter(default="dashscope:qwen3.5-flash"))
        assert cfg.resolve_model("default") == "dashscope:qwen3.5-flash"

    def test_resolve_role_fallback(self):
        cfg = SootheConfig(router=ModelRouter(default="dashscope:qwen3.5-flash"))
        assert cfg.resolve_model("think") == "dashscope:qwen3.5-flash"

    def test_resolve_explicit_role(self):
        cfg = SootheConfig(
            router=ModelRouter(
                default="dashscope:qwen3.5-flash",
                think="idealab:glm-4.7",
            )
        )
        assert cfg.resolve_model("think") == "idealab:glm-4.7"
        assert cfg.resolve_model("default") == "dashscope:qwen3.5-flash"

    def test_resolve_all_roles(self):
        cfg = SootheConfig(
            router=ModelRouter(
                default="a:b",
                think="c:d",
                fast="e:f",
                image="g:h",
                embedding="i:j",
                web_search="k:l",
            )
        )
        assert cfg.resolve_model("default") == "a:b"
        assert cfg.resolve_model("think") == "c:d"
        assert cfg.resolve_model("fast") == "e:f"
        assert cfg.resolve_model("image") == "g:h"
        assert cfg.resolve_model("embedding") == "i:j"
        assert cfg.resolve_model("web_search") == "k:l"

    def test_unknown_role_fallback(self):
        cfg = SootheConfig(router=ModelRouter(default="test:model"))
        assert cfg.resolve_model("nonexistent") == "test:model"


class TestModelProvider:
    def test_find_provider(self):
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

    def test_find_provider_missing(self):
        cfg = SootheConfig()
        assert cfg._find_provider("nonexistent") is None


class TestResolveEnv:
    def test_env_var_substitution(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "resolved-value")
        assert _resolve_env("${MY_KEY}") == "resolved-value"

    def test_passthrough_literal(self):
        assert _resolve_env("literal-key") == "literal-key"

    def test_missing_env_returns_original(self, monkeypatch):
        monkeypatch.delenv("MISSING_KEY", raising=False)
        assert _resolve_env("${MISSING_KEY}") == "${MISSING_KEY}"

    def test_resolve_provider_env_success(self, monkeypatch):
        monkeypatch.setenv("MY_BASE_URL", "https://example.test/v1")
        assert (
            _resolve_provider_env(
                "${MY_BASE_URL}",
                provider_name="openai",
                field_name="api_base_url",
            )
            == "https://example.test/v1"
        )

    def test_resolve_provider_env_missing_raises(self, monkeypatch):
        monkeypatch.delenv("MISSING_PROVIDER_KEY", raising=False)
        try:
            _resolve_provider_env(
                "${MISSING_PROVIDER_KEY}",
                provider_name="dashscope",
                field_name="api_key",
            )
            assert False, "Expected unresolved env var to raise ValueError"
        except ValueError as exc:
            message = str(exc)
            assert "dashscope" in message
            assert "MISSING_PROVIDER_KEY" in message
            assert "providers[].api_key" in message


class TestPropagateEnv:
    def test_propagate_openai_provider(self, monkeypatch):
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

    def test_propagate_openai_provider_base_url_from_env(self, monkeypatch):
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

    def test_propagate_openai_provider_missing_api_key_env_raises(self, monkeypatch):
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
        try:
            cfg.propagate_env()
            assert False, "Expected unresolved API key env var to raise ValueError"
        except ValueError as exc:
            message = str(exc)
            assert "myopenai" in message
            assert "MISSING_OPENAI_KEY" in message
            assert "providers[].api_key" in message

    def test_provider_kwargs_base_url_env_substitution(self, monkeypatch):
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

    def test_provider_kwargs_missing_base_url_env_raises(self, monkeypatch):
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
        try:
            cfg._provider_kwargs("dashscope")
            assert False, "Expected unresolved base_url env var to raise ValueError"
        except ValueError as exc:
            message = str(exc)
            assert "dashscope" in message
            assert "MISSING_BASE_URL" in message
            assert "providers[].api_base_url" in message

    def test_no_propagate_non_openai(self, monkeypatch):
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

    def test_no_providers_no_propagate(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg = SootheConfig()
        cfg.propagate_env()
        import os

        assert "OPENAI_API_KEY" not in os.environ


class TestProtocolConfig:
    def test_context_backend_options(self):
        for backend in ("keyword", "vector", "none"):
            cfg = SootheConfig(context_backend=backend)
            assert cfg.context_backend == backend

    def test_memory_backend_options(self):
        for backend in ("keyword", "vector", "none"):
            cfg = SootheConfig(memory_backend=backend)
            assert cfg.memory_backend == backend

    def test_persist_backend_options(self):
        cfg = SootheConfig(
            context_persist_backend="rocksdb",
            memory_persist_backend="rocksdb",
        )
        assert cfg.context_persist_backend == "rocksdb"
        assert cfg.memory_persist_backend == "rocksdb"

    def test_vector_store_config(self):
        cfg = SootheConfig(
            vector_store_provider="pgvector",
            vector_store_collection="my_collection",
            vector_store_config={"dsn": "postgresql://localhost/test"},
        )
        assert cfg.vector_store_provider == "pgvector"
        assert cfg.vector_store_collection == "my_collection"
        assert cfg.vector_store_config["dsn"] == "postgresql://localhost/test"

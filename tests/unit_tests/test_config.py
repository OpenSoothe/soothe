"""Tests for SootheConfig."""

from soothe.config import (
    MCPServerConfig,
    ModelProviderConfig,
    ModelRouter,
    SootheConfig,
    SubagentConfig,
    _resolve_env,
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
        assert cfg.subagents["browser"].enabled is False
        assert cfg.subagents["claude"].enabled is False

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
        for backend in ("store", "vector", "none"):
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

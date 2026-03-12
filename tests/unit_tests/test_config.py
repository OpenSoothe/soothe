"""Tests for SootheConfig."""

from soothe.config import MCPServerConfig, SootheConfig, SubagentConfig


class TestSootheConfig:
    def test_defaults(self):
        cfg = SootheConfig()
        assert cfg.model is None
        assert cfg.llm_provider == "openai"
        assert cfg.llm_chat_model == "qwen3.5-flash"
        assert cfg.llm_api_key is None
        assert cfg.llm_base_url is None
        assert cfg.llm_vision_model is None
        assert cfg.debug is False
        assert cfg.tools == []
        assert cfg.mcp_servers == []
        assert cfg.skills == []
        assert cfg.memory == []

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


class TestResolveModelString:
    def test_explicit_model_takes_precedence(self):
        cfg = SootheConfig(model="anthropic:claude-sonnet-4-6")
        assert cfg.resolve_model_string() == "anthropic:claude-sonnet-4-6"

    def test_builds_from_provider_and_chat_model(self):
        cfg = SootheConfig(llm_provider="openai", llm_chat_model="gpt-4o")
        assert cfg.resolve_model_string() == "openai:gpt-4o"

    def test_default_resolution(self):
        cfg = SootheConfig()
        assert cfg.resolve_model_string() == "openai:qwen3.5-flash"

    def test_custom_provider(self):
        cfg = SootheConfig(llm_provider="google-genai", llm_chat_model="gemini-2.0-flash")
        assert cfg.resolve_model_string() == "google-genai:gemini-2.0-flash"


class TestPropagateEnv:
    def test_propagate_openai_env(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        cfg = SootheConfig(
            llm_provider="openai",
            llm_api_key="test-key",
            llm_base_url="https://test.example.com",
        )
        cfg.propagate_env()
        import os

        assert os.environ["OPENAI_API_KEY"] == "test-key"
        assert os.environ["OPENAI_BASE_URL"] == "https://test.example.com"

    def test_no_propagate_non_openai(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg = SootheConfig(
            llm_provider="anthropic",
            llm_api_key="test-key",
        )
        cfg.propagate_env()
        import os

        assert "OPENAI_API_KEY" not in os.environ

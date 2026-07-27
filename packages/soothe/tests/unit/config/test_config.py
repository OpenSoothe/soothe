"""Tests for SootheConfig."""

from pathlib import Path

import pytest
from support_config import config_with_router_profile as config_with_router

from soothe.config import (
    MCPServerConfig,
    ModelProviderConfig,
    ModelRouter,
    PersistenceConfig,
    SootheConfig,
    SubagentConfig,
    ToolsConfig,
    WebSearchConfig,
    _expand_env_in_config,
    _resolve_env,
    _resolve_provider_env,
)


class TestSootheConfig:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        cfg = SootheConfig()
        assert cfg.debug is False
        # Check that tools is a ToolsConfig instance
        assert isinstance(cfg.tools, ToolsConfig)
        # Check that default tools are enabled
        assert cfg.tools.execution.enabled is True
        assert cfg.tools.file_ops.enabled is True
        assert cfg.tools.datetime.enabled is True
        assert cfg.tools.data.enabled is True
        assert cfg.tools.wizsearch.enabled is True
        # Heavy optional tools are disabled by default (opt-in via config)
        assert cfg.tools.deepxiv.enabled is False
        assert cfg.mcp_servers == []
        assert cfg.mcp_builtins == []
        assert cfg.skills == []
        assert cfg.memory == []
        assert cfg.providers == []
        assert cfg.router.default == "openai:gpt-4o-mini"
        assert cfg.embedding_model == "openai:text-embedding-3-small"
        assert cfg.embedding_dims == 1536
        assert cfg.agent.autopilot.enabled is False
        assert cfg.agent.loop.dispatch_timeout_seconds == 0.0
        assert len(cfg.vector_stores) == 1
        assert cfg.vector_stores[0].name == "sqlite_vec_default"
        assert cfg.vector_store_router.default == "sqlite_vec_default:soothe_default"

    def test_yaml_with_daemon_top_level_block_is_rejected(self, tmp_path: Path) -> None:
        """Agent config rejects daemon-only top-level keys."""
        p = tmp_path / "cfg.yml"
        p.write_text(
            "agent:\n"
            "  name: TestDaemonStrip\n"
            "daemon:\n"
            "  event_size_stats_enabled: true\n"
            "  event_size_stats_interval_seconds: 90\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="daemon"):
            SootheConfig.from_yaml_file(str(p))

    def test_yaml_top_level_strange_loop_is_rejected(self, tmp_path: Path) -> None:
        """Top-level ``strange_loop`` is no longer accepted."""
        p = tmp_path / "cfg.yml"
        p.write_text(
            "agent:\n"
            "  name: NoFold\n"
            "strange_loop:\n"
            "  max_iterations: 42\n"
            "  concurrency:\n"
            "    max_parallel_steps: 7\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="strange_loop"):
            SootheConfig.from_yaml_file(str(p))

    def test_llm_rate_limit_enabled_by_default(self) -> None:
        cfg = SootheConfig()
        assert cfg.agent.loop.llm_rate_limit.enabled is True

    def test_checkpoint_defaults(self) -> None:
        cfg = SootheConfig()
        assert cfg.agent.loop.checkpoint.progressive is True
        assert cfg.agent.loop.checkpoint.auto_resume_on_start is False

    def test_default_subagents(self) -> None:
        cfg = SootheConfig()
        assert "planner" in cfg.subagents
        assert "explorer" not in cfg.subagents
        assert "deep_research" in cfg.subagents
        assert "academic_research" in cfg.subagents
        assert "browser_use" in cfg.subagents
        assert "skillify" not in cfg.subagents
        assert "claude" not in cfg.subagents
        assert "scout" not in cfg.subagents
        for name in ("planner", "deep_research", "academic_research"):
            assert cfg.subagents[name].enabled is True, f"{name} should be enabled by default"
        assert cfg.subagents["planner"].model_role == "think"
        assert cfg.subagents["planner"].endpoint is None
        assert cfg.subagents["browser_use"].enabled is True
        assert cfg.subagents["browser_use"].model_role == "default"

    def test_subagent_endpoint_accepts_legacy_url_key(self) -> None:
        cfg = SootheConfig(
            subagents={
                "custom_remote": {
                    "enabled": True,
                    "transport": "acp",
                    "url": "https://example.invalid/subagent",
                }
            }
        )
        assert cfg.subagents["custom_remote"].endpoint == "https://example.invalid/subagent"

    def test_default_skillify_config(self) -> None:
        cfg = SootheConfig()
        assert cfg.skillify.enabled is False
        assert cfg.skillify.model_role == "embedding"
        assert cfg.skillify.retrieval_top_k == 10

    def test_subagents_skillify_is_no_longer_rewritten(self) -> None:
        cfg = SootheConfig(
            subagents={
                "skillify": {
                    "enabled": False,
                    "config": {"retrieval_top_k": 5},
                }
            }
        )
        assert "skillify" in cfg.subagents
        assert cfg.subagents["skillify"].enabled is False
        assert cfg.skillify.enabled is False

    def test_legacy_claude_core_agent_fields_stripped(self) -> None:
        cfg = SootheConfig(
            agent={
                "core_agent_backend": "claude",
                "claude_permission_mode": "default",
                "claude_max_turns": 10,
                "claude_model": "claude-sonnet-4",
            }
        )
        dumped = cfg.agent.model_dump()
        assert "core_agent_backend" not in dumped
        assert "claude_permission_mode" not in dumped
        assert "claude_max_turns" not in dumped
        assert "claude_model" not in dumped

    def test_legacy_always_claude_routing_normalized(self) -> None:
        cfg = SootheConfig(agent={"protocols": {"planner": {"routing": "always_claude"}}})
        assert cfg.agent.protocols.planner.routing == "auto"

    def test_assistant_name_default(self) -> None:
        cfg = SootheConfig()
        assert cfg.agent.name == "Soothe"

    def test_general_purpose_subagent_disabled_by_sloop_default(self) -> None:
        cfg = SootheConfig()
        assert cfg.agent.loop.general_purpose_subagent is False
        assert cfg.agent.runtime.general_purpose_subagent is False

    def test_general_purpose_subagent_config_override(self) -> None:
        cfg = SootheConfig(agent={"loop": {"general_purpose_subagent": True}})
        assert cfg.agent.loop.general_purpose_subagent is True
        assert cfg.agent.runtime.general_purpose_subagent is True

    def test_core_agent_recursion_limit_default(self) -> None:
        cfg = SootheConfig()
        assert cfg.agent.runtime.recursion_limit == 9999

    def test_core_agent_recursion_limit_config_override(self) -> None:
        cfg = SootheConfig(agent={"runtime": {"recursion_limit": 300}})
        assert cfg.agent.runtime.recursion_limit == 300

    def test_resolve_system_prompt_default(self) -> None:
        cfg = SootheConfig()
        prompt = cfg.resolve_system_prompt()
        assert prompt.startswith("<ASSISTANT_IDENTITY>")
        assert "Soothe" in prompt
        assert "Never identify as Claude" in prompt

    def test_resolve_system_prompt_custom_name(self) -> None:
        cfg = SootheConfig(agent={"name": "MyBot"})
        prompt = cfg.resolve_system_prompt()
        assert prompt.startswith("<ASSISTANT_IDENTITY>")
        assert "MyBot" in prompt
        assert "Soothe" not in prompt

    def test_resolve_system_prompt_override(self) -> None:
        cfg = SootheConfig(agent={"system_prompt": "Custom prompt here"})
        result = cfg.resolve_system_prompt()
        assert result.startswith("<ASSISTANT_IDENTITY>")
        assert "Custom prompt here" in result
        assert "Today's date is" in result

    def test_default_system_prompt_does_not_nudge_read_instruction_files(self) -> None:
        """Builtin default body inlines AGENTS.md/CLAUDE.md on execute; no read-file nudge."""
        cfg = SootheConfig()
        prompt = cfg.resolve_system_prompt()

        assert "read and respect" not in prompt
        assert "MUST read" not in prompt
        assert "CLAUDE.md" not in prompt
        assert "AGENTS.md" not in prompt

    def test_planner_routing_default(self) -> None:
        cfg = SootheConfig()
        assert cfg.agent.protocols.planner.routing == "auto"

    def test_planner_routing_options(self) -> None:
        for routing in ("auto", "always_direct", "always_planner"):
            cfg = SootheConfig(agent={"protocols": {"planner": {"routing": routing}}})
            assert cfg.agent.protocols.planner.routing == routing

    def test_loop_plan_model_roles_default(self) -> None:
        cfg = SootheConfig()
        assert cfg.agent.loop.plan_assess_model_role == "fast"
        assert cfg.agent.loop.plan_gap_model_role == "fast"
        assert cfg.agent.loop.plan_generate_model_role == "think"
        assert cfg.agent.loop.goal_synthesis_model_role == "default"

    def test_loop_plan_model_roles_yaml(self) -> None:
        cfg = SootheConfig(
            agent={
                "loop": {
                    "plan_assess_model_role": "think",
                    "plan_gap_model_role": "default",
                    "plan_generate_model_role": "think",
                    "goal_synthesis_model_role": "fast",
                }
            }
        )
        assert cfg.agent.loop.plan_assess_model_role == "think"
        assert cfg.agent.loop.plan_gap_model_role == "default"
        assert cfg.agent.loop.plan_generate_model_role == "think"
        assert cfg.agent.loop.goal_synthesis_model_role == "fast"

    def test_verbosity_default(self) -> None:
        cfg = SootheConfig()
        assert cfg.logging.verbosity == "normal"

    def test_verbosity_options(self) -> None:
        for level in ("quiet", "normal", "debug"):
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
        assert cfg.logging.console.format == "%(level_short)s %(name)s %(message)s"

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
                "deep_research": SubagentConfig(enabled=False),
            }
        )
        assert cfg.subagents["scout"].enabled is True
        assert cfg.subagents["deep_research"].enabled is False

    def test_mcp_server_config_stdio(self) -> None:
        cfg = MCPServerConfig(name="my-server", command="npx", args=["-y", "@my/server"])
        assert cfg.transport == "stdio"
        assert cfg.command == "npx"
        assert cfg.args == ["-y", "@my/server"]

    def test_mcp_server_config_sse(self) -> None:
        cfg = MCPServerConfig(name="sse-server", url="https://example.com/sse", transport="sse")
        assert cfg.transport == "sse"
        assert cfg.url == "https://example.com/sse"

    def test_tools_list(self) -> None:
        # Tools config is now a ToolsConfig object, not a list
        cfg = SootheConfig()
        assert isinstance(cfg.tools, ToolsConfig)

    def test_skills_and_memory(self) -> None:
        cfg = SootheConfig(
            skills=["/skills/user/", "/skills/project/"],
            memory=["/memory/AGENTS.md"],
        )
        assert len(cfg.skills) == 2
        assert len(cfg.memory) == 1


class TestModelRouter:
    def test_resolve_default(self) -> None:
        cfg = config_with_router(ModelRouter(default="dashscope:qwen3.5-flash"))
        assert cfg.resolve_model("default") == "dashscope:qwen3.5-flash"

    def test_resolve_role_fallback(self) -> None:
        cfg = config_with_router(ModelRouter(default="dashscope:qwen3.5-flash"))
        assert cfg.resolve_model("think") == "dashscope:qwen3.5-flash"

    def test_resolve_explicit_role(self) -> None:
        cfg = config_with_router(
            ModelRouter(
                default="dashscope:qwen3.5-flash",
                think="idealab:glm-4.7",
            )
        )
        assert cfg.resolve_model("think") == "idealab:glm-4.7"
        assert cfg.resolve_model("default") == "dashscope:qwen3.5-flash"

    def test_resolve_all_roles(self) -> None:
        cfg = config_with_router(
            ModelRouter(
                default="a:b",
                think="c:d",
                fast="e:f",
                image="g:h",
                ocr="k:l",
            ),
            embedding_profile=[{"model_role": "i:j", "embedding_dims": 1536}],
        )
        assert cfg.resolve_model("default") == "a:b"
        assert cfg.resolve_model("think") == "c:d"
        assert cfg.resolve_model("fast") == "e:f"
        assert cfg.resolve_model("image") == "g:h"
        assert cfg.resolve_model("ocr") == "k:l"
        assert cfg.resolve_model("embedding") == "i:j"

    def test_unknown_role_fallback(self) -> None:
        cfg = config_with_router(ModelRouter(default="test:model"))
        assert cfg.resolve_model("nonexistent") == "test:model"  # type: ignore[arg-type]

    # Backend Inheritance Tests
    def test_resolve_backend_default_inheritance(self) -> None:
        """Test 'default' backend inherits from persistence.default_backend."""
        cfg = SootheConfig(
            persistence=PersistenceConfig(default_backend="postgresql"),
            agent={"protocols": {"durability": {"backend": "default"}}},
        )
        assert cfg.resolve_backend("default") == "postgresql"
        assert cfg.resolve_durability_backend() == "postgresql"

    def test_resolve_backend_explicit_override(self) -> None:
        """Test explicit backend overrides inheritance."""
        cfg = SootheConfig(
            persistence=PersistenceConfig(default_backend="postgresql"),
            agent={"protocols": {"durability": {"backend": "sqlite"}}},
        )
        assert cfg.resolve_backend("sqlite") == "sqlite"
        assert cfg.resolve_durability_backend() == "sqlite"

    def test_resolve_checkpointer_backend_inheritance(self) -> None:
        """Test checkpointer backend inheritance."""
        cfg = SootheConfig(
            persistence=PersistenceConfig(default_backend="postgresql"),
            agent={"protocols": {"durability": {"checkpointer": "default"}}},
        )
        assert cfg.resolve_checkpointer_backend() == "postgresql"

    def test_resolve_backend_concrete_values(self) -> None:
        """Test concrete backend values pass through unchanged."""
        cfg = SootheConfig(persistence=PersistenceConfig(default_backend="sqlite"))
        assert cfg.resolve_backend("postgresql") == "postgresql"
        assert cfg.resolve_backend("sqlite") == "sqlite"

    def test_persistence_postgres_pool_size_defaults(self) -> None:
        """Shared PostgreSQL pool defaults (PostgresPoolRegistry per-database budgets)."""
        p = PersistenceConfig(default_backend="postgresql")
        assert p.postgres.pool_min_size == 4
        assert p.postgres.checkpoints_pool_size == 32
        assert p.postgres.metadata_pool_size == 16
        assert p.postgres.vectors_pool_size == 16


class TestRouterProfiles:
    def test_active_profile_applies_router_and_embedding_dims(self) -> None:
        cfg = SootheConfig(
            router_profiles=[
                {
                    "name": "production",
                    "router": {
                        "default": "dashscope:glm-5.2",
                        "fast": "dashscope:kimi-k2.5",
                    },
                },
                {
                    "name": "local-deploy",
                    "router": {"default": "omlx:glm"},
                },
            ],
            embedding_profile=[
                {"model_role": "dashscope:multimodal-embedding-v1", "embedding_dims": 768}
            ],
            active_router_profile="production",
        )
        assert cfg.router.default == "dashscope:glm-5.2"
        assert cfg.router.fast == "dashscope:kimi-k2.5"
        assert cfg.resolve_model("embedding") == "dashscope:multimodal-embedding-v1"
        assert cfg.embedding_dims == 768
        assert cfg.resolve_model("fast") == "dashscope:kimi-k2.5"

    def test_active_profile_overrides_yaml_selection(self) -> None:
        cfg = SootheConfig(
            router_profiles=[
                {
                    "name": "cloud",
                    "router": {"default": "dashscope:glm-5.2"},
                },
                {
                    "name": "local",
                    "router": {"default": "omlx:glm"},
                },
            ],
            embedding_profile=[
                {"model_role": "openai:text-embedding-3-small", "embedding_dims": 384}
            ],
            active_router_profile="local",
        )
        assert cfg.router.default == "omlx:glm"
        assert cfg.embedding_dims == 384

    def test_legacy_flat_router_yaml_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "cfg.yml"
        p.write_text("router:\n  default: openai:gpt-4o-mini\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Top-level router removed"):
            SootheConfig.from_yaml_file(str(p))

    def test_legacy_embedding_dims_yaml_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "cfg.yml"
        p.write_text("embedding_dims: 1536\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Top-level embedding_dims removed"):
            SootheConfig.from_yaml_file(str(p))

    def test_legacy_router_profile_embedding_dims_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "cfg.yml"
        p.write_text(
            "router_profiles:\n"
            "  - name: legacy\n"
            "    router:\n"
            "      default: openai:gpt-4o-mini\n"
            "    embedding_dims: 1536\n"
            "embedding_profile:\n"
            "  - model_role: openai:text-embedding-3-small\n"
            "    embedding_dims: 1536\n",
            encoding="utf-8",
        )
        with pytest.raises(
            ValueError, match="router_profiles\\[\\]\\.embedding_dims has been removed"
        ):
            SootheConfig.from_yaml_file(str(p))

    def test_legacy_router_embedding_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "cfg.yml"
        p.write_text(
            "router_profiles:\n"
            "  - name: legacy\n"
            "    router:\n"
            "      default: openai:gpt-4o-mini\n"
            "      embedding: openai:text-embedding-3-small\n"
            "embedding_profile:\n"
            "  - model_role: openai:text-embedding-3-small\n"
            "    embedding_dims: 1536\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="router.embedding has been removed"):
            SootheConfig.from_yaml_file(str(p))

    def test_missing_active_profile_raises(self) -> None:
        with pytest.raises(ValueError, match="Router profile 'missing' not found"):
            SootheConfig(
                router_profiles=[{"name": "production", "router": {"default": "a:b"}}],
                active_router_profile="missing",
            )

    def test_duplicate_profile_names_raise(self) -> None:
        with pytest.raises(ValueError, match="Router profile names must be unique"):
            SootheConfig(
                router_profiles=[
                    {"name": "dup", "router": {"default": "a:b"}},
                    {"name": "dup", "router": {"default": "c:d"}},
                ],
            )

    def test_yaml_router_profiles_load(self, tmp_path: Path) -> None:
        p = tmp_path / "cfg.yml"
        p.write_text(
            "router_profiles:\n"
            "  - name: local\n"
            "    router:\n"
            "      default: omlx:test\n"
            "embedding_profile:\n"
            "  - model_role: omlx:embed\n"
            "    embedding_dims: 768\n"
            "active_router_profile: local\n",
            encoding="utf-8",
        )
        cfg = SootheConfig.from_yaml_file(str(p))
        assert cfg.router.default == "omlx:test"
        assert cfg.resolve_model("embedding") == "omlx:embed"
        assert cfg.embedding_dims == 768

    def test_env_overrides_yaml_active_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SOOTHE_ACTIVE_ROUTER_PROFILE", "local-deploy")
        cfg = SootheConfig(
            router_profiles=[
                {
                    "name": "production",
                    "router": {"default": "dashscope:glm-5.2"},
                },
                {
                    "name": "local-deploy",
                    "router": {"default": "omlx:glm"},
                },
            ],
            embedding_profile=[
                {"model_role": "openai:text-embedding-3-small", "embedding_dims": 384}
            ],
            active_router_profile="production",
        )
        assert cfg.active_router_profile == "local-deploy"
        assert cfg.router.default == "omlx:glm"
        assert cfg.embedding_dims == 384


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
        p = cfg.llm_factory._registry.get_provider("dashscope")  # noqa: SLF001
        assert p is not None
        assert p.name == "dashscope"
        assert p.api_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def test_find_provider_missing(self) -> None:
        cfg = SootheConfig()
        assert cfg.llm_factory._registry.get_provider("nonexistent") is None  # noqa: SLF001


class TestResolveEnv:
    def test_env_var_substitution(self, monkeypatch) -> None:
        monkeypatch.setenv("MY_KEY", "resolved-value")
        assert _resolve_env("${MY_KEY}") == "resolved-value"

    def test_passthrough_literal(self) -> None:
        assert _resolve_env("literal-key") == "literal-key"

    def test_missing_env_returns_original(self, monkeypatch) -> None:
        monkeypatch.delenv("MISSING_KEY", raising=False)
        assert _resolve_env("${MISSING_KEY}") == "${MISSING_KEY}"

    def test_embedded_env_var(self, monkeypatch) -> None:
        """Env var can be embedded within a larger string."""
        monkeypatch.setenv("HOME", "/Users/alice")
        assert _resolve_env("${HOME}/workspaces") == "/Users/alice/workspaces"

    def test_multiple_env_vars(self, monkeypatch) -> None:
        """Multiple env vars in one string are all resolved."""
        monkeypatch.setenv("VAR1", "foo")
        monkeypatch.setenv("VAR2", "bar")
        assert _resolve_env("${VAR1}/${VAR2}/path") == "foo/bar/path"

    def test_embedded_with_missing_var(self, monkeypatch) -> None:
        """Missing embedded var is left as placeholder."""
        monkeypatch.setenv("VAR1", "foo")
        monkeypatch.delenv("MISSING", raising=False)
        assert _resolve_env("${VAR1}/${MISSING}/path") == "foo/${MISSING}/path"

    def test_env_var_in_path_middle(self, monkeypatch) -> None:
        """Env var can appear anywhere in the path."""
        monkeypatch.setenv("USER", "alice")
        assert _resolve_env("/home/${USER}/.config") == "/home/alice/.config"

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


class TestExpandEnvInConfig:
    """Tests for recursive env var expansion throughout config tree."""

    def test_expand_simple_dict(self, monkeypatch) -> None:
        """Env vars in dict values are resolved."""
        monkeypatch.setenv("MY_KEY", "resolved")
        config = {"key": "${MY_KEY}", "other": "literal"}
        result = _expand_env_in_config(config)
        assert result["key"] == "resolved"
        assert result["other"] == "literal"

    def test_expand_nested_dict(self, monkeypatch) -> None:
        """Env vars in nested dict values are resolved."""
        monkeypatch.setenv("HOST_ROOT", "/host/workspaces")
        config = {"workspace_mount": {"host_root": "${HOST_ROOT}", "container_root": "/container"}}
        result = _expand_env_in_config(config)
        assert result["workspace_mount"]["host_root"] == "/host/workspaces"

    def test_expand_list_of_dicts(self, monkeypatch) -> None:
        """Env vars in list items are resolved."""
        monkeypatch.setenv("API_KEY", "secret123")
        config = {"providers": [{"name": "openai", "api_key": "${API_KEY}"}]}
        result = _expand_env_in_config(config)
        assert result["providers"][0]["api_key"] == "secret123"

    def test_expand_embedded_in_nested_path(self, monkeypatch) -> None:
        """Env vars embedded in path strings throughout config are resolved."""
        monkeypatch.setenv("HOME", "/Users/alice")
        monkeypatch.setenv("PROJECT", "myproject")
        config = {
            "workspace_mount": {
                "host_root": "${HOME}/workspaces/${PROJECT}",
                "container_root": "/workspaces",
            },
            "filesystem_middleware": {"workspace_root": "${HOME}/projects"},
        }
        result = _expand_env_in_config(config)
        assert result["workspace_mount"]["host_root"] == "/Users/alice/workspaces/myproject"
        assert result["filesystem_middleware"]["workspace_root"] == "/Users/alice/projects"

    def test_expand_preserves_scalars(self) -> None:
        """Int, bool, None pass through unchanged."""
        config = {"count": 42, "enabled": True, "name": None}
        result = _expand_env_in_config(config)
        assert result["count"] == 42
        assert result["enabled"] is True
        assert result["name"] is None

    def test_expand_mixed_list(self, monkeypatch) -> None:
        """List with mixed types resolves strings only."""
        monkeypatch.setenv("VAR", "resolved")
        config = ["${VAR}", 42, True, None, "literal"]
        result = _expand_env_in_config(config)
        assert result[0] == "resolved"
        assert result[1] == 42
        assert result[2] is True
        assert result[3] is None
        assert result[4] == "literal"


class TestYamlEnvExpansion:
    """Tests for env var expansion when loading from YAML files."""

    def test_yaml_embedded_env_var(self, tmp_path: Path, monkeypatch) -> None:
        """Env vars embedded in YAML path strings are resolved."""
        monkeypatch.setenv("HOST_ROOT", "/host/workspaces")
        p = tmp_path / "cfg.yml"
        p.write_text(
            "workspace_mount:\n  host_root: ${HOST_ROOT}/subdir\n  container_root: /workspaces\n",
            encoding="utf-8",
        )
        cfg = SootheConfig.from_yaml_file(str(p))
        assert cfg.workspace_mount.host_root == "/host/workspaces/subdir"
        assert cfg.workspace_mount.container_root == "/workspaces"

    def test_yaml_multiple_env_vars(self, tmp_path: Path, monkeypatch) -> None:
        """Multiple env vars in one YAML value are resolved."""
        monkeypatch.setenv("VAR1", "foo")
        monkeypatch.setenv("VAR2", "bar")
        p = tmp_path / "cfg.yml"
        p.write_text(
            "filesystem_middleware:\n  workspace_root: ${VAR1}/${VAR2}/workspace\n",
            encoding="utf-8",
        )
        cfg = SootheConfig.from_yaml_file(str(p))
        assert cfg.filesystem_middleware.workspace_root == "foo/bar/workspace"

    def test_yaml_env_in_nested_mcp_auth(self, tmp_path: Path, monkeypatch) -> None:
        """Env vars in deeply nested MCP auth headers are resolved."""
        monkeypatch.setenv("LINEAR_TOKEN", "secret-token-123")
        p = tmp_path / "cfg.yml"
        p.write_text(
            "mcp_servers:\n"
            "  - name: linear\n"
            "    transport: streamable_http\n"
            "    url: https://mcp.linear.app/sse\n"
            "    auth:\n"
            "      headers:\n"
            "        Authorization: Bearer ${LINEAR_TOKEN}\n",
            encoding="utf-8",
        )
        cfg = SootheConfig.from_yaml_file(str(p))
        assert len(cfg.mcp_servers) == 1
        assert cfg.mcp_servers[0].auth.headers["Authorization"] == "Bearer secret-token-123"

    def test_yaml_missing_env_var_left_as_placeholder(self, tmp_path: Path, monkeypatch) -> None:
        """Missing env vars are left as placeholders and fail validation or produce warnings."""
        monkeypatch.delenv("MISSING_VAR", raising=False)
        p = tmp_path / "cfg.yml"
        p.write_text(
            "workspace_mount:\n  host_root: ${MISSING_VAR}\n  container_root: /workspaces\n",
            encoding="utf-8",
        )
        # Should still load, but with placeholder
        cfg = SootheConfig.from_yaml_file(str(p))
        assert cfg.workspace_mount.host_root == "${MISSING_VAR}"

    def test_yaml_env_in_provider_config(self, tmp_path: Path, monkeypatch) -> None:
        """Env vars in provider config are expanded before Pydantic validation."""
        monkeypatch.setenv("OPENAI_KEY", "sk-test-123")
        monkeypatch.setenv("OPENAI_BASE", "https://proxy.example.com/v1")
        p = tmp_path / "cfg.yml"
        p.write_text(
            "providers:\n"
            "  - name: openai\n"
            "    provider_type: openai\n"
            "    api_key: ${OPENAI_KEY}\n"
            "    api_base_url: ${OPENAI_BASE}\n"
            "    models: [gpt-4o]\n",
            encoding="utf-8",
        )
        cfg = SootheConfig.from_yaml_file(str(p))
        assert len(cfg.providers) == 1
        assert cfg.providers[0].api_key == "sk-test-123"
        assert cfg.providers[0].api_base_url == "https://proxy.example.com/v1"


class TestPropagateEnv:
    def test_propagate_openai_provider_standard_endpoint(self, monkeypatch) -> None:
        """Standard OpenAI endpoint (no custom base_url) sets OPENAI_* env vars."""
        # Pre-set via monkeypatch so propagate_env's setdefault is a no-op
        # and the env var is auto-cleaned at test teardown (prevents env leakage).
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        cfg = SootheConfig(
            providers=[
                ModelProviderConfig(
                    name="openai",
                    api_key="test-key",
                    provider_type="openai",
                    # No api_base_url = standard OpenAI endpoint
                ),
            ]
        )
        cfg.propagate_env()
        import os

        assert os.environ["OPENAI_API_KEY"] == "test-key"
        # OPENAI_BASE_URL should not be set for standard endpoint
        assert "OPENAI_BASE_URL" not in os.environ

    def test_propagate_openai_provider_explicit_standard_endpoint(self, monkeypatch) -> None:
        """Explicit standard OpenAI endpoint sets OPENAI_* env vars."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        cfg = SootheConfig(
            providers=[
                ModelProviderConfig(
                    name="openai",
                    api_base_url="https://api.openai.com/v1",
                    api_key="test-key",
                    provider_type="openai",
                ),
            ]
        )
        cfg.propagate_env()
        import os

        assert os.environ["OPENAI_API_KEY"] == "test-key"
        # Explicit api.openai.com URL should still set OPENAI_BASE_URL
        assert os.environ["OPENAI_BASE_URL"] == "https://api.openai.com/v1"

    def test_propagate_custom_endpoint_no_env_vars(self, monkeypatch) -> None:
        """Custom OpenAI-compatible endpoint should NOT set OPENAI_* env vars."""
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

        # Custom endpoint should NOT set OPENAI_* env vars
        assert "OPENAI_API_KEY" not in os.environ
        assert "OPENAI_BASE_URL" not in os.environ

    def test_propagate_custom_endpoint_from_env_no_env_vars(self, monkeypatch) -> None:
        """Custom OpenAI-compatible endpoint from env var should NOT set OPENAI_* env vars."""
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

        # Custom endpoint should NOT set OPENAI_* env vars
        assert "OPENAI_API_KEY" not in os.environ
        assert "OPENAI_BASE_URL" not in os.environ

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
        provider_type, kwargs = cfg.llm_factory._registry.get_provider_kwargs("dashscope")  # noqa: SLF001
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
            provider_type, kwargs = cfg.llm_factory._registry.get_provider_kwargs("dashscope")  # noqa: SLF001
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
        cfg = SootheConfig(agent={"protocols": {"memory": {"enabled": False}}})
        assert cfg.agent.protocols.memory.enabled is False

        cfg = SootheConfig(agent={"protocols": {"memory": {"enabled": True}}})
        assert cfg.agent.protocols.memory.enabled is True

        # Test persist_dir option
        cfg = SootheConfig(agent={"protocols": {"memory": {"persist_dir": "/custom/memory/dir"}}})
        assert cfg.agent.protocols.memory.persist_dir == "/custom/memory/dir"

        # Test LLM role configuration
        cfg = SootheConfig(
            agent={
                "protocols": {"memory": {"llm_chat_role": "fast", "llm_embed_role": "embedding"}}
            }
        )
        assert cfg.agent.protocols.memory.llm_chat_role == "fast"
        assert cfg.agent.protocols.memory.llm_embed_role == "embedding"

    def test_combined_backend_options(self) -> None:
        """Test combined backend format for memory."""
        cfg = SootheConfig(
            agent={
                "protocols": {
                    "memory": {"persist_dir": "/custom/memory/dir"},
                }
            }
        )
        assert cfg.agent.protocols.memory.persist_dir == "/custom/memory/dir"

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

    def test_resolve_vector_store_role_falls_back_to_default(self) -> None:
        """Unknown roles inherit ``vector_store_router.default`` (sqlite_vec bootstrap)."""
        cfg = SootheConfig()
        assert cfg.resolve_vector_store_role("unknown_role") == "sqlite_vec_default:soothe_default"

    def test_resolve_vector_store_role_no_default(self) -> None:
        """When default is unset, unknown roles resolve to None."""
        cfg = SootheConfig(vector_store_router={"default": None})
        assert cfg.resolve_vector_store_role("unknown_role") is None

    def test_vector_store_instance_caching(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that vector store instances are cached."""
        from unittest.mock import MagicMock

        mock_create = MagicMock()
        monkeypatch.setattr("soothe_nano.backends.vector_store.create_vector_store", mock_create)

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
        monkeypatch.setattr("soothe_nano.backends.vector_store.create_vector_store", mock_create)

        cfg.create_vector_store_for_role("my_role")
        call_kwargs = mock_create.call_args[0][2]
        assert call_kwargs["dsn"] == "postgresql://user:pass@host:5432/db"

    def test_pgvector_dsn_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that pgvector DSN is required (no fallback)."""
        from unittest.mock import MagicMock

        mock_create = MagicMock()
        monkeypatch.setattr("soothe_nano.backends.vector_store.create_vector_store", mock_create)

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
        monkeypatch.setattr("soothe_nano.backends.vector_store.create_vector_store", mock_create)

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
        assert hasattr(cfg.tools, "wizsearch")
        assert isinstance(cfg.tools.wizsearch, WebSearchConfig)

    def test_web_search_default_engines(self) -> None:
        """Test that wizsearch default_engines defaults to ['tavily']."""
        cfg = SootheConfig()
        assert cfg.tools.wizsearch.default_engines == ["tavily"]
        assert cfg.tools.wizsearch.max_results_per_engine == 10
        assert cfg.tools.wizsearch.timeout == 30
        assert cfg.tools.wizsearch.enabled is True
        assert cfg.tools.wizsearch.proxy is None

    def test_web_search_custom_config(self) -> None:
        """Test wizsearch with custom configuration."""
        cfg = SootheConfig(
            tools=ToolsConfig(
                wizsearch=WebSearchConfig(
                    enabled=True,
                    default_engines=["tavily"],
                    max_results_per_engine=15,
                    timeout=45,
                    proxy="http://127.0.0.1:7890",
                )
            )
        )
        assert cfg.tools.wizsearch.enabled is True
        assert cfg.tools.wizsearch.default_engines == ["tavily"]
        assert cfg.tools.wizsearch.max_results_per_engine == 15
        assert cfg.tools.wizsearch.timeout == 45
        assert cfg.tools.wizsearch.proxy == "http://127.0.0.1:7890"

    def test_web_search_config_from_dict(self) -> None:
        """Test wizsearch config from dict."""
        cfg = SootheConfig(
            tools={
                "wizsearch": {
                    "enabled": True,
                    "default_engines": ["brave", "tavily"],
                    "max_results_per_engine": 20,
                    "timeout": 60,
                    "proxy": "http://127.0.0.1:7890",
                }
            }
        )
        assert cfg.tools.wizsearch.enabled is True
        assert cfg.tools.wizsearch.default_engines == ["brave", "tavily"]
        assert cfg.tools.wizsearch.max_results_per_engine == 20
        assert cfg.tools.wizsearch.timeout == 60
        assert cfg.tools.wizsearch.proxy == "http://127.0.0.1:7890"

    def test_web_search_partial_config(self) -> None:
        """Test wizsearch with partial configuration."""
        cfg = SootheConfig(
            tools={
                "wizsearch": {
                    "default_engines": ["duckduckgo"],
                }
            }
        )
        # Custom value
        assert cfg.tools.wizsearch.default_engines == ["duckduckgo"]
        # Defaults preserved
        assert cfg.tools.wizsearch.max_results_per_engine == 10
        assert cfg.tools.wizsearch.timeout == 30
        assert cfg.tools.wizsearch.enabled is True

    def test_resolve_persistence_postgres_dsn_prefers_soothe_dsn(self) -> None:
        cfg = SootheConfig(
            persistence={
                "soothe_postgres_dsn": "postgresql://localhost/soothe_new",
            }
        )
        assert cfg.resolve_persistence_postgres_dsn() == "postgresql://localhost/soothe_new"


class TestEnvProviderBootstrap:
    def test_bootstrap_openai_provider_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        cfg = SootheConfig()
        assert len(cfg.providers) == 1
        assert cfg.providers[0].name == "openai"
        assert cfg.providers[0].api_key == "sk-test-openai"
        assert cfg.router.default == "openai:gpt-4o-mini"

    def test_bootstrap_openai_with_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
        cfg = SootheConfig()
        assert cfg.providers[0].api_base_url == "http://localhost:1234/v1"

    def test_bootstrap_anthropic_provider_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        cfg = SootheConfig()
        assert len(cfg.providers) == 1
        assert cfg.providers[0].name == "anthropic"
        assert cfg.router.default == "anthropic:claude-sonnet-4-20250514"

    def test_bootstrap_skipped_when_yaml_providers_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")
        cfg = SootheConfig(providers=[ModelProviderConfig(name="custom", api_key="yaml-key")])
        assert len(cfg.providers) == 1
        assert cfg.providers[0].name == "custom"
        assert cfg.providers[0].api_key == "yaml-key"

    def test_openai_takes_priority_over_anthropic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        cfg = SootheConfig()
        assert cfg.providers[0].name == "openai"

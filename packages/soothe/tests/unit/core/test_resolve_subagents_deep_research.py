"""Regression: deep_research subagent must receive SootheConfig and context from resolver."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from soothe.config import SootheConfig, SubagentConfig
from soothe.runner.resolver._resolver_tools import resolve_subagents


def test_resolve_subagents_passes_config_and_context_to_deep_research() -> None:
    """Deep Research factory must receive config and work_dir context, not spread YAML options."""
    cfg = SootheConfig()
    for name in cfg.subagents:
        cfg.subagents[name] = SubagentConfig(enabled=(name == "deep_research"))

    fake_model = MagicMock()
    inner_runnable = MagicMock()
    inner_runnable.invoke.return_value = {"messages": []}

    def _fake_call(factory, kwargs):
        return {
            "name": "deep_research",
            "description": "deep_research",
            "runnable": inner_runnable,
        }

    with (
        patch(
            "soothe.config.settings.SootheConfig.create_chat_model",
            return_value=fake_model,
        ),
        patch(
            "soothe.plugin.global_registry.is_plugins_loaded",
            return_value=False,
        ),
        patch(
            "soothe.runner.resolver._resolver_tools._call_subagent_factory",
            side_effect=_fake_call,
        ) as factory_mock,
    ):
        specs = resolve_subagents(cfg, lazy=False)

        assert len(specs) == 1
        spec = specs[0]
        assert spec.get("name") == "deep_research"
        factory_mock.assert_not_called()

        spec["runnable"].invoke({"messages": []})
        factory_mock.assert_called_once()
        _factory, kwargs = factory_mock.call_args[0]
        assert kwargs["config"] is cfg
        assert "work_dir" in kwargs["context"]


def test_resolve_subagents_deep_research_uses_explicit_model_spec() -> None:
    cfg = SootheConfig()
    cfg.subagents["deep_research"] = SubagentConfig(
        enabled=True,
        model="dashscope:kimi-k2.5",
    )
    for name in cfg.subagents:
        if name != "deep_research":
            cfg.subagents[name] = SubagentConfig(enabled=False)

    spec_model = MagicMock(name="spec-model")

    with (
        patch(
            "soothe.config.settings.SootheConfig.create_chat_model_for_spec",
            return_value=spec_model,
        ) as create_for_spec,
        patch(
            "soothe.config.settings.SootheConfig.create_chat_model",
        ) as create_model,
        patch(
            "soothe.plugin.global_registry.is_plugins_loaded",
            return_value=False,
        ),
    ):
        resolve_subagents(cfg, lazy=False)

    create_for_spec.assert_called_once_with("dashscope:kimi-k2.5")
    create_model.assert_not_called()

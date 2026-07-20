"""Regression: planner subagent model resolution via ``model_role`` or explicit spec."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from soothe.config import SootheConfig, SubagentConfig
from soothe.runner.resolver._resolver_tools import resolve_subagents


def test_resolve_subagents_planner_uses_model_role() -> None:
    cfg = SootheConfig(
        router_profiles=[
            {
                "name": "production",
                "router": {
                    "default": "dashscope:glm-5.2",
                    "fast": "dashscope:kimi-k2.5",
                    "think": "dashscope:glm-5",
                },
            }
        ],
        active_router_profile="production",
    )
    cfg.subagents["planner"] = SubagentConfig(enabled=True, model_role="fast")
    for name in cfg.subagents:
        if name != "planner":
            cfg.subagents[name] = SubagentConfig(enabled=False)

    fast_model = MagicMock(name="fast-model")
    inner_runnable = MagicMock()
    inner_runnable.invoke.return_value = {"messages": []}

    def _fake_call(factory, kwargs):
        assert kwargs["model"] is fast_model
        assert kwargs["config"] is cfg
        return {
            "name": "planner",
            "description": "planner",
            "runnable": inner_runnable,
        }

    with (
        patch(
            "soothe.config.settings.SootheConfig.create_chat_model",
            return_value=fast_model,
        ) as create_model,
        patch(
            "soothe_nano.plugin.global_registry.is_plugins_loaded",
            return_value=False,
        ),
        patch(
            "soothe.runner.resolver._resolver_tools._call_subagent_factory",
            side_effect=_fake_call,
        ) as factory_mock,
    ):
        specs = resolve_subagents(cfg, lazy=False)
        assert len(specs) == 1
        create_model.assert_called_once_with("fast")
        factory_mock.assert_not_called()

        specs[0]["runnable"].invoke({"messages": []})
        factory_mock.assert_called_once()


def test_resolve_subagents_planner_defaults_to_think_role() -> None:
    cfg = SootheConfig()
    cfg.subagents["planner"] = SubagentConfig(enabled=True)
    for name in cfg.subagents:
        if name != "planner":
            cfg.subagents[name] = SubagentConfig(enabled=False)

    think_model = MagicMock(name="think-model")

    with (
        patch(
            "soothe.config.settings.SootheConfig.create_chat_model",
            return_value=think_model,
        ) as create_model,
        patch(
            "soothe_nano.plugin.global_registry.is_plugins_loaded",
            return_value=False,
        ),
    ):
        resolve_subagents(cfg, lazy=False)

    create_model.assert_called_once_with("think")


def test_resolve_subagents_planner_uses_explicit_model_spec() -> None:
    cfg = SootheConfig()
    cfg.subagents["planner"] = SubagentConfig(
        enabled=True,
        model="dashscope:glm-5",
        model_role="fast",
    )
    for name in cfg.subagents:
        if name != "planner":
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
            "soothe_nano.plugin.global_registry.is_plugins_loaded",
            return_value=False,
        ),
    ):
        resolve_subagents(cfg, lazy=False)

    create_for_spec.assert_called_once_with("dashscope:glm-5")
    create_model.assert_not_called()

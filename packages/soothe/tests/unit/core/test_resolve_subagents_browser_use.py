"""Regression: browser_use subagent resolves model via ``model_role``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from soothe_nano.resolve._resolver_tools import resolve_subagents

from soothe.config import SootheConfig, SubagentConfig


def test_resolve_subagents_browser_use_passes_soothe_config_not_model() -> None:
    cfg = SootheConfig(
        router_profiles=[
            {
                "name": "production",
                "router": {
                    "default": "dashscope:glm-5.2",
                    "fast": "dashscope:kimi-k2.5",
                },
            }
        ],
        active_router_profile="production",
    )
    cfg.subagents["browser_use"] = SubagentConfig(enabled=True, model_role="fast")
    for name in cfg.subagents:
        if name != "browser_use":
            cfg.subagents[name] = SubagentConfig(enabled=False)

    fake_factory = MagicMock()
    fake_factory.__self__ = MagicMock(manifest=MagicMock(name="browser_use"))

    def _fake_call(factory, kwargs):
        assert kwargs["config"] is cfg
        assert kwargs.get("model") is None
        return {
            "name": "browser_use",
            "description": "browser",
            "runnable": MagicMock(),
        }

    with (
        patch(
            "soothe_nano.plugin.global_registry.is_plugins_loaded",
            return_value=True,
        ),
        patch(
            "soothe_nano.plugin.global_registry.get_plugin_registry",
        ) as registry_mock,
        patch(
            "soothe_nano.resolve._resolver_tools._call_subagent_factory",
            side_effect=_fake_call,
        ) as factory_mock,
    ):
        registry = registry_mock.return_value
        registry.get_subagent_factory.return_value = fake_factory

        specs = resolve_subagents(cfg, lazy=False)

        assert len(specs) == 1
        assert specs[0].get("name") == "browser_use"
        factory_mock.assert_not_called()

        specs[0]["runnable"].invoke({"messages": []})
        factory_mock.assert_called_once()


def test_resolve_subagents_browser_use_fallback_passes_soothe_config_not_model() -> None:
    """Built-in factory fallback must receive soothe_config, not model."""
    cfg = SootheConfig()
    for name in cfg.subagents:
        cfg.subagents[name] = SubagentConfig(enabled=(name == "browser_use"))

    inner_runnable = MagicMock()
    inner_runnable.invoke.return_value = {"messages": []}

    def _fake_call(factory, kwargs):
        assert "model" not in kwargs
        assert kwargs["soothe_config"] is cfg
        return {
            "name": "browser_use",
            "description": "browser",
            "runnable": inner_runnable,
        }

    with (
        patch(
            "soothe_nano.plugin.global_registry.is_plugins_loaded",
            return_value=False,
        ),
        patch(
            "soothe_nano.resolve._resolver_tools._call_subagent_factory",
            side_effect=_fake_call,
        ) as factory_mock,
    ):
        specs = resolve_subagents(cfg, lazy=False)

        assert len(specs) == 1
        assert specs[0].get("name") == "browser_use"
        factory_mock.assert_not_called()

        specs[0]["runnable"].invoke({"messages": []})
        factory_mock.assert_called_once()


def test_call_subagent_factory_browser_use_plugin_accepts_model_none() -> None:
    """Regression: @subagent wrapper requires model kwarg even when unused."""
    from soothe_nano.resolve._resolver_tools import _call_subagent_factory
    from soothe_nano.subagents.browser_use import BrowserUsePlugin

    cfg = SootheConfig()
    plugin = BrowserUsePlugin()
    spec = _call_subagent_factory(
        plugin.create_browser_use,
        {"model": None, "config": cfg, "context": None},
    )
    assert spec["name"] == "browser_use"
    assert spec.get("runnable") is not None

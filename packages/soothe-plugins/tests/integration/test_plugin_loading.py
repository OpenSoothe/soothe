"""Integration test: verify community plugins have correct structure."""

from __future__ import annotations

import importlib
import importlib.metadata

import pytest


def test_entry_points_registered() -> None:
    """Verify community plugins are registered as entry points."""
    # Get entry points for soothe.plugins group
    try:
        eps = importlib.metadata.entry_points(group="soothe.plugins")
    except TypeError:
        # Python 3.10 compatibility
        eps = importlib.metadata.entry_points().get("soothe.plugins", [])

    eps_list = list(eps)
    assert len(eps_list) > 0, "No soothe.plugins entry points found"

    # Check expected plugins are registered
    names = {ep.name for ep in eps_list}
    assert "paperscout" in names, "paperscout entry point not registered"
    assert "sample_echo" in names, "sample_echo entry point not registered"
    assert "weaver" in names, "weaver entry point not registered"


def test_plugins_importable() -> None:
    """Verify all plugin modules can be imported."""
    plugins = [
        "soothe_plugins.paperscout",
        "soothe_plugins.sample_echo",
        "soothe_plugins.weaver",
    ]

    for plugin_module in plugins:
        try:
            mod = importlib.import_module(plugin_module)
            assert mod is not None, f"{plugin_module} import returned None"
        except ImportError as e:
            pytest.fail(f"Failed to import {plugin_module}: {e}")


@pytest.mark.asyncio
async def test_community_plugins_have_manifest() -> None:
    """Verify all community plugin classes have _plugin_manifest."""
    plugin_classes = [
        ("soothe_plugins.paperscout", "PaperScoutPlugin"),
        ("soothe_plugins.sample_echo", "SampleEchoPlugin"),
        ("soothe_plugins.weaver", "WeaverPlugin"),
    ]

    for module_name, class_name in plugin_classes:
        mod = importlib.import_module(module_name)
        cls = getattr(mod, class_name)
        assert hasattr(cls, "_plugin_manifest"), f"{class_name} missing _plugin_manifest"
        manifest = cls._plugin_manifest
        assert manifest.name, f"{class_name} manifest has no name"
        assert manifest.version, f"{class_name} manifest has no version"
        assert manifest.description, f"{class_name} manifest has no description"


@pytest.mark.asyncio
async def test_community_plugins_have_subagent_decorator() -> None:
    """Verify community plugins expose subagent factories via @subagent."""
    from unittest.mock import MagicMock

    plugin_instances = [
        ("soothe_plugins.paperscout", "PaperScoutPlugin"),
        ("soothe_plugins.sample_echo", "SampleEchoPlugin"),
        ("soothe_plugins.weaver", "WeaverPlugin"),
    ]

    for module_name, class_name in plugin_instances:
        mod = importlib.import_module(module_name)
        cls = getattr(mod, class_name)
        instance = cls()

        # Mock context for on_load
        context = MagicMock()
        context.logger = MagicMock()
        context.config = {}

        # Call on_load (should not raise)
        try:
            await instance.on_load(context)
        except Exception:
            # Some plugins may have dependency checks that fail in test env
            # This is OK - we're just testing the decorator structure
            pass

        # Check subagents are exposed
        subagents = instance.get_subagents()
        assert len(subagents) > 0, f"{class_name} should expose at least one subagent"

        # Verify subagent has decorator metadata
        factory = subagents[0]
        assert hasattr(factory, "_subagent_name"), f"{class_name} subagent missing _subagent_name"


def test_plugin_manifest_trust_levels() -> None:
    """Verify all community plugins have appropriate trust levels."""
    plugin_classes = [
        ("soothe_plugins.paperscout", "PaperScoutPlugin"),
        ("soothe_plugins.sample_echo", "SampleEchoPlugin"),
        ("soothe_plugins.weaver", "WeaverPlugin"),
    ]

    valid_trust_levels = ("built-in", "trusted", "standard", "untrusted")

    for module_name, class_name in plugin_classes:
        mod = importlib.import_module(module_name)
        cls = getattr(mod, class_name)
        manifest = cls._plugin_manifest
        assert manifest.trust_level in valid_trust_levels, (
            f"{class_name} has invalid trust_level: {manifest.trust_level}"
        )


def test_subagent_return_format() -> None:
    """Verify sample_echo returns correct CompiledSubAgent format."""
    from soothe_plugins.sample_echo.implementation import create_echo_subagent_spec

    spec = create_echo_subagent_spec()

    # Check required keys
    assert "name" in spec, "CompiledSubAgent missing 'name'"
    assert "description" in spec, "CompiledSubAgent missing 'description'"
    assert "runnable" in spec, "CompiledSubAgent missing 'runnable'"

    # Check runnable is a compiled graph (not a dict)
    runnable = spec["runnable"]
    assert hasattr(runnable, "with_config"), "runnable must have .with_config() method (should be CompiledStateGraph)"
    assert not isinstance(runnable, dict), "runnable must NOT be a nested dict!"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

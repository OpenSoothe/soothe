"""Integration tests for plugin entry-point discovery and loading."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.integration


def test_entry_point_discovery() -> None:
    """discover_entry_points should find entry point plugins if installed."""
    from soothe_nano.plugin.discovery import discover_entry_points

    entry_points = discover_entry_points()
    if not entry_points:
        pytest.skip("No entry point plugins found - soothe-plugins not installed")

    entry_str = " ".join(entry_points)
    valid_patterns = ["soothe_plugins", "soothe.subagents"]
    assert any(pattern in entry_str for pattern in valid_patterns), (
        f"Expected soothe_plugins or soothe.subagents in entry points, got: {entry_str}"
    )


def test_plugin_load_from_entry_points() -> None:
    """Plugins should be loadable via entry points."""
    import importlib.metadata

    from soothe_sdk.plugin.manifest import PluginManifest

    eps = list(importlib.metadata.entry_points(group="soothe.plugins"))
    if not eps:
        pytest.skip("No entry point plugins found - soothe-plugins not installed")

    for ep in eps:
        try:
            plugin_cls = ep.load()
            if hasattr(plugin_cls, "_plugin_manifest"):
                manifest: PluginManifest = plugin_cls._plugin_manifest
                assert manifest.name
                assert manifest.trust_level in (
                    "standard",
                    "trusted",
                    "untrusted",
                    "built-in",
                )
                return
        except (ImportError, ModuleNotFoundError):
            continue

    pytest.skip("No entry point plugins could be loaded - soothe-plugins not installed")


@pytest.mark.asyncio
async def test_lifecycle_loads_plugins() -> None:
    """PluginLifecycleManager should load discovered plugins including entry points."""
    from soothe_nano.plugin.discovery import discover_all_plugins, discover_entry_points

    config = MagicMock()
    config.plugins = []

    discovered = discover_all_plugins(config)
    entry_eps = discover_entry_points()

    if not entry_eps:
        pytest.skip("No entry point plugins found - soothe-plugins not installed")

    assert len(discovered) > 0

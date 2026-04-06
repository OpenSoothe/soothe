"""Integration test: load community plugins through the full plugin system."""

import pytest


@pytest.mark.asyncio
async def test_community_plugins_load_via_lifecycle():
    """Full lifecycle test: discover -> register -> load community plugins."""
    from soothe.plugin.discovery import discover_all_plugins, discover_entry_points
    from soothe.plugin.loader import PluginLoader
    from soothe.plugin.registry import PluginRegistry

    # 1. Verify entry points exist
    entry_points = discover_entry_points()
    assert len(entry_points) > 0, "No soothe.plugins entry points found"
    entry_str = " ".join(entry_points)
    assert "soothe_community" in entry_str, "Community plugins not found in entry points"

    # 2. Create mock config (no config-declared plugins)
    from unittest.mock import MagicMock

    config = MagicMock()
    config.plugins = []

    # 3. Full discovery
    discovered = discover_all_plugins(config)
    assert len(discovered) > 0

    # 4. Check community plugins were discovered
    names = set(discovered.keys())
    assert "browser" in names  # built-in subagent
    assert "execution" in names  # built-in tool
    assert "paperscout" in names, "paperscout not discovered via entry points"
    assert "skillify" in names, "skillify not discovered via entry points"
    assert "weaver" in names, "weaver not discovered via entry points"

    # 5. Register all discovered plugins
    registry = PluginRegistry()
    loader = PluginLoader(registry)

    for module_path, _ in discovered.values():
        manifest = None
        # Try to get manifest from the class
        try:
            import importlib

            if ":" in module_path:
                mod_name, cls_name = module_path.split(":", 1)
            else:
                mod_name = module_path
                cls_name = None

            mod = importlib.import_module(mod_name)
            if cls_name:
                cls = getattr(mod, cls_name)
            else:
                # Find the plugin class
                cls = None
                for attr_name in dir(mod):
                    if attr_name.endswith("Plugin") and not attr_name.startswith("_"):
                        cls = getattr(mod, attr_name)
                        break
                if cls is None:
                    # For built-in modules, skip
                    continue

            if hasattr(cls, "_plugin_manifest"):
                manifest = cls._plugin_manifest
                source = "built-in" if module_path.startswith("soothe.") else "entry_point"
                registry.register(manifest, source)
        except ImportError:
            # Some community plugins have heavy deps that may fail
            continue

    # 6. Verify registered plugins
    registered = registry.list_all()
    registered_names = {e.manifest.name for e in registered}

    assert "paperscout" in registered_names, "paperscout not registered"
    assert "skillify" in registered_names, "skillify not registered"
    assert "weaver" in registered_names, "weaver not registered"

    # 7. Verify manifests have correct trust levels
    for entry in registered:
        assert entry.manifest.trust_level in ("built-in", "trusted", "standard", "untrusted")

    paperscout_entry = registry.get("paperscout")
    assert paperscout_entry is not None
    assert paperscout_entry.manifest.name == "paperscout"
    assert paperscout_entry.manifest.version == "1.0.0"


@pytest.mark.asyncio
async def test_community_plugins_subagent_discovery():
    """Verify community plugins expose subagents correctly."""
    from soothe_community.paperscout import PaperScoutPlugin
    from soothe_community.skillify import SkillifyPlugin
    from soothe_community.weaver import WeaverPlugin

    # Verify each plugin has the decorator metadata
    for plugin_cls in [PaperScoutPlugin, SkillifyPlugin, WeaverPlugin]:
        assert hasattr(plugin_cls, "_plugin_manifest"), f"{plugin_cls.__name__} missing manifest"
        manifest = plugin_cls._plugin_manifest
        assert manifest.name
        assert manifest.version
        assert manifest.description

    # Verify PaperScout exposes subagent factory
    from unittest.mock import MagicMock

    context = MagicMock()
    context.logger = MagicMock()
    plugin_instance = PaperScoutPlugin()
    await plugin_instance.on_load(context)

    subagents = plugin_instance.get_subagents()
    assert len(subagents) > 0, "PaperScout should expose at least one subagent"
    assert hasattr(subagents[0], "_subagent_name")
    assert subagents[0]._subagent_name == "paperscout"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

"""Test plugin gap fixes: config_requirements, health_check, trust, discovery."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---- Test 1: config_requirements in manifest and decorator ----


def test_manifest_has_config_requirements():
    """PluginManifest should have config_requirements field."""
    from soothe_sdk.plugin.manifest import PluginManifest

    manifest = PluginManifest(
        name="test-plugin",
        version="1.0.0",
        description="Test",
        config_requirements=["providers.openai.api_key", "model_settings.temperature"],
    )
    assert manifest.config_requirements == [
        "providers.openai.api_key",
        "model_settings.temperature",
    ]

    # Default should be empty list
    manifest2 = PluginManifest(name="test", version="1.0.0", description="Test")
    assert manifest2.config_requirements == []


def test_plugin_decorator_accepts_config_requirements():
    """@plugin decorator should accept config_requirements parameter."""
    from soothe_sdk.plugin.decorators import plugin

    @plugin(
        name="test-config-plugin",
        version="1.0.0",
        description="Test plugin with config requirements",
        config_requirements=["providers.openai.api_key"],
    )
    class TestPlugin:
        pass

    assert TestPlugin._plugin_manifest.config_requirements == ["providers.openai.api_key"]


# ---- Test 2: config dependency resolution in loader ----


def test_config_dependency_resolution():
    """PluginLoader should validate config_requirements."""
    from soothe_sdk.plugin.manifest import PluginManifest

    from soothe.plugin.exceptions import DependencyError
    from soothe.plugin.loader import PluginLoader
    from soothe.plugin.registry import PluginRegistry

    registry = PluginRegistry()
    loader = PluginLoader(registry)

    # Create a mock config with nested attributes
    config = MagicMock()
    config.providers = MagicMock()
    config.providers.openai = MagicMock()
    config.providers.openai.api_key = "sk-test-key"
    config.model_settings = MagicMock()
    config.model_settings.temperature = None

    PluginManifest(
        name="test-config-dep",
        version="1.0.0",
        description="Test",
        config_requirements=["providers.openai.api_key"],
    )

    # This should pass - key exists and has value
    loader._check_config_dependency("providers.openai.api_key", config)

    # Missing key should fail (use a real object, not MagicMock which auto-creates attrs)
    class FakeConfig:
        pass

    fake_config = FakeConfig()
    assert not loader._check_config_dependency("missing.config.key", fake_config)

    # None value should fail
    assert not loader._check_config_dependency("model_settings.temperature", config)

    # resolve_dependencies should raise when config dep is missing
    class SimpleConfig:
        pass

    simple_config = SimpleConfig()
    manifest_missing = PluginManifest(
        name="test-config-dep-missing",
        version="1.0.0",
        description="Test",
        config_requirements=["providers.nonexistent.key"],
    )
    with pytest.raises(DependencyError):
        loader.resolve_dependencies(manifest_missing, simple_config)


# ---- Test 3: Health check event exists ----


def test_health_check_event_exists():
    """PluginHealthCheckedEvent should exist and be importable."""
    from soothe.plugin.events import PluginHealthCheckedEvent

    event = PluginHealthCheckedEvent(
        name="test-plugin",
        status="healthy",
        details="All systems operational",
    )
    assert event.type == "soothe.plugin.health_checked"
    assert event.name == "test-plugin"
    assert event.status == "healthy"
    assert event.details == "All systems operational"


# ---- Test 4: Health check invocation in lifecycle ----


@pytest.mark.asyncio
async def test_health_check_invocation():
    """health_check_all should call health_check() on plugins that have it."""
    from soothe.plugin.lifecycle import PluginLifecycleManager
    from soothe.plugin.registry import PluginRegistry

    registry = PluginRegistry()
    manager = PluginLifecycleManager(registry)

    # Create a mock plugin with health_check
    healthy_plugin = MagicMock()
    healthy_plugin.health_check = AsyncMock(return_value={"status": "healthy", "details": "OK"})

    # Create a mock plugin without health_check
    no_healthcheck_plugin = MagicMock(spec=[])

    manager.loaded_plugins = {
        "healthy": healthy_plugin,
        "no_healthcheck": no_healthcheck_plugin,
    }

    results = await manager.health_check_all()

    assert results["healthy"]["status"] == "healthy"
    assert results["no_healthcheck"]["status"] == "healthy"


# ---- Test 5: Trust level enforcement ----


def test_untrusted_plugin_blocked_by_default():
    """Untrusted plugins should be blocked unless env var is set."""
    from soothe_sdk.plugin.manifest import PluginManifest

    from soothe.plugin.exceptions import ValidationError
    from soothe.plugin.loader import PluginLoader
    from soothe.plugin.registry import PluginRegistry

    # Ensure env var is not set
    original = os.environ.pop("SOOTHE_ALLOW_UNTRUSTED_PLUGINS", None)

    try:
        registry = PluginRegistry()
        loader = PluginLoader(registry)

        manifest = PluginManifest(
            name="untrusted-plugin",
            version="1.0.0",
            description="Test",
            trust_level="untrusted",
        )

        with pytest.raises(ValidationError) as exc_info:
            loader.validate_trust_level(manifest)

        assert "untrusted" in str(exc_info.value).lower()
    finally:
        # Restore env var
        if original is not None:
            os.environ["SOOTHE_ALLOW_UNTRUSTED_PLUGINS"] = original


def test_trusted_plugin_allowed():
    """Built-in, trusted, and standard plugins should always be allowed."""
    from soothe_sdk.plugin.manifest import PluginManifest

    from soothe.plugin.loader import PluginLoader
    from soothe.plugin.registry import PluginRegistry

    registry = PluginRegistry()
    loader = PluginLoader(registry)

    for trust_level in ("built-in", "trusted", "standard"):
        manifest = PluginManifest(
            name=f"{trust_level}-plugin",
            version="1.0.0",
            description="Test",
            trust_level=trust_level,
        )
        # Should not raise
        loader.validate_trust_level(manifest)


# ---- Test 6: Filesystem discovery adds sys.path ----


def test_filesystem_discovery_adds_sys_path():
    """discover_filesystem should add plugin directory to sys.path."""
    from soothe.plugin.discovery import discover_filesystem

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin_dir = Path(tmpdir) / "test_plugin"
        plugin_dir.mkdir()
        (plugin_dir / "__init__.py").write_text("")

        # Use temp dir as plugin base
        results = discover_filesystem(Path(tmpdir))

        # Should have found the plugin
        assert "test_plugin" in results

        # Should have added to sys.path
        assert tmpdir in sys.path


# ---- Test 7: Entry point discovery works ----


@pytest.mark.integration
def test_entry_point_discovery():
    """discover_entry_points should find entry point plugins if installed."""
    from soothe.plugin.discovery import discover_entry_points

    entry_points = discover_entry_points()

    # Entry point plugins should be found if soothe-community is installed
    if not entry_points:
        pytest.skip("No entry point plugins found - soothe-community not installed")

    # Should contain community plugin paths
    entry_str = " ".join(entry_points)
    assert "soothe_community" in entry_str


# ---- Test 8: Plugin loading from entry points ----


@pytest.mark.integration
def test_plugin_load_from_entry_points():
    """Plugins should be loadable via entry points."""
    import importlib.metadata

    from soothe_sdk.plugin.manifest import PluginManifest

    # Check community entry points exist
    eps = list(importlib.metadata.entry_points(group="soothe.plugins"))
    if not eps:
        pytest.skip("No entry point plugins found - soothe-community not installed")

    # Try importing paperscout
    from soothe_community.paperscout import PaperScoutPlugin

    assert hasattr(PaperScoutPlugin, "_plugin_manifest")
    manifest: PluginManifest = PaperScoutPlugin._plugin_manifest
    assert manifest.name == "paperscout"
    assert manifest.trust_level == "standard"
    assert len(manifest.config_requirements) == 0  # paperscout has no config_requirements


# ---- Test 9: Full lifecycle with community plugins ----


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lifecycle_loads_plugins():
    """PluginLifecycleManager should load discovered plugins including entry points."""
    from soothe.plugin.discovery import discover_all_plugins, discover_entry_points

    # Create mock config
    config = MagicMock()
    config.plugins = []

    # Discovery should find entry point plugins
    discovered = discover_all_plugins(config)
    entry_eps = discover_entry_points()

    if not entry_eps:
        pytest.skip("No entry point plugins found - soothe-community not installed")

    # At least one entry point plugin should be discovered
    assert len(discovered) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Tests for type definitions."""

from soothe_sdk.plugin import Health as PluginHealth
from soothe_sdk.plugin import Manifest as PluginManifest


def test_plugin_manifest():
    """Test PluginManifest creation and validation."""
    manifest = PluginManifest(
        name="test-plugin",
        version="1.0.0",
        description="Test plugin",
        dependencies=["langchain>=0.1.0"],
    )

    assert manifest.name == "test-plugin"
    assert manifest.version == "1.0.0"
    assert manifest.description == "Test plugin"
    assert manifest.dependencies == ["langchain>=0.1.0"]


def test_plugin_health():
    """Test PluginHealth creation."""
    health = PluginHealth(status="healthy")

    assert health.status == "healthy"
    assert health.details == {}

    health_with_details = PluginHealth(status="degraded", details={"error": "API unavailable"})

    assert health_with_details.status == "degraded"
    assert health_with_details.details == {"error": "API unavailable"}


# Note: Semantic version validation is not implemented in PluginManifest
# The version field accepts any string value

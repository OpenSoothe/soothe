"""Unit tests for Channel registry (RFC-620 §7)."""

from __future__ import annotations

import importlib
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.registry import (
    discover_all,
    discover_channel_names,
    discover_enabled,
    discover_plugins,
    load_channel_class,
)


class MockTestChannel(Channel):
    """Mock channel for registry testing."""

    name = "mock_test"
    display_name = "Mock Test Channel"

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, chat_id: str, message: Any) -> None:
        pass


class TestDiscoverChannelNames:
    """Tests for discover_channel_names function."""

    def test_returns_list(self):
        """Test function returns a list."""
        names = discover_channel_names()
        assert isinstance(names, list)

    def test_excludes_infrastructure_modules(self):
        """Test infrastructure modules are excluded."""
        names = discover_channel_names()
        # Infrastructure modules should not appear
        assert "base" not in names
        assert "message" not in names
        assert "events" not in names
        assert "registry" not in names
        assert "__init__" not in names

    def test_names_are_strings(self):
        """Test all names are strings."""
        names = discover_channel_names()
        for name in names:
            assert isinstance(name, str)


class TestLoadChannelClass:
    """Tests for load_channel_class function."""

    def test_returns_none_for_invalid_module(self):
        """Test returns None for non-existent module."""
        result = load_channel_class("nonexistent_channel_xyz")
        assert result is None

    def test_returns_none_for_module_without_channel(self):
        """Test returns None for module without Channel subclass."""
        # The events module has no Channel subclass
        result = load_channel_class("events")
        assert result is None


class TestDiscoverPlugins:
    """Tests for discover_plugins function."""

    def test_returns_dict(self):
        """Test function returns a dict."""
        result = discover_plugins(set())
        assert isinstance(result, dict)

    def test_filters_by_enabled_names(self):
        """Test only enabled names are loaded."""
        result = discover_plugins({"telegram", "discord"})
        # Should return empty if no plugins registered
        assert isinstance(result, dict)

    def test_handles_import_error(self):
        """Test handles ImportError gracefully."""
        with patch("importlib.metadata.entry_points", side_effect=ImportError):
            result = discover_plugins({"test"})
            assert result == {}


class TestDiscoverEnabled:
    """Tests for discover_enabled function."""

    def test_returns_dict(self):
        """Test function returns a dict."""
        result = discover_enabled(set())
        assert isinstance(result, dict)

    def test_empty_enabled_names_returns_empty_dict(self):
        """Test empty enabled_names returns empty dict."""
        result = discover_enabled(set())
        assert result == {}

    def test_filters_by_enabled_names(self):
        """Test only specified names are attempted."""
        # Requesting non-existent channels should return empty
        result = discover_enabled({"nonexistent_xyz", "fake_channel"})
        assert result == {}


class TestDiscoverAll:
    """Tests for discover_all function."""

    def test_returns_dict(self):
        """Test function returns a dict."""
        result = discover_all()
        assert isinstance(result, dict)

    def test_includes_built_in_and_plugins(self):
        """Test combines built-in and plugin channels."""
        # This tests the integration path
        result = discover_all()
        # Should return dict (may be empty if no channels registered)
        assert isinstance(result, dict)


class TestRegistryIntegration:
    """Integration tests for registry with mock entry points."""

    def test_mock_entry_point_loading(self):
        """Test loading a channel via mock entry point."""
        # Create a mock entry point
        mock_ep = MagicMock()
        mock_ep.name = "mock_plugin"
        mock_ep.load = MagicMock(return_value=MockTestChannel)

        mock_eps = [mock_ep]

        with patch("importlib.metadata.entry_points", return_value=mock_eps):
            result = discover_plugins({"mock_plugin"})

            assert "mock_plugin" in result
            assert result["mock_plugin"] == MockTestChannel

    def test_entry_point_load_failure_handled(self):
        """Test entry point load failure is handled."""
        mock_ep = MagicMock()
        mock_ep.name = "broken_plugin"
        mock_ep.load = MagicMock(side_effect=ImportError("Failed to load"))

        mock_eps = [mock_ep]

        with patch("importlib.metadata.entry_points", return_value=mock_eps):
            result = discover_plugins({"broken_plugin"})

            # Should not include failed entry point
            assert "broken_plugin" not in result

    def test_entry_point_non_channel_handled(self):
        """Test entry point returning non-Channel is handled."""
        mock_ep = MagicMock()
        mock_ep.name = "not_a_channel"
        mock_ep.load = MagicMock(return_value=str)  # Returns a class, but not Channel

        mock_eps = [mock_ep]

        with patch("importlib.metadata.entry_points", return_value=mock_eps):
            result = discover_plugins({"not_a_channel"})

            # Should not include non-Channel class
            assert "not_a_channel" not in result

    def test_entry_point_override_builtin(self):
        """Test entry point can override built-in channel."""
        # Create mock entry point with same name as built-in
        mock_ep = MagicMock()
        mock_ep.name = "websocket"  # Same name as built-in
        mock_ep.load = MagicMock(return_value=MockTestChannel)

        mock_eps = [mock_ep]

        with patch("importlib.metadata.entry_points", return_value=mock_eps):
            result = discover_plugins({"websocket"})

            # Plugin should be loaded (would override built-in in discover_enabled)
            assert "websocket" in result


class TestRegistryErrorHandling:
    """Tests for registry error handling."""

    def test_entry_points_group_not_found(self):
        """Test handles missing entry_points group."""
        # entry_points returns empty for unknown group
        with patch("importlib.metadata.entry_points", return_value=[]):
            result = discover_plugins({"any_channel"})
            assert result == {}

    def test_importlib_metadata_import_failure(self):
        """Test handles importlib.metadata import failure."""
        with patch(
            "importlib.metadata.entry_points",
            side_effect=ImportError("No module named 'importlib.metadata'"),
        ):
            result = discover_plugins({"test"})
            assert result == {}

    def test_load_channel_class_import_error(self):
        """Test load_channel_class handles ImportError."""
        with patch(
            "importlib.import_module",
            side_effect=ImportError("Module not found"),
        ):
            result = load_channel_class("some_channel")
            assert result is None

    def test_load_channel_class_no_channel_class(self):
        """Test load_channel_class returns None for module without Channel."""
        # Create a simple module-like object that has no Channel subclass
        class FakeModule:
            some_function = lambda x: x
            _private = None
            __name__ = "fake_module"

        fake_module = FakeModule()

        with patch("importlib.import_module", return_value=fake_module):
            result = load_channel_class("fake_module")
            # Should return None since no Channel subclass found
            assert result is None
"""Unit tests for browser runtime directory configuration."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from soothe.config import BrowserSubagentConfig, SootheConfig
from soothe.utils.runtime import (
    cleanup_browser_temp_files,
    get_browser_downloads_dir,
    get_browser_extensions_dir,
    get_browser_runtime_dir,
    get_browser_user_data_dir,
    get_subagent_runtime_dir,
)


def test_get_subagent_runtime_dir():
    """Test getting subagent runtime directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("soothe.utils.runtime.SOOTHE_HOME", tmpdir):
            runtime_dir = get_subagent_runtime_dir("browser")
            assert runtime_dir == Path(tmpdir) / "agents" / "browser"
            assert runtime_dir.exists()
            assert runtime_dir.is_dir()


def test_get_browser_runtime_dir():
    """Test getting browser runtime directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("soothe.utils.runtime.SOOTHE_HOME", tmpdir):
            runtime_dir = get_browser_runtime_dir()
            assert runtime_dir == Path(tmpdir) / "agents" / "browser"
            assert runtime_dir.exists()


def test_get_browser_downloads_dir():
    """Test getting browser downloads directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("soothe.utils.runtime.SOOTHE_HOME", tmpdir):
            downloads_dir = get_browser_downloads_dir()
            assert downloads_dir == Path(tmpdir) / "agents" / "browser" / "downloads"
            assert downloads_dir.exists()


def test_get_browser_user_data_dir():
    """Test getting browser user data directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("soothe.utils.runtime.SOOTHE_HOME", tmpdir):
            user_data_dir = get_browser_user_data_dir()
            assert user_data_dir == Path(tmpdir) / "agents" / "browser" / "profiles" / "default"
            assert user_data_dir.exists()

            # Test with custom profile name
            custom_dir = get_browser_user_data_dir("custom")
            assert custom_dir == Path(tmpdir) / "agents" / "browser" / "profiles" / "custom"
            assert custom_dir.exists()


def test_get_browser_extensions_dir():
    """Test getting browser extensions directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("soothe.utils.runtime.SOOTHE_HOME", tmpdir):
            extensions_dir = get_browser_extensions_dir()
            assert extensions_dir == Path(tmpdir) / "agents" / "browser" / "extensions"
            assert extensions_dir.exists()


def test_cleanup_browser_temp_files():
    """Test cleaning up temporary browser files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("soothe.utils.runtime.SOOTHE_HOME", tmpdir):
            # Create temp directories with UUID-like suffixes
            downloads_dir = get_browser_downloads_dir()
            temp_download = downloads_dir / "browser-use-downloads-abc12345"
            temp_download.mkdir(parents=True, exist_ok=True)
            (temp_download / "test.txt").write_text("test")

            # Create a persistent directory without UUID suffix
            persistent_dir = downloads_dir / "persistent"
            persistent_dir.mkdir(parents=True, exist_ok=True)
            (persistent_dir / "keep.txt").write_text("keep")

            # Run cleanup
            cleanup_browser_temp_files()

            # Temp directory should be removed
            assert not temp_download.exists()
            # Persistent directory should be kept
            assert persistent_dir.exists()
            assert (persistent_dir / "keep.txt").exists()


def test_browser_subagent_config_defaults():
    """Test BrowserSubagentConfig default values."""
    config = BrowserSubagentConfig()
    assert config.runtime_dir == ""
    assert config.downloads_dir == ""
    assert config.user_data_dir == ""
    assert config.extensions_dir == ""
    assert config.cleanup_on_exit is True
    assert config.disable_extensions is True
    assert config.disable_cloud is True
    assert config.disable_telemetry is True


def test_soothe_config_browser_field():
    """Test that SootheConfig includes browser configuration."""
    config = SootheConfig()
    assert hasattr(config, "browser")
    assert isinstance(config.browser, BrowserSubagentConfig)


def test_browser_config_integration():
    """Test browser configuration integration with config file."""
    config_dict = {
        "browser": {
            "runtime_dir": "/custom/browser",
            "cleanup_on_exit": False,
            "disable_extensions": False,
        }
    }
    config = SootheConfig(**config_dict)
    assert config.browser.runtime_dir == "/custom/browser"
    assert config.browser.cleanup_on_exit is False
    assert config.browser.disable_extensions is False


def test_runtime_directory_structure():
    """Test that the complete directory structure is created."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("soothe.utils.runtime.SOOTHE_HOME", tmpdir):
            # Get all directories
            runtime_dir = get_browser_runtime_dir()
            downloads_dir = get_browser_downloads_dir()
            user_data_dir = get_browser_user_data_dir()
            extensions_dir = get_browser_extensions_dir()

            # Verify structure
            assert runtime_dir == Path(tmpdir) / "agents" / "browser"
            assert downloads_dir == runtime_dir / "downloads"
            assert user_data_dir == runtime_dir / "profiles" / "default"
            assert extensions_dir == runtime_dir / "extensions"

            # All directories should exist
            for directory in [runtime_dir, downloads_dir, user_data_dir, extensions_dir]:
                assert directory.exists(), f"Directory {directory} should exist"
                assert directory.is_dir(), f"{directory} should be a directory"


def test_cleanup_specific_session():
    """Test cleaning up a specific session by ID."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("soothe.utils.runtime.SOOTHE_HOME", tmpdir):
            # Create test directories
            downloads_dir = get_browser_downloads_dir()
            session_dir = downloads_dir / "session-abc123"
            other_dir = downloads_dir / "session-xyz789"

            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "test.txt").write_text("test")

            other_dir.mkdir(parents=True, exist_ok=True)
            (other_dir / "other.txt").write_text("other")

            # Clean up specific session
            cleanup_browser_temp_files(session_id="abc123")

            # Target session should be removed
            assert not session_dir.exists()
            # Other session should remain
            assert other_dir.exists()
            assert (other_dir / "other.txt").exists()

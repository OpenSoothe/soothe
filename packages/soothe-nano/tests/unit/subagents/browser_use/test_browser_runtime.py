"""Unit tests for browser runtime directory configuration.

Uses local _runtime module (no soothe daemon dependency).
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import soothe_nano.subagents.browser_use._runtime as browser_runtime
from soothe_nano.subagents.browser_use._runtime import (
    cleanup_browser_temp_files,
    cleanup_stale_chrome,
    get_browser_downloads_dir,
    get_browser_extensions_dir,
    get_browser_runtime_dir,
    get_browser_user_data_dir,
)
from soothe_nano.subagents.browser_use.config_model import BrowserUseSubagentConfig


def _isolated_soothe_home():
    """Patch browser runtime to use an isolated SOOTHE_HOME directory."""
    return patch.object(
        browser_runtime,
        "SOOTHE_HOME",
        Path(tempfile.mkdtemp()),
    )


def test_get_browser_runtime_dir() -> None:
    """Test getting browser runtime directory."""
    with _isolated_soothe_home():
        runtime_dir = get_browser_runtime_dir()
        assert runtime_dir.name == "browser"
        assert runtime_dir.parent.name == "agents"
        assert runtime_dir.exists()


def test_get_browser_downloads_dir() -> None:
    """Test getting browser downloads directory."""
    with _isolated_soothe_home():
        downloads_dir = get_browser_downloads_dir()
        assert downloads_dir.name == "downloads"
        assert downloads_dir.exists()


def test_get_browser_user_data_dir() -> None:
    """Test getting browser user data directory."""
    with _isolated_soothe_home():
        user_data_dir = get_browser_user_data_dir()
        assert user_data_dir.name == "default"
        assert user_data_dir.parent.name == "profiles"
        assert user_data_dir.exists()

        # Test with custom profile name
        custom_dir = get_browser_user_data_dir("custom")
        assert custom_dir.name == "custom"
        assert custom_dir.exists()


def test_get_browser_extensions_dir() -> None:
    """Test getting browser extensions directory."""
    with _isolated_soothe_home():
        extensions_dir = get_browser_extensions_dir()
        assert extensions_dir.name == "extensions"
        assert extensions_dir.exists()


def test_cleanup_browser_temp_files() -> None:
    """Test cleaning up temporary browser files."""
    with _isolated_soothe_home():
        # Create temp directories
        downloads_dir = get_browser_downloads_dir()
        temp_download = downloads_dir / "browser-use-downloads-abc12345"
        temp_download.mkdir(parents=True, exist_ok=True)
        (temp_download / "test.txt").write_text("test")

        # Run cleanup - cleans everything in downloads
        cleaned = cleanup_browser_temp_files()

        # Temp directory should be removed
        assert not temp_download.exists()
        # Should report cleaned files
        assert cleaned >= 1


def test_browser_use_subagent_config_defaults() -> None:
    """Test BrowserUseSubagentConfig default values."""
    config = BrowserUseSubagentConfig()
    assert config.max_steps == 10
    assert config.runtime_dir == ""
    assert config.downloads_dir == ""
    assert config.user_data_dir == ""
    assert config.extensions_dir == ""
    assert config.cleanup_on_exit is True
    assert config.disable_extensions is True
    assert config.disable_cloud is True
    assert config.disable_telemetry is True
    assert config.synthesis_role == "default"
    assert config.synthesis_timeout_sec == 30.0


def test_browser_use_config_from_dict() -> None:
    """Test browser_use configuration from dict."""
    config_dict = {
        "runtime_dir": "/custom/browser",
        "cleanup_on_exit": False,
        "disable_extensions": False,
    }
    browser_config = BrowserUseSubagentConfig(**config_dict)
    assert browser_config.runtime_dir == "/custom/browser"
    assert browser_config.cleanup_on_exit is False
    assert browser_config.disable_extensions is False


def test_runtime_directory_structure() -> None:
    """Test that the complete directory structure is created."""
    with _isolated_soothe_home():
        # Get all directories
        runtime_dir = get_browser_runtime_dir()
        downloads_dir = get_browser_downloads_dir()
        user_data_dir = get_browser_user_data_dir()
        extensions_dir = get_browser_extensions_dir()

        # Verify structure
        assert downloads_dir.parent == runtime_dir
        assert user_data_dir.parent.parent == runtime_dir
        assert extensions_dir.parent == runtime_dir

        # All directories should exist
        for directory in [runtime_dir, downloads_dir, user_data_dir, extensions_dir]:
            assert directory.exists(), f"Directory {directory} should exist"
            assert directory.is_dir(), f"{directory} should be a directory"


def test_cleanup_stale_chrome_no_processes() -> None:
    """Test cleanup_stale_chrome when no matching processes."""
    with _isolated_soothe_home():
        # Should return 0 when no processes match
        killed = cleanup_stale_chrome("/nonexistent/profile")
        assert killed == 0

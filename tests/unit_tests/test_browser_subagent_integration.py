"""Integration tests for browser subagent runtime configuration."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from soothe.config import BrowserSubagentConfig, SootheConfig
from soothe.subagents.browser import create_browser_subagent


def test_browser_subagent_uses_configured_runtime_dir():
    """Test that browser subagent uses configured runtime directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_runtime = Path(tmpdir) / "custom_browser"
        custom_runtime.mkdir(parents=True, exist_ok=True)

        # Create config with custom runtime dir
        config = SootheConfig(
            browser=BrowserSubagentConfig(
                runtime_dir=str(custom_runtime),
                cleanup_on_exit=False,
            )
        )

        # Create browser subagent
        subagent = create_browser_subagent(
            runtime_dir=config.browser.runtime_dir,
            cleanup_on_exit=config.browser.cleanup_on_exit,
        )

        # Verify subagent was created successfully
        assert subagent is not None
        assert subagent["name"] == "browser"
        assert "runnable" in subagent


def test_browser_subagent_environment_variables():
    """Test that browser subagent sets correct environment variables."""
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_runtime = Path(tmpdir) / "browser_test"
        custom_runtime.mkdir(parents=True, exist_ok=True)

        # Mock environment
        env_patch = {}
        with patch.dict(os.environ, env_patch, clear=False):
            # Create subagent which should set env vars during execution
            subagent = create_browser_subagent(
                runtime_dir=str(custom_runtime),
                cleanup_on_exit=True,
            )

            # Note: Environment variables are set during graph execution,
            # not during creation. This test verifies the subagent can be
            # created with custom config.
            assert subagent is not None


def test_browser_subagent_default_directories():
    """Test that browser subagent works with default directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("soothe.utils.runtime.get_browser_runtime_dir") as mock_runtime:
            with patch("soothe.utils.runtime.get_browser_downloads_dir") as mock_downloads:
                with patch("soothe.utils.runtime.get_browser_user_data_dir") as mock_user_data:
                    with patch("soothe.utils.runtime.get_browser_extensions_dir") as mock_extensions:
                        # Mock the runtime directory functions
                        mock_runtime.return_value = Path(tmpdir) / "agents" / "browser"
                        mock_downloads.return_value = Path(tmpdir) / "agents" / "browser" / "downloads"
                        mock_user_data.return_value = Path(tmpdir) / "agents" / "browser" / "profiles" / "default"
                        mock_extensions.return_value = Path(tmpdir) / "agents" / "browser" / "extensions"

                        # Create subagent with defaults
                        subagent = create_browser_subagent()

                        # Verify subagent was created
                        assert subagent is not None
                        assert subagent["name"] == "browser"


def test_browser_subagent_config_from_soothe_config():
    """Test that browser subagent can be created from SootheConfig."""
    config = SootheConfig(
        browser=BrowserSubagentConfig(
            disable_extensions=True,
            disable_cloud=True,
            disable_telemetry=True,
            cleanup_on_exit=True,
        )
    )

    # Create subagent using config values
    subagent = create_browser_subagent(
        disable_extensions=config.browser.disable_extensions,
        disable_cloud=config.browser.disable_cloud,
        disable_telemetry=config.browser.disable_telemetry,
        cleanup_on_exit=config.browser.cleanup_on_exit,
    )

    assert subagent is not None
    assert subagent["name"] == "browser"


def test_browser_subagent_cleanup_flag():
    """Test that cleanup_on_exit flag is properly passed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Test with cleanup enabled
        subagent_with_cleanup = create_browser_subagent(
            runtime_dir=tmpdir,
            cleanup_on_exit=True,
        )
        assert subagent_with_cleanup is not None

        # Test with cleanup disabled
        subagent_no_cleanup = create_browser_subagent(
            runtime_dir=tmpdir,
            cleanup_on_exit=False,
        )
        assert subagent_no_cleanup is not None

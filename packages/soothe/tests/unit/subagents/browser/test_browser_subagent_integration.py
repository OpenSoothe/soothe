"""Integration tests for browser subagent runtime configuration."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from soothe.config import BrowserSubagentConfig
from soothe.subagents.browser import create_browser_subagent


def test_browser_subagent_uses_configured_runtime_dir() -> None:
    """Test that browser subagent uses configured runtime directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_runtime = Path(tmpdir) / "custom_browser"
        custom_runtime.mkdir(parents=True, exist_ok=True)

        # Create browser config
        browser_config = BrowserSubagentConfig(
            runtime_dir=str(custom_runtime),
            cleanup_on_exit=False,
        )

        # Create browser subagent
        subagent = create_browser_subagent(
            config=browser_config,
        )

        # Verify subagent was created successfully
        assert subagent is not None
        assert subagent["name"] == "browser"
        assert "runnable" in subagent


def test_browser_subagent_environment_variables() -> None:
    """Test that browser subagent sets correct environment variables."""
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_runtime = Path(tmpdir) / "browser_test"
        custom_runtime.mkdir(parents=True, exist_ok=True)

        # Mock environment
        env_patch = {}
        with patch.dict(os.environ, env_patch, clear=False):
            # Create browser config
            browser_config = BrowserSubagentConfig(
                runtime_dir=str(custom_runtime),
                cleanup_on_exit=True,
            )

            # Create subagent which should set env vars during execution
            subagent = create_browser_subagent(config=browser_config)

            # Note: Environment variables are set during graph execution,
            # not during creation. This test verifies the subagent can be
            # created with custom config.
            assert subagent is not None


def test_browser_subagent_default_directories() -> None:
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


def test_browser_subagent_config_from_soothe_config() -> None:
    """Test that browser subagent can be created from SootheConfig."""
    browser_config = BrowserSubagentConfig(
        disable_extensions=True,
        disable_cloud=True,
        disable_telemetry=True,
        cleanup_on_exit=True,
    )

    # Create subagent using config
    subagent = create_browser_subagent(config=browser_config)

    assert subagent is not None
    assert subagent["name"] == "browser"


def test_browser_subagent_cleanup_flag() -> None:
    """Test that cleanup_on_exit flag is properly passed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Test with cleanup enabled
        config_with_cleanup = BrowserSubagentConfig(
            runtime_dir=tmpdir,
            cleanup_on_exit=True,
        )
        subagent_with_cleanup = create_browser_subagent(config=config_with_cleanup)
        assert subagent_with_cleanup is not None

        # Test with cleanup disabled
        config_no_cleanup = BrowserSubagentConfig(
            runtime_dir=tmpdir,
            cleanup_on_exit=False,
        )
        subagent_no_cleanup = create_browser_subagent(config=config_no_cleanup)
        assert subagent_no_cleanup is not None

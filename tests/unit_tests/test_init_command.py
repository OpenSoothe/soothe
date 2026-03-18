"""Tests for soothe init command."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


def test_init_command_creates_config():
    """Test that init creates config from package resources."""
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / ".soothe"

        with patch("soothe.cli.main.SOOTHE_HOME", str(home)):
            from soothe.cli.main import init_soothe

            init_soothe()

            # Verify config was created
            config_path = home / "config" / "config.yml"
            assert config_path.exists()

            # Verify it has expected content
            content = config_path.read_text()
            assert "providers:" in content
            assert "router:" in content


def test_init_command_idempotent():
    """Test that init doesn't overwrite existing config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / ".soothe"
        config_path = home / "config" / "config.yml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("existing config")

        with patch("soothe.cli.main.SOOTHE_HOME", str(home)):
            from soothe.cli.main import init_soothe

            init_soothe()

            # Verify config wasn't overwritten
            assert config_path.read_text() == "existing config"


def test_init_creates_directories():
    """Test that init creates all required directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / ".soothe"

        with patch("soothe.cli.main.SOOTHE_HOME", str(home)):
            from soothe.cli.main import init_soothe

            init_soothe()

            # Verify all directories were created
            assert (home / "runs").exists()
            assert (home / "generated_agents").exists()
            assert (home / "logs").exists()

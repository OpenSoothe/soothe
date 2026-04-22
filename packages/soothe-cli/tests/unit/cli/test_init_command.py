"""Tests for soothe init command."""

import tempfile
from pathlib import Path
from unittest.mock import patch


def test_init_command_creates_config():
    """Test that init creates config from package resources."""
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / ".soothe"

        with patch("soothe.config.SOOTHE_HOME", str(home)):
            from soothe_cli.cli.commands.config_cmd import config_init

            config_init()

            # Verify config was created
            config_path = home / "config" / "config.yml"
            assert config_path.exists()

            # Verify it has expected content
            content = config_path.read_text()
            # Should have some configuration
            assert len(content) > 0


def test_init_command_idempotent():
    """Test that init doesn't overwrite existing config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / ".soothe"
        config_path = home / "config" / "config.yml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("existing config")

        with patch("soothe.config.SOOTHE_HOME", str(home)):
            from soothe_cli.cli.commands.config_cmd import config_init

            # Mock the confirmation prompt to return False (don't overwrite)
            with patch("typer.confirm", return_value=False):
                config_init()

            # Verify config wasn't overwritten
            assert config_path.read_text() == "existing config"


def test_init_creates_directories():
    """Test that init creates all required directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / ".soothe"

        with patch("soothe.config.SOOTHE_HOME", str(home)):
            from soothe_cli.cli.commands.config_cmd import config_init

            config_init()

            # Verify all directories were created
            assert (home / "data").exists()
            assert (home / "generated_agents").exists()
            assert (home / "logs").exists()

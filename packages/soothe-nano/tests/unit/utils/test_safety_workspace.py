"""Tests for workspace resolution and validation."""

import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from soothe_nano.workspace.workspace_policy import validate_client_workspace
from soothe_nano.workspace.workspace_runtime import (
    resolve_daemon_workspace,
)


class TestResolveDaemonWorkspace:
    """Tests for daemon workspace resolution."""

    def test_resolve_from_env_var(self, tmp_path: Path) -> None:
        """Should use SOOTHE_WORKSPACE env var when set."""
        custom_workspace = tmp_path / "custom"
        custom_workspace.mkdir()

        with mock.patch.dict(os.environ, {"SOOTHE_WORKSPACE": str(custom_workspace)}):
            result = resolve_daemon_workspace()
            assert result == custom_workspace.resolve()

    def test_resolve_to_temp_when_no_env(self) -> None:
        """Should use TEMP directory when SOOTHE_WORKSPACE not set."""
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SOOTHE_WORKSPACE", None)

            result = resolve_daemon_workspace()
            # Should be under temp directory
            assert str(result).startswith(tempfile.gettempdir())
            assert "soothe-daemon-workspace" in str(result)
            assert result.exists()

    def test_reject_system_directory_root(self) -> None:
        """Should reject / as invalid workspace."""
        with mock.patch.dict(os.environ, {"SOOTHE_WORKSPACE": "/"}):
            with pytest.raises(ValueError, match="system directory"):
                resolve_daemon_workspace()

    def test_reject_system_directory_users(self) -> None:
        """Should reject /Users as invalid workspace."""
        with mock.patch.dict(os.environ, {"SOOTHE_WORKSPACE": "/Users"}):
            with pytest.raises(ValueError, match="system directory"):
                resolve_daemon_workspace()


class TestValidateClientWorkspace:
    """Tests for client workspace validation."""

    def test_accept_valid_project_directory(self, tmp_path: Path) -> None:
        """Should accept valid project directory."""
        project = tmp_path / "myproject"
        project.mkdir()

        result = validate_client_workspace(project)
        assert result == project.resolve()

    def test_reject_system_directory_root(self) -> None:
        """Should reject / as invalid client workspace."""
        with pytest.raises(ValueError, match="system directory"):
            validate_client_workspace("/")

    def test_reject_system_directory_home(self) -> None:
        """Should reject /home as invalid client workspace."""
        with pytest.raises(ValueError, match="system directory"):
            validate_client_workspace("/home")

    def test_warn_nonexistent_directory(self, tmp_path: Path, caplog) -> None:
        """Should log when workspace doesn't exist (debug — callers may fall back)."""
        import logging

        from soothe_nano.workspace.workspace_policy import logger as ws_logger

        nonexistent = tmp_path / "nonexistent"

        # Set level on the actual logger (not just caplog) to ensure debug messages are emitted
        with caplog.at_level(logging.DEBUG, logger=ws_logger.name):
            result = validate_client_workspace(nonexistent)
        assert result == nonexistent.resolve()
        assert "does not exist" in caplog.text

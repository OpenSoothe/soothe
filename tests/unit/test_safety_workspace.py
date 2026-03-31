"""Tests for workspace resolution and validation."""

import os
from pathlib import Path
from unittest import mock

import pytest

from soothe.safety.workspace import (
    resolve_daemon_workspace,
    validate_client_workspace,
)


class TestResolveDaemonWorkspace:
    """Tests for daemon workspace resolution."""

    def test_resolve_from_env_var(self, tmp_path: Path) -> None:
        """Should use SOOTHE_WORKSPACE env var when set."""
        custom_workspace = tmp_path / "custom"
        custom_workspace.mkdir()

        with mock.patch.dict(os.environ, {"SOOTHE_WORKSPACE": str(custom_workspace)}):
            result = resolve_daemon_workspace(".")
            assert result == custom_workspace.resolve()

    def test_resolve_from_soothe_home_workspace(self, tmp_path: Path) -> None:
        """Should use $SOOTHE_HOME/Workspace/ as default."""
        with mock.patch.dict(os.environ, {}, clear=True):
            # Remove SOOTHE_WORKSPACE if set
            os.environ.pop("SOOTHE_WORKSPACE", None)

            with mock.patch("soothe.config.SOOTHE_HOME", str(tmp_path)):
                result = resolve_daemon_workspace(".")
                assert result == tmp_path / "Workspace"
                assert result.exists()

    def test_resolve_from_config_when_workspace_exists(self, tmp_path: Path) -> None:
        """Should use config workspace_dir when SOOTHE_HOME/Workspace exists and config != '.'."""
        config_workspace = tmp_path / "config_ws"
        config_workspace.mkdir()

        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SOOTHE_WORKSPACE", None)

            with mock.patch("soothe.config.SOOTHE_HOME", str(tmp_path)):
                # Create Workspace dir so it exists
                (tmp_path / "Workspace").mkdir()

                result = resolve_daemon_workspace(str(config_workspace))
                assert result == config_workspace.resolve()

    def test_reject_system_directory_root(self) -> None:
        """Should reject / as invalid workspace."""
        with mock.patch.dict(os.environ, {"SOOTHE_WORKSPACE": "/"}):
            with pytest.raises(ValueError, match="system directory"):
                resolve_daemon_workspace(".")

    def test_reject_system_directory_users(self) -> None:
        """Should reject /Users as invalid workspace."""
        with mock.patch.dict(os.environ, {"SOOTHE_WORKSPACE": "/Users"}):
            with pytest.raises(ValueError, match="system directory"):
                resolve_daemon_workspace(".")


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
        """Should warn when workspace doesn't exist."""
        nonexistent = tmp_path / "nonexistent"

        result = validate_client_workspace(nonexistent)
        assert result == nonexistent.resolve()
        assert "does not exist" in caplog.text

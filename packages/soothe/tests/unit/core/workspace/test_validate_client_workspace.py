"""Tests for client workspace validation.

Moved from ``soothe_nano`` to the host (IG-635 PR-4): ``validate_client_workspace``
is host-owned (``soothe.workspace.resolution``).
"""

from pathlib import Path

import pytest

from soothe.workspace import validate_client_workspace


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

        from soothe.workspace.resolution import logger as ws_logger

        nonexistent = tmp_path / "nonexistent"

        # Set level on the actual logger (not just caplog) to ensure debug messages are emitted
        with caplog.at_level(logging.DEBUG, logger=ws_logger.name):
            result = validate_client_workspace(nonexistent)
        assert result == nonexistent.resolve()
        assert "does not exist" in caplog.text

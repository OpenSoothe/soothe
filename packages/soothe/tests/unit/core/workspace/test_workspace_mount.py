"""Tests for workspace host convention path mapping (RFC-621, IG-458)."""

from __future__ import annotations

from pathlib import Path

import pytest
from soothe_nano.workspace.resolution import (
    translate_client_path_to_container,
    translate_container_path_to_client,
)

from soothe.config.models import WorkspaceMountConfig


class TestTranslateClientPathToContainer:
    """Tests for translate_client_path_to_container (RFC-621)."""

    def test_identity_when_not_configured(self):
        assert translate_client_path_to_container("/foo/bar") == Path("/foo/bar").resolve()

    def test_identity_when_host_root_none(self):
        assert (
            translate_client_path_to_container("/foo/bar", host_root=None, container_root="/ws")
            == Path("/foo/bar").resolve()
        )

    def test_identity_when_container_root_none(self):
        assert (
            translate_client_path_to_container("/foo/bar", host_root="/host", container_root=None)
            == Path("/foo/bar").resolve()
        )

    def test_valid_mapping(self):
        result = translate_client_path_to_container(
            "/host/ws/project-a",
            host_root="/host/ws",
            container_root="/workspaces",
        )
        assert result == Path("/workspaces/project-a")

    def test_nested_path(self):
        result = translate_client_path_to_container(
            "/host/ws/project-a/src/main.py",
            host_root="/host/ws",
            container_root="/workspaces",
        )
        assert result == Path("/workspaces/project-a/src/main.py")

    def test_workspace_outside_host_root_raises(self):
        with pytest.raises(ValueError, match="not under configured host_root"):
            translate_client_path_to_container(
                "/other/path/project",
                host_root="/host/ws",
                container_root="/workspaces",
            )

    def test_host_root_itself(self):
        result = translate_client_path_to_container(
            "/host/ws",
            host_root="/host/ws",
            container_root="/workspaces",
        )
        assert result == Path("/workspaces")

    def test_path_at_host_root_boundary(self):
        # /host/workspacesx is NOT under /host/ws — boundary check
        with pytest.raises(ValueError, match="not under configured host_root"):
            translate_client_path_to_container(
                "/host/wsx",
                host_root="/host/ws",
                container_root="/workspaces",
            )


class TestTranslateContainerPathToClient:
    """Tests for translate_container_path_to_client (RFC-621)."""

    def test_identity_when_not_configured(self):
        assert translate_container_path_to_client("/foo/bar") == Path("/foo/bar").resolve()

    def test_valid_mapping(self):
        result = translate_container_path_to_client(
            "/workspaces/project-a",
            host_root="/host/ws",
            container_root="/workspaces",
        )
        assert result == Path("/host/ws/project-a")

    def test_nested_path(self):
        result = translate_container_path_to_client(
            "/workspaces/project-a/src/main.py",
            host_root="/host/ws",
            container_root="/workspaces",
        )
        assert result == Path("/host/ws/project-a/src/main.py")

    def test_path_outside_container_root_unchanged(self):
        result = translate_container_path_to_client(
            "/etc/config",
            host_root="/host/ws",
            container_root="/workspaces",
        )
        assert result == Path("/etc/config").resolve()

    def test_container_root_itself(self):
        result = translate_container_path_to_client(
            "/workspaces",
            host_root="/host/ws",
            container_root="/workspaces",
        )
        assert result == Path("/host/ws")


class TestWorkspaceMountConfig:
    """Tests for WorkspaceMountConfig model (RFC-621)."""

    def test_both_none_is_valid(self):
        cfg = WorkspaceMountConfig()
        assert not cfg.is_configured
        assert cfg.host_root is None
        assert cfg.container_root is None

    def test_both_set_is_valid(self):
        cfg = WorkspaceMountConfig(host_root="/host", container_root="/container")
        assert cfg.is_configured
        assert cfg.host_root == "/host"
        assert cfg.container_root == "/container"

    def test_only_host_root_raises(self):
        with pytest.raises(ValueError, match="must both be set"):
            WorkspaceMountConfig(host_root="/host")

    def test_only_container_root_raises(self):
        with pytest.raises(ValueError, match="must both be set"):
            WorkspaceMountConfig(container_root="/container")

    def test_empty_strings_treated_as_unset(self):
        cfg = WorkspaceMountConfig(host_root="", container_root="")
        assert not cfg.is_configured

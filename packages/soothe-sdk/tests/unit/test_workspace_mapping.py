"""Tests for SDK WorkspaceMapping (RFC-621, IG-458)."""

from __future__ import annotations

from soothe_sdk.wire.protocol import WorkspaceMapping


class TestWorkspaceMapping:
    """Tests for WorkspaceMapping path translation (RFC-621)."""

    def test_not_configured_when_both_none(self):
        m = WorkspaceMapping(host_root=None, container_root=None)
        assert not m.is_configured

    def test_configured_when_both_set(self):
        m = WorkspaceMapping(host_root="/host/ws", container_root="/workspaces")
        assert m.is_configured

    def test_translate_to_client_when_not_configured(self):
        m = WorkspaceMapping(host_root=None, container_root=None)
        assert m.translate_to_client("/workspaces/foo") == "/workspaces/foo"

    def test_translate_to_client_valid(self):
        m = WorkspaceMapping(host_root="/host/ws", container_root="/workspaces")
        assert (
            m.translate_to_client("/workspaces/project-a/src/main.py")
            == "/host/ws/project-a/src/main.py"
        )

    def test_translate_to_client_exact_container_root(self):
        m = WorkspaceMapping(host_root="/host/ws", container_root="/workspaces")
        assert m.translate_to_client("/workspaces") == "/host/ws"

    def test_translate_to_client_path_outside_container_root(self):
        m = WorkspaceMapping(host_root="/host/ws", container_root="/workspaces")
        assert m.translate_to_client("/etc/config") == "/etc/config"

    def test_translate_to_container_valid(self):
        m = WorkspaceMapping(host_root="/host/ws", container_root="/workspaces")
        assert m.translate_to_container("/host/ws/project-a") == "/workspaces/project-a"

    def test_translate_to_container_exact_host_root(self):
        m = WorkspaceMapping(host_root="/host/ws", container_root="/workspaces")
        assert m.translate_to_container("/host/ws") == "/workspaces"

    def test_translate_to_container_path_outside_host_root(self):
        m = WorkspaceMapping(host_root="/host/ws", container_root="/workspaces")
        assert m.translate_to_container("/other/path") == "/other/path"

    def test_roundtrip_client_to_container_to_client(self):
        m = WorkspaceMapping(host_root="/var/run/soothe/workspaces", container_root="/workspaces")
        original = "/var/run/soothe/workspaces/project-a/src/main.py"
        container = m.translate_to_container(original)
        assert container == "/workspaces/project-a/src/main.py"
        back = m.translate_to_client(container)
        assert back == original

    def test_no_partial_prefix_match(self):
        m = WorkspaceMapping(host_root="/host/ws", container_root="/workspaces")
        # /workspaces-extra should NOT be translated (not a prefix match with /)
        assert m.translate_to_client("/workspaces-extra/file") == "/workspaces-extra/file"

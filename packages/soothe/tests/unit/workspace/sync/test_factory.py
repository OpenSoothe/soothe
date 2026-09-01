"""Tests for the URI classifier and factory security (S8: SSRF prevention)."""

from __future__ import annotations

import pytest

from soothe.workspace.resolution import is_remote_workspace_uri


class TestIsRemoteWorkspaceUri:
    """S8: explicit scheme allowlist, not substring check."""

    @pytest.mark.parametrize(
        "uri",
        [
            "s3://bucket/prefix",
            "gs://bucket/prefix",
            "az://container/prefix",
            "S3://bucket/prefix",  # case-insensitive
            "GS://bucket/prefix",
        ],
    )
    def test_allowed_schemes(self, uri: str) -> None:
        assert is_remote_workspace_uri(uri) is True

    @pytest.mark.parametrize(
        "uri",
        [
            "file:///etc/passwd",  # SSRF
            "sftp://host/path",  # SSRF
            "http://localhost:8080/",  # SSRF
            "https://example.com/",  # SSRF
            "ftp://host/file",  # SSRF
            "memory://test/",  # test-only
            "/local/path",  # local path
            "relative/path",  # not a URI
            "",  # empty
            "s3",  # no scheme separator
        ],
    )
    def test_rejected_schemes(self, uri: str) -> None:
        assert is_remote_workspace_uri(uri) is False


class TestConstructSyncBackend:
    """S8: factory rejects disallowed schemes."""

    def test_rejects_file_scheme(self) -> None:
        from soothe.workspace.sync.factory import construct_sync_backend

        with pytest.raises(ValueError, match="unsupported.*scheme"):
            construct_sync_backend("file:///etc/passwd")

    def test_rejects_sftp_scheme(self) -> None:
        from soothe.workspace.sync.factory import construct_sync_backend

        with pytest.raises(ValueError, match="unsupported.*scheme"):
            construct_sync_backend("sftp://host/path")

    def test_rejects_http_scheme(self) -> None:
        from soothe.workspace.sync.factory import construct_sync_backend

        with pytest.raises(ValueError, match="unsupported.*scheme"):
            construct_sync_backend("http://localhost:8080/")

    def test_rejects_no_scheme(self) -> None:
        from soothe.workspace.sync.factory import construct_sync_backend

        with pytest.raises(ValueError, match="no scheme"):
            construct_sync_backend("/local/path")

    def test_rejects_memory_scheme(self) -> None:
        from soothe.workspace.sync.factory import construct_sync_backend

        with pytest.raises(ValueError, match="unsupported.*scheme"):
            construct_sync_backend("memory://test/")

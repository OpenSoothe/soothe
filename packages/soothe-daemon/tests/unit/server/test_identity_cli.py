"""Unit tests for the identity service CLI (RFC-307 §CLI Commands).

Exercises the ``soothed identity`` Typer sub-app end-to-end against a real
``IdentityService`` backed by a temp SQLite database:

- User management: create-user, list-users, delete-user
- AKSK management: create-aksk, list-aksk, revoke-aksk
- Token management: list-tokens, revoke-token, revoke-all-tokens
- External mapping: map-external, list-mappings, unmap-external
- Service status: status

The ``_require_enabled`` guard is stubbed so commands run regardless of the
host's daemon config, and ``_get_identity_service`` is patched to return a
real ``IdentityService`` with a temp DB + known JWT key.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from soothe.identity.identity_service import IdentityService
from typer.testing import CliRunner

from soothe_daemon.identity_cli import app as identity_app

TEST_JWT_KEY = "test-secret-key-for-testing-only-256bit!!"

# Valid-format keys for deterministic AKSK creation (see credentials.py).
KNOWN_ACCESS_KEY = "AK-abcdefghijklmno0"
KNOWN_SECRET_KEY = "SK-abcdefghijklmnopqrstuvwxyz012345"


runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _event_loop() -> None:
    """Ensure a fresh event loop for each test.

    IdentityService uses ``asyncio.get_event_loop().run_until_complete()``
    internally, so a current loop must be set in the test thread.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    loop.close()
    asyncio.set_event_loop(None)


@pytest.fixture()
def identity_service(tmp_path: Path) -> IdentityService:
    """Real IdentityService with a temp SQLite DB."""
    db_path = tmp_path / "test_identity_cli.db"
    svc = IdentityService(db_path=db_path, jwt_key=TEST_JWT_KEY)
    yield svc
    svc.close_sync()


@pytest.fixture(autouse=True)
def _patch_identity_cli(identity_service: IdentityService, monkeypatch) -> None:
    """Patch the CLI helpers to use the temp IdentityService.

    - ``_require_enabled`` is a no-op so commands run regardless of host config.
    - ``_get_identity_service`` returns the shared temp IdentityService.
    """
    monkeypatch.setattr("soothe_daemon.identity_cli._require_enabled", lambda: None)
    monkeypatch.setattr(
        "soothe_daemon.identity_cli._get_identity_service",
        lambda: identity_service,
    )
    monkeypatch.setenv("SOOTHE_JWT_KEY", TEST_JWT_KEY)
    monkeypatch.setenv("SOOTHE_HOME", str(identity_service.db_path.parent))


def _create_user_and_aksk(svc: IdentityService, user_id: str = "alice") -> tuple[str, str, str]:
    """Create a user + AKSK, returning (access_key, secret_key, aksk_id).

    Patches credential generators so the secret key is known for auth tests.
    """
    svc.create_user(user_id)
    with (
        patch(
            "soothe.identity.identity_service.generate_access_key",
            return_value=KNOWN_ACCESS_KEY,
        ),
        patch(
            "soothe.identity.identity_service.generate_secret_key",
            return_value=KNOWN_SECRET_KEY,
        ),
    ):
        aksk = svc.create_aksk(user_id)
    return KNOWN_ACCESS_KEY, KNOWN_SECRET_KEY, aksk.aksk_id


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------


class TestCreateUser:
    """Tests for ``identity create-user``."""

    def test_create_user_success(self) -> None:
        result = runner.invoke(identity_app, ["create-user", "--user", "alice"])
        assert result.exit_code == 0
        assert "User created" in result.stdout
        assert "alice" in result.stdout

    def test_create_user_with_metadata(self) -> None:
        meta = json.dumps({"display_name": "Alice", "role": "admin"})
        result = runner.invoke(
            identity_app,
            ["create-user", "--user", "alice", "--metadata", meta],
        )
        assert result.exit_code == 0
        assert "User created" in result.stdout

    def test_create_user_invalid_json_metadata(self) -> None:
        result = runner.invoke(
            identity_app,
            ["create-user", "--user", "alice", "--metadata", "{not-json}"],
        )
        assert result.exit_code == 1
        assert "Invalid JSON" in result.stdout


class TestListUsers:
    """Tests for ``identity list-users``."""

    def test_list_users_empty(self) -> None:
        result = runner.invoke(identity_app, ["list-users"])
        assert result.exit_code == 0
        assert "No users found" in result.stdout

    def test_list_users_shows_users(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        runner.invoke(identity_app, ["create-user", "--user", "bob"])
        result = runner.invoke(identity_app, ["list-users"])
        assert result.exit_code == 0
        assert "alice" in result.stdout
        assert "bob" in result.stdout


class TestDeleteUser:
    """Tests for ``identity delete-user``."""

    def test_delete_user_with_force(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        result = runner.invoke(identity_app, ["delete-user", "--user", "alice", "--force"])
        assert result.exit_code == 0
        assert "User deleted" in result.stdout
        assert "alice" in result.stdout

    def test_delete_user_confirm_yes(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        result = runner.invoke(identity_app, ["delete-user", "--user", "alice"], input="y\n")
        assert result.exit_code == 0
        assert "User deleted" in result.stdout

    def test_delete_user_confirm_no(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        result = runner.invoke(identity_app, ["delete-user", "--user", "alice"], input="n\n")
        assert result.exit_code == 0
        assert "Cancelled" in result.stdout

    def test_delete_nonexistent_user(self) -> None:
        result = runner.invoke(identity_app, ["delete-user", "--user", "ghost", "--force"])
        assert result.exit_code == 1
        assert "Error" in result.stdout


# ---------------------------------------------------------------------------
# AKSK Management
# ---------------------------------------------------------------------------


class TestCreateAKSK:
    """Tests for ``identity create-aksk``."""

    def test_create_aksk_success(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        with (
            patch(
                "soothe.identity.identity_service.generate_access_key",
                return_value=KNOWN_ACCESS_KEY,
            ),
            patch(
                "soothe.identity.identity_service.generate_secret_key",
                return_value=KNOWN_SECRET_KEY,
            ),
        ):
            result = runner.invoke(identity_app, ["create-aksk", "--user", "alice"])
        assert result.exit_code == 0
        assert "AKSK created" in result.stdout
        assert KNOWN_ACCESS_KEY in result.stdout
        # Secret key is derived from access key in the CLI display
        assert "SK-" in result.stdout

    def test_create_aksk_nonexistent_user(self) -> None:
        result = runner.invoke(identity_app, ["create-aksk", "--user", "ghost"])
        assert result.exit_code == 1
        assert "Error" in result.stdout

    def test_create_aksk_with_expiry(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        result = runner.invoke(
            identity_app,
            ["create-aksk", "--user", "alice", "--expiry-days", "7"],
        )
        assert result.exit_code == 0
        assert "AKSK created" in result.stdout
        assert "expires_at" in result.stdout


class TestListAKSK:
    """Tests for ``identity list-aksk``."""

    def test_list_aksk_empty(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        result = runner.invoke(identity_app, ["list-aksk", "--user", "alice"])
        assert result.exit_code == 0
        assert "No AKSK pairs found" in result.stdout

    def test_list_aksk_shows_pairs(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        runner.invoke(identity_app, ["create-aksk", "--user", "alice"])
        result = runner.invoke(identity_app, ["list-aksk", "--user", "alice"])
        assert result.exit_code == 0
        assert "AK" in result.stdout  # access key prefix or table header


class TestRevokeAKSK:
    """Tests for ``identity revoke-aksk``."""

    def test_revoke_aksk_with_force(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        runner.invoke(identity_app, ["create-aksk", "--user", "alice"])
        # The CLI truncates aksk_id in display, so fetch the real one
        from soothe_daemon.identity_cli import _get_identity_service

        svc = _get_identity_service()
        aksks = svc.list_aksk("alice")
        aksk_id = aksks[0].aksk_id

        result = runner.invoke(identity_app, ["revoke-aksk", "--aksk-id", aksk_id, "--force"])
        assert result.exit_code == 0
        assert "AKSK revoked" in result.stdout

    def test_revoke_aksk_confirm_no(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        runner.invoke(identity_app, ["create-aksk", "--user", "alice"])
        from soothe_daemon.identity_cli import _get_identity_service

        svc = _get_identity_service()
        aksk_id = svc.list_aksk("alice")[0].aksk_id

        result = runner.invoke(identity_app, ["revoke-aksk", "--aksk-id", aksk_id], input="n\n")
        assert result.exit_code == 0
        assert "Cancelled" in result.stdout


# ---------------------------------------------------------------------------
# Token Management
# ---------------------------------------------------------------------------


class TestListTokens:
    """Tests for ``identity list-tokens``."""

    def test_list_tokens_empty(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        result = runner.invoke(identity_app, ["list-tokens", "--user", "alice"])
        assert result.exit_code == 0
        assert "No tokens found" in result.stdout

    def test_list_tokens_after_auth(self) -> None:
        """After authenticating, tokens should be listed."""
        from soothe_daemon.identity_cli import _get_identity_service

        identity = _get_identity_service()
        access_key, secret_key, _ = _create_user_and_aksk(identity)
        # Authenticate to generate tokens
        identity.authenticate(access_key, secret_key)

        result = runner.invoke(identity_app, ["list-tokens", "--user", "alice"])
        assert result.exit_code == 0
        assert "Tokens" in result.stdout

    def test_list_tokens_active_only(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        result = runner.invoke(identity_app, ["list-tokens", "--user", "alice", "--active"])
        assert result.exit_code == 0
        assert "No active tokens" in result.stdout


class TestRevokeToken:
    """Tests for ``identity revoke-token``."""

    def test_revoke_token_by_jti(self) -> None:
        """Revoke a token after authentication."""
        from soothe_daemon.identity_cli import _get_identity_service

        identity = _get_identity_service()
        identity.create_user("alice")
        with (
            patch(
                "soothe.identity.identity_service.generate_access_key",
                return_value=KNOWN_ACCESS_KEY,
            ),
            patch(
                "soothe.identity.identity_service.generate_secret_key",
                return_value=KNOWN_SECRET_KEY,
            ),
        ):
            identity.create_aksk("alice")

        auth_result = identity.authenticate(KNOWN_ACCESS_KEY, KNOWN_SECRET_KEY)
        assert auth_result is not None

        # Get a token JTI from the service
        tokens = identity.list_tokens("alice")
        assert len(tokens) > 0
        jti = tokens[0].jti

        result = runner.invoke(identity_app, ["revoke-token", "--jti", jti])
        assert result.exit_code == 0
        assert "Token revoked" in result.stdout

    def test_revoke_nonexistent_token(self) -> None:
        """revoke_token is idempotent: nonexistent JTI succeeds (no-op).

        The service uses INSERT OR IGNORE so revoking a nonexistent JTI
        does not raise — it simply affects zero rows.
        """
        result = runner.invoke(identity_app, ["revoke-token", "--jti", "nonexistent-jti"])
        assert result.exit_code == 0
        assert "Token revoked" in result.stdout


class TestRevokeAllTokens:
    """Tests for ``identity revoke-all-tokens``."""

    def test_revoke_all_with_force(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        result = runner.invoke(identity_app, ["revoke-all-tokens", "--user", "alice", "--force"])
        assert result.exit_code == 0
        assert "All tokens revoked" in result.stdout

    def test_revoke_all_confirm_no(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        result = runner.invoke(identity_app, ["revoke-all-tokens", "--user", "alice"], input="n\n")
        assert result.exit_code == 0
        assert "Cancelled" in result.stdout


# ---------------------------------------------------------------------------
# External Mapping
# ---------------------------------------------------------------------------


class TestMapExternal:
    """Tests for ``identity map-external``."""

    def test_map_external_success(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        result = runner.invoke(
            identity_app,
            [
                "map-external",
                "--channel",
                "telegram",
                "--sender-id",
                "12345",
                "--user",
                "alice",
            ],
        )
        assert result.exit_code == 0
        assert "External identity mapped" in result.stdout
        assert "telegram" in result.stdout
        assert "12345" in result.stdout

    def test_map_external_nonexistent_user(self) -> None:
        result = runner.invoke(
            identity_app,
            [
                "map-external",
                "--channel",
                "telegram",
                "--sender-id",
                "12345",
                "--user",
                "ghost",
            ],
        )
        assert result.exit_code == 1
        assert "Error" in result.stdout


class TestListMappings:
    """Tests for ``identity list-mappings``."""

    def test_list_mappings_empty(self) -> None:
        result = runner.invoke(identity_app, ["list-mappings"])
        assert result.exit_code == 0
        assert "No mappings found" in result.stdout

    def test_list_mappings_shows_mappings(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        runner.invoke(
            identity_app,
            [
                "map-external",
                "--channel",
                "telegram",
                "--sender-id",
                "12345",
                "--user",
                "alice",
            ],
        )
        result = runner.invoke(identity_app, ["list-mappings"])
        assert result.exit_code == 0
        assert "telegram" in result.stdout
        assert "12345" in result.stdout

    def test_list_mappings_filter_by_channel(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        runner.invoke(
            identity_app,
            [
                "map-external",
                "--channel",
                "telegram",
                "--sender-id",
                "12345",
                "--user",
                "alice",
            ],
        )
        result = runner.invoke(identity_app, ["list-mappings", "--channel", "telegram"])
        assert result.exit_code == 0
        assert "telegram" in result.stdout

    def test_list_mappings_filter_by_user(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        runner.invoke(
            identity_app,
            [
                "map-external",
                "--channel",
                "telegram",
                "--sender-id",
                "12345",
                "--user",
                "alice",
            ],
        )
        result = runner.invoke(identity_app, ["list-mappings", "--user", "alice"])
        assert result.exit_code == 0
        assert "alice" in result.stdout


class TestUnmapExternal:
    """Tests for ``identity unmap-external``."""

    def test_unmap_external_success(self) -> None:
        runner.invoke(identity_app, ["create-user", "--user", "alice"])
        runner.invoke(
            identity_app,
            [
                "map-external",
                "--channel",
                "telegram",
                "--sender-id",
                "12345",
                "--user",
                "alice",
            ],
        )
        result = runner.invoke(
            identity_app,
            ["unmap-external", "--channel", "telegram", "--sender-id", "12345"],
        )
        assert result.exit_code == 0
        assert "External mapping removed" in result.stdout


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class TestStatus:
    """Tests for ``identity status``."""

    def test_status_enabled(self, monkeypatch, tmp_path: Path) -> None:
        """Status command shows service info when identity is enabled."""
        from soothe.identity.runtime import IdentityConfig

        from soothe_daemon.config import SootheDaemonConfig

        cfg = SootheDaemonConfig()
        cfg.identity = IdentityConfig(enabled=True)
        # status() does local imports from soothe_daemon.config, so patch there.
        # Use a real temp file so config_path.exists() returns True.
        config_path = tmp_path / "daemon.yml"
        config_path.write_text("identity:\n  enabled: true\n")
        monkeypatch.setattr(
            "soothe_daemon.config.default_daemon_config_path",
            lambda: config_path,
        )
        monkeypatch.setattr(
            "soothe_daemon.config.SootheDaemonConfig.from_yaml_file",
            staticmethod(lambda _path: cfg),
        )
        result = runner.invoke(identity_app, ["status"])
        assert result.exit_code == 0
        assert "Identity Service Status" in result.stdout
        assert "enabled" in result.stdout

    def test_status_disabled(self, monkeypatch, tmp_path: Path) -> None:
        """Status command shows disabled message when identity is off."""
        from soothe.identity.runtime import IdentityConfig

        from soothe_daemon.config import SootheDaemonConfig

        cfg = SootheDaemonConfig()
        cfg.identity = IdentityConfig(enabled=False)
        config_path = tmp_path / "daemon.yml"
        config_path.write_text("identity:\n  enabled: false\n")
        monkeypatch.setattr(
            "soothe_daemon.config.default_daemon_config_path",
            lambda: config_path,
        )
        monkeypatch.setattr(
            "soothe_daemon.config.SootheDaemonConfig.from_yaml_file",
            staticmethod(lambda _path: cfg),
        )
        result = runner.invoke(identity_app, ["status"])
        assert result.exit_code == 0
        assert "disabled" in result.stdout

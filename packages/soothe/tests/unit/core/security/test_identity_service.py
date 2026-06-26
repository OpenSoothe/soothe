"""Unit tests for IdentityService (RFC-307 §Protocol Interface implementation).

Tests user management, AKSK provisioning, JWT authentication, token rotation,
revocation, and external identity mapping.

The IdentityService uses asyncio.get_event_loop().run_until_complete() internally,
so tests must run synchronously with a pre-set event loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from soothe.core.security.errors import (
    AKSKNotFoundError,
    MappingConflictError,
    MappingNotFoundError,
    UserNotFoundError,
)
from soothe.core.security.identity_service import (
    IdentityService,
    initialize_identity_tables_sync,
)

TEST_JWT_KEY = "test-secret-key-for-testing-only-256bit!!"

# Valid-format keys for patching credential generators
KNOWN_ACCESS_KEY = "AK-abcdefghijklmno0"
KNOWN_SECRET_KEY = "SK-abcdefghijklmnopqrstuvwxyz012345"


@pytest.fixture(autouse=True)
def _event_loop() -> None:
    """Ensure a fresh event loop is set for each test.

    IdentityService methods call asyncio.get_event_loop().run_until_complete(),
    which requires a current event loop in the thread.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    loop.close()
    asyncio.set_event_loop(None)


@pytest.fixture()
def identity_service(tmp_path: Path) -> IdentityService:
    """Create an IdentityService with a temp SQLite database."""
    db_path = tmp_path / "test_identity.db"
    return IdentityService(db_path=db_path, jwt_key=TEST_JWT_KEY)


@pytest.fixture()
def identity_service_no_expiry(tmp_path: Path) -> IdentityService:
    """Create an IdentityService with AKSK that never expires."""
    db_path = tmp_path / "test_identity_no_exp.db"
    return IdentityService(
        db_path=db_path,
        jwt_key=TEST_JWT_KEY,
        default_aksk_expiry_days=None,
    )


def _create_user_with_aksk(
    svc: IdentityService, user_id: str = "test-user"
) -> tuple[str, str, str]:
    """Helper: create user + AKSK, return (access_key, secret_key, aksk_id).

    Patches credential generators to return known-format keys.
    """
    svc.create_user(user_id)
    with (
        patch(
            "soothe.core.security.identity_service.generate_access_key",
            return_value=KNOWN_ACCESS_KEY,
        ),
        patch(
            "soothe.core.security.identity_service.generate_secret_key",
            return_value=KNOWN_SECRET_KEY,
        ),
    ):
        aksk = svc.create_aksk(user_id)
    return KNOWN_ACCESS_KEY, KNOWN_SECRET_KEY, aksk.aksk_id


# ---------------------------------------------------------------------------
# initialize_identity_tables_sync
# ---------------------------------------------------------------------------


class TestInitializeIdentityTables:
    """Tests for initialize_identity_tables_sync()."""

    def test_creates_all_tables(self, tmp_path: Path) -> None:
        """All identity tables must be created."""
        import sqlite3

        db_path = tmp_path / "init_test.db"
        initialize_identity_tables_sync(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert "identity_users" in tables
        assert "identity_aksk_pairs" in tables
        assert "identity_tokens" in tables
        assert "identity_external_mappings" in tables
        assert "identity_revoked_jtis" in tables

    def test_creates_indexes(self, tmp_path: Path) -> None:
        """Indexes must be created for performance."""
        import sqlite3

        db_path = tmp_path / "init_test.db"
        initialize_identity_tables_sync(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert "idx_identity_aksk_user" in indexes
        assert "idx_identity_tokens_user" in indexes
        assert "idx_identity_tokens_aksk" in indexes
        assert "idx_identity_mappings_channel_sender" in indexes
        assert "idx_identity_mappings_user" in indexes

    def test_idempotent(self, tmp_path: Path) -> None:
        """Calling twice must not raise."""
        db_path = tmp_path / "init_test.db"
        initialize_identity_tables_sync(db_path)
        initialize_identity_tables_sync(db_path)  # should not raise

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        """Parent directories must be created if missing."""
        db_path = tmp_path / "nested" / "deep" / "test.db"
        initialize_identity_tables_sync(db_path)
        assert db_path.exists()


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------


class TestUserManagement:
    """Tests for create_user, get_user, list_users, delete_user."""

    def test_create_user_returns_user(self, identity_service: IdentityService) -> None:
        """create_user must return a User with correct fields."""
        user = identity_service.create_user("alice", {"display_name": "Alice"})
        assert user.user_id == "alice"
        assert user.metadata == {"display_name": "Alice"}
        assert user.created_at is not None

    def test_create_user_default_metadata(self, identity_service: IdentityService) -> None:
        """Default metadata is an empty dict."""
        user = identity_service.create_user("bob")
        assert user.metadata == {}

    def test_get_user_returns_user(self, identity_service: IdentityService) -> None:
        """get_user must return the user if it exists."""
        identity_service.create_user("alice")
        fetched = identity_service.get_user("alice")
        assert fetched is not None
        assert fetched.user_id == "alice"

    def test_get_user_nonexistent_returns_none(self, identity_service: IdentityService) -> None:
        """get_user must return None for non-existent user."""
        assert identity_service.get_user("ghost") is None

    def test_list_users_returns_all(self, identity_service: IdentityService) -> None:
        """list_users must return all users."""
        identity_service.create_user("alice")
        identity_service.create_user("bob")
        users = identity_service.list_users()
        user_ids = {u.user_id for u in users}
        assert user_ids == {"alice", "bob"}

    def test_list_users_empty(self, identity_service: IdentityService) -> None:
        """list_users on empty database returns []."""
        assert identity_service.list_users() == []

    def test_delete_user_removes_user(self, identity_service: IdentityService) -> None:
        """delete_user must remove the user."""
        identity_service.create_user("alice")
        identity_service.delete_user("alice")
        assert identity_service.get_user("alice") is None

    def test_delete_user_cascades_aksk(self, identity_service: IdentityService) -> None:
        """delete_user must also remove AKSK pairs."""
        _create_user_with_aksk(identity_service, "alice")
        identity_service.delete_user("alice")
        assert identity_service.list_aksk("alice") == []

    def test_delete_user_nonexistent_raises(self, identity_service: IdentityService) -> None:
        """delete_user on non-existent user must raise UserNotFoundError."""
        with pytest.raises(UserNotFoundError):
            identity_service.delete_user("ghost")


# ---------------------------------------------------------------------------
# AKSK Management
# ---------------------------------------------------------------------------


class TestAKSKManagement:
    """Tests for create_aksk, list_aksk, revoke_aksk."""

    def test_create_aksk_returns_pair(self, identity_service: IdentityService) -> None:
        """create_aksk must return an AKSKPair with all fields."""
        identity_service.create_user("alice")
        with (
            patch(
                "soothe.core.security.identity_service.generate_access_key",
                return_value=KNOWN_ACCESS_KEY,
            ),
            patch(
                "soothe.core.security.identity_service.generate_secret_key",
                return_value=KNOWN_SECRET_KEY,
            ),
        ):
            aksk = identity_service.create_aksk("alice")
        assert aksk.user_id == "alice"
        assert aksk.access_key == KNOWN_ACCESS_KEY
        assert aksk.secret_key_hash
        assert not aksk.revoked
        assert aksk.created_at is not None

    def test_create_aksk_nonexistent_user_raises(self, identity_service: IdentityService) -> None:
        """create_aksk on non-existent user must raise UserNotFoundError."""
        with pytest.raises(UserNotFoundError):
            identity_service.create_aksk("ghost")

    def test_create_aksk_with_default_expiry(self, identity_service: IdentityService) -> None:
        """Default expiry (90 days) is applied when expiry_days=None."""
        identity_service.create_user("alice")
        aksk = identity_service.create_aksk("alice")
        assert aksk.expires_at is not None

    def test_create_aksk_no_expiry(self, identity_service_no_expiry: IdentityService) -> None:
        """expires_at is None when default_aksk_expiry_days=None."""
        identity_service_no_expiry.create_user("alice")
        aksk = identity_service_no_expiry.create_aksk("alice")
        assert aksk.expires_at is None

    def test_create_aksk_exceeding_max_raises(self, identity_service: IdentityService) -> None:
        """expiry_days exceeding max must raise ValueError."""
        identity_service.create_user("alice")
        with pytest.raises(ValueError, match="exceeds maximum"):
            identity_service.create_aksk("alice", expiry_days=999)

    def test_create_aksk_custom_expiry(self, identity_service: IdentityService) -> None:
        """Custom expiry_days is reflected in expires_at."""
        identity_service.create_user("alice")
        from datetime import UTC, datetime, timedelta

        before = datetime.now(UTC)
        aksk = identity_service.create_aksk("alice", expiry_days=7)
        after = datetime.now(UTC)
        expected_min = before + timedelta(days=7)
        expected_max = after + timedelta(days=7)
        assert expected_min <= aksk.expires_at <= expected_max

    def test_list_aksk_returns_pairs(self, identity_service: IdentityService) -> None:
        """list_aksk must return all pairs for a user."""
        identity_service.create_user("alice")
        identity_service.create_aksk("alice")
        identity_service.create_aksk("alice")
        aksks = identity_service.list_aksk("alice")
        assert len(aksks) == 2

    def test_list_aksk_empty(self, identity_service: IdentityService) -> None:
        """list_aksk on user with no pairs returns []."""
        identity_service.create_user("alice")
        assert identity_service.list_aksk("alice") == []

    def test_revoke_aksk_marks_revoked(self, identity_service: IdentityService) -> None:
        """revoke_aksk must set revoked=True."""
        identity_service.create_user("alice")
        aksk = identity_service.create_aksk("alice")
        identity_service.revoke_aksk(aksk.aksk_id)
        aksks = identity_service.list_aksk("alice")
        assert aksks[0].revoked is True
        assert aksks[0].revoked_at is not None

    def test_revoke_aksk_nonexistent_raises(self, identity_service: IdentityService) -> None:
        """revoke_aksk on non-existent ID must raise AKSKNotFoundError."""
        with pytest.raises(AKSKNotFoundError):
            identity_service.revoke_aksk("nonexistent-id")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class TestAuthenticate:
    """Tests for authenticate()."""

    def test_valid_credentials_return_auth_result(self, identity_service: IdentityService) -> None:
        """Valid AKSK must return AuthResult with tokens."""
        access_key, secret_key, _ = _create_user_with_aksk(identity_service, "alice")
        result = identity_service.authenticate(access_key, secret_key)
        assert result is not None
        assert result.user_id == "alice"
        assert result.access_token
        assert result.refresh_token
        assert result.expires_in == 3600

    def test_wrong_access_key_returns_none(self, identity_service: IdentityService) -> None:
        """Wrong access key must return None (no user existence hint)."""
        _create_user_with_aksk(identity_service, "alice")
        result = identity_service.authenticate("AK-wrong1234567890", KNOWN_SECRET_KEY)
        assert result is None

    def test_wrong_secret_key_returns_none(self, identity_service: IdentityService) -> None:
        """Wrong secret key must return None."""
        access_key, _, _ = _create_user_with_aksk(identity_service, "alice")
        result = identity_service.authenticate(
            access_key, "SK-wrong1234567890abcdefghijklmnopqrstuv"
        )
        assert result is None

    def test_invalid_access_key_format_returns_none(
        self, identity_service: IdentityService
    ) -> None:
        """Malformed access key must return None without DB lookup."""
        _create_user_with_aksk(identity_service, "alice")
        result = identity_service.authenticate("not-valid", KNOWN_SECRET_KEY)
        assert result is None

    def test_revoked_aksk_returns_none(self, identity_service: IdentityService) -> None:
        """Revoked AKSK must not authenticate."""
        access_key, secret_key, aksk_id = _create_user_with_aksk(identity_service, "alice")
        identity_service.revoke_aksk(aksk_id)
        result = identity_service.authenticate(access_key, secret_key)
        assert result is None


# ---------------------------------------------------------------------------
# Token Validation
# ---------------------------------------------------------------------------


class TestValidateToken:
    """Tests for validate_token()."""

    def test_valid_token_returns_claims(self, identity_service: IdentityService) -> None:
        """Valid access token must return TokenClaims."""
        access_key, secret_key, _ = _create_user_with_aksk(identity_service, "alice")
        result = identity_service.authenticate(access_key, secret_key)
        claims = identity_service.validate_token(result.access_token)
        assert claims is not None
        assert claims.user_id == "alice"
        assert claims.token_type == "access"

    def test_invalid_token_returns_none(self, identity_service: IdentityService) -> None:
        """Garbage token must return None."""
        assert identity_service.validate_token("garbage") is None

    def test_wrong_key_token_returns_none(self, identity_service: IdentityService) -> None:
        """Token signed with different key must return None."""
        access_key, secret_key, _ = _create_user_with_aksk(identity_service, "alice")
        result = identity_service.authenticate(access_key, secret_key)
        # Re-sign with wrong key
        import jwt

        payload = jwt.decode(result.access_token, TEST_JWT_KEY, algorithms=["HS256"])
        wrong_token = jwt.encode(
            payload, "wrong-key-with-sufficient-length-32b!!", algorithm="HS256"
        )
        assert identity_service.validate_token(wrong_token) is None


# ---------------------------------------------------------------------------
# Token Refresh
# ---------------------------------------------------------------------------


class TestRefreshToken:
    """Tests for refresh_token()."""

    def test_valid_refresh_returns_new_tokens(self, identity_service: IdentityService) -> None:
        """Valid refresh token must return new token pair."""
        access_key, secret_key, _ = _create_user_with_aksk(identity_service, "alice")
        result = identity_service.authenticate(access_key, secret_key)
        refreshed = identity_service.refresh_token(result.refresh_token)
        assert refreshed is not None
        assert refreshed.access_token != result.access_token
        assert refreshed.refresh_token != result.refresh_token
        assert refreshed.expires_in == 3600

    def test_old_refresh_invalid_after_rotation(self, identity_service: IdentityService) -> None:
        """Old refresh token must be invalid after rotation."""
        access_key, secret_key, _ = _create_user_with_aksk(identity_service, "alice")
        result = identity_service.authenticate(access_key, secret_key)
        identity_service.refresh_token(result.refresh_token)
        # Old refresh token should now be revoked
        assert identity_service.validate_token(result.refresh_token) is None

    def test_refresh_with_access_token_returns_none(
        self, identity_service: IdentityService
    ) -> None:
        """Using an access token for refresh must fail."""
        access_key, secret_key, _ = _create_user_with_aksk(identity_service, "alice")
        result = identity_service.authenticate(access_key, secret_key)
        assert identity_service.refresh_token(result.access_token) is None

    def test_refresh_with_invalid_token_returns_none(
        self, identity_service: IdentityService
    ) -> None:
        """Invalid refresh token must return None."""
        assert identity_service.refresh_token("garbage") is None


# ---------------------------------------------------------------------------
# Token Revocation
# ---------------------------------------------------------------------------


class TestTokenRevocation:
    """Tests for revoke_token and revoke_all_tokens."""

    def test_revoke_token_invalidates_it(self, identity_service: IdentityService) -> None:
        """revoke_token must make the token invalid."""
        access_key, secret_key, _ = _create_user_with_aksk(identity_service, "alice")
        result = identity_service.authenticate(access_key, secret_key)
        claims = identity_service.validate_token(result.access_token)
        identity_service.revoke_token(claims.jti)
        assert identity_service.validate_token(result.access_token) is None

    def test_revoke_all_tokens_invalidates_all(self, identity_service: IdentityService) -> None:
        """revoke_all_tokens must invalidate all user tokens."""
        access_key, secret_key, _ = _create_user_with_aksk(identity_service, "alice")
        result = identity_service.authenticate(access_key, secret_key)
        identity_service.revoke_all_tokens("alice")
        assert identity_service.validate_token(result.access_token) is None
        assert identity_service.validate_token(result.refresh_token) is None

    def test_revoke_aksk_cascades_to_tokens(self, identity_service: IdentityService) -> None:
        """Revoking an AKSK must revoke all its tokens."""
        access_key, secret_key, aksk_id = _create_user_with_aksk(identity_service, "alice")
        result = identity_service.authenticate(access_key, secret_key)
        identity_service.revoke_aksk(aksk_id)
        assert identity_service.validate_token(result.access_token) is None
        assert identity_service.validate_token(result.refresh_token) is None


# ---------------------------------------------------------------------------
# Token Listing
# ---------------------------------------------------------------------------


class TestListTokens:
    """Tests for list_tokens()."""

    def test_list_tokens_returns_all(self, identity_service: IdentityService) -> None:
        """list_tokens must return all tokens (access + refresh)."""
        access_key, secret_key, _ = _create_user_with_aksk(identity_service, "alice")
        identity_service.authenticate(access_key, secret_key)
        tokens = identity_service.list_tokens("alice")
        assert len(tokens) >= 2

    def test_list_tokens_active_only(self, identity_service: IdentityService) -> None:
        """list_tokens(active_only=True) must exclude revoked tokens."""
        access_key, secret_key, _ = _create_user_with_aksk(identity_service, "alice")
        identity_service.authenticate(access_key, secret_key)
        identity_service.revoke_all_tokens("alice")
        active = identity_service.list_tokens("alice", active_only=True)
        assert len(active) == 0

    def test_list_tokens_empty(self, identity_service: IdentityService) -> None:
        """list_tokens on user with no tokens returns []."""
        identity_service.create_user("alice")
        assert identity_service.list_tokens("alice") == []


# ---------------------------------------------------------------------------
# External Identity Mapping
# ---------------------------------------------------------------------------


class TestExternalMapping:
    """Tests for map_external_identity, resolve_identity, list_mappings, unmap_external."""

    def test_map_external_returns_mapping(self, identity_service: IdentityService) -> None:
        """map_external_identity must return an ExternalIdentityMapping."""
        identity_service.create_user("alice")
        mapping = identity_service.map_external_identity("telegram", "sender123", "alice")
        assert mapping.channel == "telegram"
        assert mapping.sender_id == "sender123"
        assert mapping.user_id == "alice"

    def test_map_external_nonexistent_user_raises(self, identity_service: IdentityService) -> None:
        """Mapping for non-existent user must raise UserNotFoundError."""
        with pytest.raises(UserNotFoundError):
            identity_service.map_external_identity("telegram", "sender123", "ghost")

    def test_map_external_conflict_raises(self, identity_service: IdentityService) -> None:
        """Duplicate mapping to a different user must raise MappingConflictError."""
        identity_service.create_user("alice")
        identity_service.create_user("bob")
        identity_service.map_external_identity("telegram", "sender123", "alice")
        with pytest.raises(MappingConflictError):
            identity_service.map_external_identity("telegram", "sender123", "bob")

    def test_map_external_same_mapping_idempotent(self, identity_service: IdentityService) -> None:
        """Re-mapping the same (channel, sender) -> same user returns mapping."""
        identity_service.create_user("alice")
        m1 = identity_service.map_external_identity("telegram", "sender123", "alice")
        m2 = identity_service.map_external_identity("telegram", "sender123", "alice")
        assert m1.mapping_id == m2.mapping_id

    def test_resolve_identity_returns_user_id(self, identity_service: IdentityService) -> None:
        """resolve_identity must return the mapped user_id."""
        identity_service.create_user("alice")
        identity_service.map_external_identity("telegram", "sender123", "alice")
        assert identity_service.resolve_identity("telegram", "sender123") == "alice"

    def test_resolve_identity_unmapped_returns_none(
        self, identity_service: IdentityService
    ) -> None:
        """resolve_identity for unmapped sender must return None."""
        assert identity_service.resolve_identity("telegram", "unknown") is None

    def test_list_mappings_all(self, identity_service: IdentityService) -> None:
        """list_mappings() returns all mappings."""
        identity_service.create_user("alice")
        identity_service.map_external_identity("telegram", "s1", "alice")
        identity_service.map_external_identity("feishu", "s2", "alice")
        assert len(identity_service.list_mappings()) == 2

    def test_list_mappings_by_channel(self, identity_service: IdentityService) -> None:
        """list_mappings(channel=...) filters by channel."""
        identity_service.create_user("alice")
        identity_service.map_external_identity("telegram", "s1", "alice")
        identity_service.map_external_identity("feishu", "s2", "alice")
        result = identity_service.list_mappings(channel="telegram")
        assert len(result) == 1
        assert result[0].channel == "telegram"

    def test_list_mappings_by_user(self, identity_service: IdentityService) -> None:
        """list_mappings(user_id=...) filters by user."""
        identity_service.create_user("alice")
        identity_service.create_user("bob")
        identity_service.map_external_identity("telegram", "s1", "alice")
        identity_service.map_external_identity("feishu", "s2", "bob")
        result = identity_service.list_mappings(user_id="alice")
        assert len(result) == 1
        assert result[0].user_id == "alice"

    def test_unmap_external_removes_mapping(self, identity_service: IdentityService) -> None:
        """unmap_external must remove the mapping."""
        identity_service.create_user("alice")
        identity_service.map_external_identity("telegram", "sender123", "alice")
        identity_service.unmap_external("telegram", "sender123")
        assert identity_service.resolve_identity("telegram", "sender123") is None

    def test_unmap_external_nonexistent_raises(self, identity_service: IdentityService) -> None:
        """Unmapping a non-existent mapping must raise MappingNotFoundError."""
        with pytest.raises(MappingNotFoundError):
            identity_service.unmap_external("telegram", "ghost")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class TestGetStatus:
    """Tests for get_status()."""

    def test_enabled_status(self, identity_service: IdentityService) -> None:
        """get_status must return enabled=True."""
        status = identity_service.get_status()
        assert status.enabled is True

    def test_counts_after_setup(self, identity_service: IdentityService) -> None:
        """Counts must reflect created users and AKSKs."""
        _create_user_with_aksk(identity_service, "alice")
        status = identity_service.get_status()
        assert status.users_count == 1
        assert status.active_aksk_count == 1
        assert status.active_tokens_count == 0

    def test_counts_after_auth(self, identity_service: IdentityService) -> None:
        """Active tokens count must increase after authentication."""
        access_key, secret_key, _ = _create_user_with_aksk(identity_service, "alice")
        identity_service.authenticate(access_key, secret_key)
        status = identity_service.get_status()
        assert status.active_tokens_count >= 2  # access + refresh

    def test_storage_backend_is_sqlite(self, identity_service: IdentityService) -> None:
        """Storage backend must be 'sqlite'."""
        status = identity_service.get_status()
        assert status.storage_backend == "sqlite"

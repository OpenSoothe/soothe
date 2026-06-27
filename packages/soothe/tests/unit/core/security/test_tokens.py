"""Unit tests for JWT token management (RFC-307 §TokenClaims).

Tests JWTManager: access/refresh token generation, validation, expiry, and key resolution.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest

from soothe.foundation.identity.models import TokenClaims
from soothe.foundation.identity.tokens import (
    JWTManager,
    generate_jwt_key,
    resolve_jwt_key,
    save_jwt_key,
)

TEST_KEY = "test-secret-key-for-testing-only-256bit!!"
USER_ID = "test-user"
AKSK_ID = "test-aksk-id"


# ---------------------------------------------------------------------------
# JWTManager.__init__
# ---------------------------------------------------------------------------


class TestJWTManagerInit:
    """Tests for JWTManager initialization."""

    def test_default_expiry_values(self) -> None:
        """Default expiry: 1 hour access, 7 days refresh."""
        mgr = JWTManager(signing_key=TEST_KEY)
        assert mgr.access_expiry_hours == 1
        assert mgr.refresh_expiry_days == 7

    def test_custom_expiry_values(self) -> None:
        """Custom expiry values are stored."""
        mgr = JWTManager(
            signing_key=TEST_KEY,
            access_expiry_hours=12,
            refresh_expiry_days=30,
        )
        assert mgr.access_expiry_hours == 12
        assert mgr.refresh_expiry_days == 30

    def test_signing_key_stored(self) -> None:
        """Signing key is stored."""
        mgr = JWTManager(signing_key=TEST_KEY)
        assert mgr.signing_key == TEST_KEY


# ---------------------------------------------------------------------------
# JWTManager.generate_access_token
# ---------------------------------------------------------------------------


class TestGenerateAccessToken:
    """Tests for generate_access_token()."""

    def test_returns_token_and_claims(self) -> None:
        """Must return a tuple of (token_str, TokenClaims)."""
        mgr = JWTManager(signing_key=TEST_KEY)
        result = mgr.generate_access_token(USER_ID, AKSK_ID)
        assert isinstance(result, tuple)
        assert len(result) == 2
        token, claims = result
        assert isinstance(token, str)
        assert isinstance(claims, TokenClaims)

    def test_claims_contain_correct_user_and_aksk(self) -> None:
        """Claims must have the provided user_id and aksk_id."""
        mgr = JWTManager(signing_key=TEST_KEY)
        _, claims = mgr.generate_access_token(USER_ID, AKSK_ID)
        assert claims.user_id == USER_ID
        assert claims.aksk_id == AKSK_ID

    def test_claims_token_type_is_access(self) -> None:
        """Access token claims must have token_type='access'."""
        mgr = JWTManager(signing_key=TEST_KEY)
        _, claims = mgr.generate_access_token(USER_ID, AKSK_ID)
        assert claims.token_type == "access"

    def test_claims_have_jti(self) -> None:
        """Claims must have a non-empty jti (JWT ID)."""
        mgr = JWTManager(signing_key=TEST_KEY)
        _, claims = mgr.generate_access_token(USER_ID, AKSK_ID)
        assert claims.jti
        assert len(claims.jti) > 0

    def test_claims_have_timestamps(self) -> None:
        """Claims must have issued_at and expires_at."""
        mgr = JWTManager(signing_key=TEST_KEY)
        _, claims = mgr.generate_access_token(USER_ID, AKSK_ID)
        assert claims.issued_at is not None
        assert claims.expires_at is not None

    def test_expiry_is_one_hour_ahead(self) -> None:
        """Expiry must be approximately 1 hour after issue time."""
        mgr = JWTManager(signing_key=TEST_KEY, access_expiry_hours=1)
        _, claims = mgr.generate_access_token(USER_ID, AKSK_ID)
        delta = claims.expires_at - claims.issued_at
        assert abs(delta - timedelta(hours=1)) < timedelta(seconds=5)

    def test_custom_expiry_hours(self) -> None:
        """Custom expiry hours are reflected in claims."""
        mgr = JWTManager(signing_key=TEST_KEY, access_expiry_hours=6)
        _, claims = mgr.generate_access_token(USER_ID, AKSK_ID)
        delta = claims.expires_at - claims.issued_at
        assert abs(delta - timedelta(hours=6)) < timedelta(seconds=5)

    def test_token_decodes_with_correct_claims(self) -> None:
        """JWT token must decode to correct payload."""
        mgr = JWTManager(signing_key=TEST_KEY)
        token, claims = mgr.generate_access_token(USER_ID, AKSK_ID)
        payload = jwt.decode(token, TEST_KEY, algorithms=["HS256"])
        assert payload["sub"] == USER_ID
        assert payload["aksk_id"] == AKSK_ID
        assert payload["typ"] == "access"
        assert payload["jti"] == claims.jti

    def test_different_calls_produce_different_jtis(self) -> None:
        """Each call must produce a unique jti."""
        mgr = JWTManager(signing_key=TEST_KEY)
        _, claims1 = mgr.generate_access_token(USER_ID, AKSK_ID)
        _, claims2 = mgr.generate_access_token(USER_ID, AKSK_ID)
        assert claims1.jti != claims2.jti


# ---------------------------------------------------------------------------
# JWTManager.generate_refresh_token
# ---------------------------------------------------------------------------


class TestGenerateRefreshToken:
    """Tests for generate_refresh_token()."""

    def test_returns_token_and_claims(self) -> None:
        """Must return a tuple of (token_str, TokenClaims)."""
        mgr = JWTManager(signing_key=TEST_KEY)
        result = mgr.generate_refresh_token(USER_ID, AKSK_ID)
        assert isinstance(result, tuple)
        token, claims = result
        assert isinstance(token, str)
        assert isinstance(claims, TokenClaims)

    def test_claims_token_type_is_refresh(self) -> None:
        """Refresh token claims must have token_type='refresh'."""
        mgr = JWTManager(signing_key=TEST_KEY)
        _, claims = mgr.generate_refresh_token(USER_ID, AKSK_ID)
        assert claims.token_type == "refresh"

    def test_expiry_is_seven_days_ahead(self) -> None:
        """Refresh expiry must be approximately 7 days after issue."""
        mgr = JWTManager(signing_key=TEST_KEY, refresh_expiry_days=7)
        _, claims = mgr.generate_refresh_token(USER_ID, AKSK_ID)
        delta = claims.expires_at - claims.issued_at
        assert abs(delta - timedelta(days=7)) < timedelta(seconds=5)

    def test_custom_expiry_days(self) -> None:
        """Custom refresh expiry days are reflected in claims."""
        mgr = JWTManager(signing_key=TEST_KEY, refresh_expiry_days=30)
        _, claims = mgr.generate_refresh_token(USER_ID, AKSK_ID)
        delta = claims.expires_at - claims.issued_at
        assert abs(delta - timedelta(days=30)) < timedelta(seconds=5)

    def test_refresh_token_decodes_correctly(self) -> None:
        """Refresh JWT must decode to correct payload."""
        mgr = JWTManager(signing_key=TEST_KEY)
        token, claims = mgr.generate_refresh_token(USER_ID, AKSK_ID)
        payload = jwt.decode(token, TEST_KEY, algorithms=["HS256"])
        assert payload["typ"] == "refresh"
        assert payload["sub"] == USER_ID
        assert payload["jti"] == claims.jti

    def test_refresh_token_longer_lived_than_access(self) -> None:
        """Refresh token must expire later than access token."""
        mgr = JWTManager(signing_key=TEST_KEY)
        _, access_claims = mgr.generate_access_token(USER_ID, AKSK_ID)
        _, refresh_claims = mgr.generate_refresh_token(USER_ID, AKSK_ID)
        assert refresh_claims.expires_at > access_claims.expires_at


# ---------------------------------------------------------------------------
# JWTManager.validate_token
# ---------------------------------------------------------------------------


class TestValidateToken:
    """Tests for validate_token()."""

    def test_valid_token_returns_claims(self) -> None:
        """A valid token must return TokenClaims."""
        mgr = JWTManager(signing_key=TEST_KEY)
        token, _ = mgr.generate_access_token(USER_ID, AKSK_ID)
        claims = mgr.validate_token(token)
        assert claims is not None
        assert claims.user_id == USER_ID
        assert claims.aksk_id == AKSK_ID
        assert claims.token_type == "access"

    def test_invalid_token_returns_none(self) -> None:
        """A garbage string must return None."""
        mgr = JWTManager(signing_key=TEST_KEY)
        assert mgr.validate_token("not.a.valid.token") is None

    def test_wrong_signing_key_returns_none(self) -> None:
        """Token signed with different key must return None."""
        mgr1 = JWTManager(signing_key=TEST_KEY)
        mgr2 = JWTManager(signing_key="different-key-xxxxxxxxxxxxxxxxxxxxx")
        token, _ = mgr1.generate_access_token(USER_ID, AKSK_ID)
        assert mgr2.validate_token(token) is None

    def test_expired_token_returns_none(self) -> None:
        """An expired token must return None."""
        mgr = JWTManager(signing_key=TEST_KEY, access_expiry_hours=1)
        token, _ = mgr.generate_access_token(USER_ID, AKSK_ID)

        # Decode without verification, patch exp to past, re-encode
        payload = jwt.decode(token, TEST_KEY, algorithms=["HS256"])
        payload["exp"] = int((datetime.now(UTC) - timedelta(hours=2)).timestamp())
        expired_token = jwt.encode(payload, TEST_KEY, algorithm="HS256")

        assert mgr.validate_token(expired_token) is None

    def test_validates_refresh_token(self) -> None:
        """Refresh tokens can also be validated."""
        mgr = JWTManager(signing_key=TEST_KEY)
        token, _ = mgr.generate_refresh_token(USER_ID, AKSK_ID)
        claims = mgr.validate_token(token)
        assert claims is not None
        assert claims.token_type == "refresh"

    def test_empty_string_returns_none(self) -> None:
        """Empty string must return None."""
        mgr = JWTManager(signing_key=TEST_KEY)
        assert mgr.validate_token("") is None


# ---------------------------------------------------------------------------
# JWTManager.get_token_expiry_seconds
# ---------------------------------------------------------------------------


class TestGetTokenExpirySeconds:
    """Tests for get_token_expiry_seconds()."""

    def test_default_one_hour(self) -> None:
        """Default: 1 hour = 3600 seconds."""
        mgr = JWTManager(signing_key=TEST_KEY)
        assert mgr.get_token_expiry_seconds() == 3600

    def test_custom_hours(self) -> None:
        """Custom hours converted to seconds."""
        mgr = JWTManager(signing_key=TEST_KEY, access_expiry_hours=6)
        assert mgr.get_token_expiry_seconds() == 6 * 3600


# ---------------------------------------------------------------------------
# resolve_jwt_key
# ---------------------------------------------------------------------------


class TestResolveJwtKey:
    """Tests for resolve_jwt_key()."""

    def test_env_var_takes_priority(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SOOTHE_JWT_KEY env var has highest priority."""
        monkeypatch.setenv("SOOTHE_JWT_KEY", "env-key")
        assert resolve_jwt_key("config-key") == "env-key"

    def test_config_key_used_when_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Config key is used when env var is absent."""
        monkeypatch.delenv("SOOTHE_JWT_KEY", raising=False)
        assert resolve_jwt_key("config-key") == "config-key"

    def test_file_key_used_when_no_env_or_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """File key is used when env and config are absent."""
        monkeypatch.delenv("SOOTHE_JWT_KEY", raising=False)
        key_file = tmp_path / ".jwt_key"
        key_file.write_text("file-key")
        monkeypatch.setenv("SOOTHE_HOME", str(tmp_path))
        assert resolve_jwt_key(None) == "file-key"

    def test_returns_none_when_no_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when no key source is available."""
        monkeypatch.delenv("SOOTHE_JWT_KEY", raising=False)
        monkeypatch.delenv("SOOTHE_HOME", raising=False)
        assert resolve_jwt_key(None) is None

    def test_env_var_overrides_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Env var takes priority over file."""
        monkeypatch.setenv("SOOTHE_JWT_KEY", "env-key")
        key_file = tmp_path / ".jwt_key"
        key_file.write_text("file-key")
        monkeypatch.setenv("SOOTHE_HOME", str(tmp_path))
        assert resolve_jwt_key(None) == "env-key"


# ---------------------------------------------------------------------------
# generate_jwt_key
# ---------------------------------------------------------------------------


class TestGenerateJwtKey:
    """Tests for generate_jwt_key()."""

    def test_returns_non_empty_string(self) -> None:
        """Generated key must be non-empty."""
        key = generate_jwt_key()
        assert key
        assert len(key) > 0

    def test_generates_unique_keys(self) -> None:
        """Two calls should produce different keys."""
        keys = {generate_jwt_key() for _ in range(100)}
        assert len(keys) == 100

    def test_key_is_url_safe(self) -> None:
        """Key must be URL-safe base64."""
        key = generate_jwt_key()
        # token_urlsafe output only contains [A-Za-z0-9_-]
        assert all(c.isalnum() or c in ("-", "_") for c in key)


# ---------------------------------------------------------------------------
# save_jwt_key
# ---------------------------------------------------------------------------


class TestSaveJwtKey:
    """Tests for save_jwt_key()."""

    def test_saves_key_to_file(self, tmp_path: Path) -> None:
        """Key is written to .jwt_key file."""
        key = "my-secret-key"
        result = save_jwt_key(key, str(tmp_path))
        assert result == tmp_path / ".jwt_key"
        assert result.read_text() == key

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        """Parent directories are created if needed."""
        key = "my-secret-key"
        nested = tmp_path / "nested" / "dir"
        result = save_jwt_key(key, str(nested))
        assert result.exists()

    def test_file_permissions_secure(self, tmp_path: Path) -> None:
        """File must have 0600 permissions (owner read/write only)."""
        key = "my-secret-key"
        result = save_jwt_key(key, str(tmp_path))
        mode = result.stat().st_mode & 0o777
        assert mode == 0o600

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        """Existing file is overwritten."""
        save_jwt_key("old-key", str(tmp_path))
        result = save_jwt_key("new-key", str(tmp_path))
        assert result.read_text() == "new-key"

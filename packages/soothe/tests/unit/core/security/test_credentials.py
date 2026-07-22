"""Unit tests for credentials module (RFC-307 §AKSKPair).

Tests AKSK credential generation, hashing, validation, and format checking.
"""

from __future__ import annotations

import hashlib
import re
import uuid

from soothe.identity.credentials import (
    ACCESS_KEY_LENGTH,
    ACCESS_KEY_PREFIX,
    SECRET_KEY_LENGTH,
    SECRET_KEY_PREFIX,
    generate_access_key,
    generate_aksk_id,
    generate_secret_key,
    hash_secret_key,
    is_valid_access_key_format,
    is_valid_secret_key_format,
    verify_secret_key,
)

# ---------------------------------------------------------------------------
# generate_access_key
# ---------------------------------------------------------------------------


class TestGenerateAccessKey:
    """Tests for generate_access_key()."""

    def test_returns_string_with_ak_prefix(self) -> None:
        """Access key must start with 'AK-'."""
        key = generate_access_key()
        assert key.startswith(f"{ACCESS_KEY_PREFIX}-")

    def test_correct_total_length(self) -> None:
        """Total length must be prefix + dash + ACCESS_KEY_LENGTH."""
        key = generate_access_key()
        assert len(key) == len(ACCESS_KEY_PREFIX) + 1 + ACCESS_KEY_LENGTH

    def test_random_part_is_url_safe(self) -> None:
        """Characters after prefix must be URL-safe base64."""
        key = generate_access_key()
        chars = key[len(ACCESS_KEY_PREFIX) + 1 :]
        assert re.match(r"^[A-Za-z0-9_-]+$", chars)

    def test_generates_unique_keys(self) -> None:
        """Two calls should produce different keys (probabilistic)."""
        keys = {generate_access_key() for _ in range(100)}
        assert len(keys) == 100

    def test_generated_key_passes_format_validation(self) -> None:
        """Generated key must pass is_valid_access_key_format()."""
        key = generate_access_key()
        assert is_valid_access_key_format(key)


# ---------------------------------------------------------------------------
# generate_secret_key
# ---------------------------------------------------------------------------


class TestGenerateSecretKey:
    """Tests for generate_secret_key()."""

    def test_returns_string_with_sk_prefix(self) -> None:
        """Secret key must start with 'SK-'."""
        key = generate_secret_key()
        assert key.startswith(f"{SECRET_KEY_PREFIX}-")

    def test_correct_total_length(self) -> None:
        """Total length must be prefix + dash + SECRET_KEY_LENGTH."""
        key = generate_secret_key()
        assert len(key) == len(SECRET_KEY_PREFIX) + 1 + SECRET_KEY_LENGTH

    def test_random_part_is_url_safe(self) -> None:
        """Characters after prefix must be URL-safe base64."""
        key = generate_secret_key()
        chars = key[len(SECRET_KEY_PREFIX) + 1 :]
        assert re.match(r"^[A-Za-z0-9_-]+$", chars)

    def test_generates_unique_keys(self) -> None:
        """Two calls should produce different keys (probabilistic)."""
        keys = {generate_secret_key() for _ in range(100)}
        assert len(keys) == 100

    def test_generated_key_passes_format_validation(self) -> None:
        """Generated key must pass is_valid_secret_key_format()."""
        key = generate_secret_key()
        assert is_valid_secret_key_format(key)


# ---------------------------------------------------------------------------
# hash_secret_key
# ---------------------------------------------------------------------------


class TestHashSecretKey:
    """Tests for hash_secret_key()."""

    def test_returns_sha256_hex_digest(self) -> None:
        """Hash must be a 64-char hex string (SHA-256)."""
        secret = "SK-abcdefghijklmnopqrstuvwxyz012345"
        h = hash_secret_key(secret)
        assert len(h) == 64
        assert re.match(r"^[0-9a-f]{64}$", h)

    def test_matches_manual_sha256(self) -> None:
        """Hash must match hashlib.sha256 of the UTF-8 encoded key."""
        secret = "SK-test1234567890abcdefghijklmnopqrstuv"
        expected = hashlib.sha256(secret.encode()).hexdigest()
        assert hash_secret_key(secret) == expected

    def test_deterministic_for_same_input(self) -> None:
        """Same input must produce same hash."""
        secret = "SK-test1234567890abcdefghijklmnopqrstuv"
        assert hash_secret_key(secret) == hash_secret_key(secret)

    def test_different_inputs_produce_different_hashes(self) -> None:
        """Different inputs must produce different hashes."""
        h1 = hash_secret_key("SK-abcdefghijklmnopqrstuvwxyz012345")
        h2 = hash_secret_key("SK-abcdefghijklmnopqrstuv0123456")
        assert h1 != h2

    def test_does_not_leak_plaintext(self) -> None:
        """Hash must not contain the plaintext key."""
        secret = "SK-abcdefghijklmnopqrstuvwxyz012345"
        h = hash_secret_key(secret)
        assert secret not in h


# ---------------------------------------------------------------------------
# verify_secret_key
# ---------------------------------------------------------------------------


class TestVerifySecretKey:
    """Tests for verify_secret_key()."""

    def test_valid_secret_matches_hash(self) -> None:
        """Correct secret key must verify against its hash."""
        secret = "SK-abcdefghijklmnopqrstuvwxyz012345"
        h = hash_secret_key(secret)
        assert verify_secret_key(secret, h) is True

    def test_wrong_secret_does_not_match(self) -> None:
        """Wrong secret key must not verify."""
        secret = "SK-abcdefghijklmnopqrstuvwxyz012345"
        h = hash_secret_key(secret)
        assert verify_secret_key("SK-wrong1234567890abcdefghijklmnopqrstuv", h) is False

    def test_constant_time_comparison(self) -> None:
        """verify_secret_key uses hmac.compare_digest (no exception on mismatch)."""
        # Should not raise even with mismatched lengths
        assert verify_secret_key("short", "a" * 64) is False

    def test_empty_secret_returns_false(self) -> None:
        """Empty secret must not verify against a real hash."""
        h = hash_secret_key("SK-abcdefghijklmnopqrstuvwxyz012345")
        assert verify_secret_key("", h) is False


# ---------------------------------------------------------------------------
# generate_aksk_id
# ---------------------------------------------------------------------------


class TestGenerateAkskId:
    """Tests for generate_aksk_id()."""

    def test_returns_valid_uuid_string(self) -> None:
        """AKSK ID must be a valid UUID string."""
        aksk_id = generate_aksk_id()
        # Should not raise
        uuid.UUID(aksk_id)

    def test_generates_unique_ids(self) -> None:
        """Two calls should produce different IDs."""
        ids = {generate_aksk_id() for _ in range(100)}
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# is_valid_access_key_format
# ---------------------------------------------------------------------------


class TestIsValidAccessKeyFormat:
    """Tests for is_valid_access_key_format()."""

    def test_valid_key_returns_true(self) -> None:
        """A properly formatted access key must be valid."""
        key = "AK-abcdefghijklmno0"
        assert is_valid_access_key_format(key) is True

    def test_generated_key_is_valid(self) -> None:
        """A generated key must pass validation."""
        assert is_valid_access_key_format(generate_access_key()) is True

    def test_empty_string_returns_false(self) -> None:
        """Empty string must be invalid."""
        assert is_valid_access_key_format("") is False

    def test_wrong_prefix_returns_false(self) -> None:
        """Key without 'AK-' prefix must be invalid."""
        assert is_valid_access_key_format("BK-abcdefghijklmno0") is False

    def test_too_short_returns_false(self) -> None:
        """Key shorter than expected must be invalid."""
        assert is_valid_access_key_format("AK-short") is False

    def test_too_long_returns_false(self) -> None:
        """Key longer than expected must be invalid."""
        assert is_valid_access_key_format("AK-abcdefghijklmnopqrstuvwxyz0123456789") is False

    def test_invalid_chars_returns_false(self) -> None:
        """Key with non-URL-safe characters must be invalid."""
        # Exactly 16 chars but with invalid characters
        assert is_valid_access_key_format("AK-abcdefghij!mno0") is False

    def test_no_dash_returns_false(self) -> None:
        """Key without dash separator must be invalid."""
        assert is_valid_access_key_format("AKabcdefghijklmno0") is False


# ---------------------------------------------------------------------------
# is_valid_secret_key_format
# ---------------------------------------------------------------------------


class TestIsValidSecretKeyFormat:
    """Tests for is_valid_secret_key_format()."""

    def test_valid_key_returns_true(self) -> None:
        """A properly formatted secret key must be valid."""
        key = "SK-abcdefghijklmnopqrstuvwxyz012345"
        assert is_valid_secret_key_format(key) is True

    def test_generated_key_is_valid(self) -> None:
        """A generated key must pass validation."""
        assert is_valid_secret_key_format(generate_secret_key()) is True

    def test_empty_string_returns_false(self) -> None:
        """Empty string must be invalid."""
        assert is_valid_secret_key_format("") is False

    def test_wrong_prefix_returns_false(self) -> None:
        """Key without 'SK-' prefix must be invalid."""
        assert is_valid_secret_key_format("AK-abcdefghijklmnopqrstuvwxyz012345") is False

    def test_too_short_returns_false(self) -> None:
        """Key shorter than expected must be invalid."""
        assert is_valid_secret_key_format("SK-short") is False

    def test_too_long_returns_false(self) -> None:
        """Key longer than expected must be invalid."""
        assert is_valid_secret_key_format("SK-abcdefghijklmnopqrstuvwxyz0123456789") is False

    def test_invalid_chars_returns_false(self) -> None:
        """Key with non-URL-safe characters must be invalid."""
        assert is_valid_secret_key_format("SK-abcdefghijklmnopqrstuvwxyz0!2345") is False

    def test_no_dash_returns_false(self) -> None:
        """Key without dash separator must be invalid."""
        assert is_valid_secret_key_format("SKabcdefghijklmnopqrstuvwxyz012345") is False

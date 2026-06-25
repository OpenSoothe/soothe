"""AKSK credential generation and hashing. RFC-307 §AKSKPair."""

import hashlib
import hmac
import secrets


# AKSK format constants
ACCESS_KEY_PREFIX = "AK"
"""Access key prefix."""
ACCESS_KEY_LENGTH = 16
"""Access key random chars length."""
SECRET_KEY_PREFIX = "SK"
"""Secret key prefix."""
SECRET_KEY_LENGTH = 32
"""Secret key random chars length."""


def generate_access_key() -> str:
    """
    Generate access key with format: AK-{16 chars}.

    Uses secrets.token_urlsafe for cryptographic randomness.

    Returns:
        Access key string (e.g., "AK-x7k2m9p4q1w8")

    RFC-307 §AKSKPair format.
    """
    random_chars = secrets.token_urlsafe(12)[:ACCESS_KEY_LENGTH]
    return f"{ACCESS_KEY_PREFIX}-{random_chars}"


def generate_secret_key() -> str:
    """
    Generate secret key with format: SK-{32 chars}.

    Uses secrets.token_urlsafe for cryptographic randomness.

    Returns:
        Secret key string (e.g., "SK-a1b2c3d4e5f6g7h8...")

    RFC-307 §AKSKPair format.
    """
    random_chars = secrets.token_urlsafe(24)[:SECRET_KEY_LENGTH]
    return f"{SECRET_KEY_PREFIX}-{random_chars}"


def hash_secret_key(secret_key: str) -> str:
    """
    Hash secret key for storage using SHA-256.

    The plaintext secret_key is never stored in the database.
    Only the SHA-256 hash is stored for verification.

    Args:
        secret_key: Plaintext secret key (SK-{32 chars})

    Returns:
        SHA-256 hex digest string (64 chars)

    RFC-307 §Security Checklist.
    """
    return hashlib.sha256(secret_key.encode()).hexdigest()


def verify_secret_key(secret_key: str, hash_value: str) -> bool:
    """
    Verify secret key against stored hash.

    Uses hmac.compare_digest for constant-time comparison to prevent
    timing attacks. This is critical for security.

    Args:
        secret_key: Plaintext secret key to verify
        hash_value: Stored SHA-256 hash from database

    Returns:
        True if secret_key matches hash, False otherwise

    RFC-307 §Security Checklist (constant-time comparison).
    """
    expected_hash = hash_secret_key(secret_key)
    # hmac.compare_digest provides constant-time comparison
    # to prevent timing attacks on credential verification
    return hmac.compare_digest(expected_hash.encode(), hash_value.encode())


def generate_aksk_id() -> str:
    """
    Generate AKSK ID (UUID for internal reference).

    Used for revocation tracking and token association.

    Returns:
        UUID string
    """
    import uuid

    return str(uuid.uuid4())


def is_valid_access_key_format(access_key: str) -> bool:
    """
    Validate access key format.

    Args:
        access_key: Access key to validate

    Returns:
        True if format is valid (AK-{16 chars}), False otherwise
    """
    if not access_key:
        return False
    if not access_key.startswith(f"{ACCESS_KEY_PREFIX}-"):
        return False
    # Check length: AK- (3 chars) + 16 chars = 19 total
    if len(access_key) != len(ACCESS_KEY_PREFIX) + 1 + ACCESS_KEY_LENGTH:
        return False
    # Validate characters after prefix are URL-safe base64 chars
    chars = access_key[len(ACCESS_KEY_PREFIX) + 1 :]
    for c in chars:
        if not (c.isalnum() or c in ("-", "_")):
            return False
    return True


def is_valid_secret_key_format(secret_key: str) -> bool:
    """
    Validate secret key format.

    Args:
        secret_key: Secret key to validate

    Returns:
        True if format is valid (SK-{32 chars}), False otherwise
    """
    if not secret_key:
        return False
    if not secret_key.startswith(f"{SECRET_KEY_PREFIX}-"):
        return False
    # Check length: SK- (3 chars) + 32 chars = 35 total
    if len(secret_key) != len(SECRET_KEY_PREFIX) + 1 + SECRET_KEY_LENGTH:
        return False
    # Validate characters after prefix are URL-safe base64 chars
    chars = secret_key[len(SECRET_KEY_PREFIX) + 1 :]
    for c in chars:
        if not (c.isalnum() or c in ("-", "_")):
            return False
    return True

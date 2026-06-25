"""JWT token generation and validation. RFC-307 §TokenClaims."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt

from soothe.core.security.models import TokenClaims


class JWTManager:
    """
    JWT token generation and validation.

    Uses HS256 (HMAC-SHA256) algorithm for signing.
    Access tokens are short-lived (1 hour default).
    Refresh tokens are longer-lived (7 days default).

    RFC-307 §TokenClaims, §Authentication Flow.
    """

    def __init__(
        self,
        signing_key: str,
        access_expiry_hours: int = 1,
        refresh_expiry_days: int = 7,
    ) -> None:
        """
        Initialize JWT manager.

        Args:
            signing_key: Secret key for JWT signing (256-bit recommended)
            access_expiry_hours: Access token expiry in hours (1-24)
            refresh_expiry_days: Refresh token expiry in days (1-365)

        RFC-307 §Configuration (token settings).
        """
        self.signing_key = signing_key
        self.access_expiry_hours = access_expiry_hours
        self.refresh_expiry_days = refresh_expiry_days

    def generate_access_token(
        self,
        user_id: str,
        aksk_id: str,
    ) -> tuple[str, TokenClaims]:
        """
        Generate access token (short-lived).

        Access tokens are used for API authentication and have
        short expiry to minimize exposure window if compromised.

        Args:
            user_id: Soothe user identifier
            aksk_id: AKSK that issued this token

        Returns:
            Tuple of (JWT token string, TokenClaims)

        RFC-307 §JWT payload structure.
        """
        now = datetime.now(UTC)
        expiry = now + timedelta(hours=self.access_expiry_hours)
        jti = str(uuid.uuid4())

        payload = {
            "jti": jti,
            "sub": user_id,
            "aksk_id": aksk_id,
            "typ": "access",
            "iat": int(now.timestamp()),
            "exp": int(expiry.timestamp()),
        }

        token = jwt.encode(payload, self.signing_key, algorithm="HS256")
        claims = TokenClaims(
            jti=jti,
            user_id=user_id,
            aksk_id=aksk_id,
            token_type="access",
            issued_at=now,
            expires_at=expiry,
        )
        return token, claims

    def generate_refresh_token(
        self,
        user_id: str,
        aksk_id: str,
    ) -> tuple[str, TokenClaims]:
        """
        Generate refresh token (longer-lived).

        Refresh tokens are used to obtain new access tokens
        and are revoked after each use (rotation pattern).

        Args:
            user_id: Soothe user identifier
            aksk_id: AKSK that issued this token

        Returns:
            Tuple of (JWT token string, TokenClaims)

        RFC-307 §JWT payload structure.
        """
        now = datetime.now(UTC)
        expiry = now + timedelta(days=self.refresh_expiry_days)
        jti = str(uuid.uuid4())

        payload = {
            "jti": jti,
            "sub": user_id,
            "aksk_id": aksk_id,
            "typ": "refresh",
            "iat": int(now.timestamp()),
            "exp": int(expiry.timestamp()),
        }

        token = jwt.encode(payload, self.signing_key, algorithm="HS256")
        claims = TokenClaims(
            jti=jti,
            user_id=user_id,
            aksk_id=aksk_id,
            token_type="refresh",
            issued_at=now,
            expires_at=expiry,
        )
        return token, claims

    def validate_token(self, token: str) -> TokenClaims | None:
        """
        Validate JWT token signature and expiry.

        This method validates JWT signature and expiry ONLY.
        Revocation checking is done by IdentityService.validate_token()
        which calls this method and then checks revoked_jtis table.

        Args:
            token: JWT token string

        Returns:
            TokenClaims if valid, None if invalid or expired

        RFC-307 §Authentication Flow (JWT validation).
        """
        try:
            payload = jwt.decode(
                token,
                self.signing_key,
                algorithms=["HS256"],
            )
            return TokenClaims(
                jti=payload["jti"],
                user_id=payload["sub"],
                aksk_id=payload["aksk_id"],
                token_type=payload["typ"],
                issued_at=datetime.fromtimestamp(payload["iat"], tz=UTC),
                expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
            )
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    def get_token_expiry_seconds(self) -> int:
        """
        Get access token expiry in seconds.

        Used for expires_in field in auth_response.

        Returns:
            Expiry duration in seconds
        """
        return self.access_expiry_hours * 3600


def resolve_jwt_key(config_jwt_key: str | None = None) -> str | None:
    """
    Resolve JWT signing key from multiple sources.

    Priority order:
    1. Environment variable: SOOTHE_JWT_KEY
    2. Config value: identity.tokens.jwt_signing_key
    3. Auto-generated file: $SOOTHE_HOME/.jwt_key

    Args:
        config_jwt_key: JWT key from config file (optional)

    Returns:
        JWT signing key, or None if not available

    RFC-307 §JWT key resolution.
    """
    import os
    from pathlib import Path

    # Priority 1: Environment variable
    key = os.environ.get("SOOTHE_JWT_KEY")
    if key:
        return key

    # Priority 2: Config value
    if config_jwt_key:
        return config_jwt_key

    # Priority 3: Auto-generated file
    soothe_home = os.environ.get("SOOTHE_HOME")
    if soothe_home:
        key_file = Path(soothe_home) / ".jwt_key"
        if key_file.exists():
            return key_file.read_text().strip()

    return None


def generate_jwt_key() -> str:
    """
    Generate a new JWT signing key.

    Creates a 256-bit key suitable for HS256 algorithm.

    Returns:
        URL-safe base64 encoded key string

    RFC-307 §JWT key auto-generation.
    """
    import secrets

    return secrets.token_urlsafe(32)  # 256-bit key


def save_jwt_key(key: str, soothe_home: str) -> Path:
    """
    Save JWT key to file for persistence.

    Key file is stored at $SOOTHE_HOME/.jwt_key with
    secure permissions (0600).

    Args:
        key: JWT signing key
        soothe_home: SOOTHE_HOME directory path

    Returns:
        Path to key file

    RFC-307 §JWT key auto-generation.
    """
    key_file = Path(soothe_home) / ".jwt_key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key)
    # Set secure permissions: owner read/write only
    key_file.chmod(0o600)
    return key_file

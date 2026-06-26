"""WebSocket auth message handler. RFC-307 §WebSocket Message Types.

Handles auth and auth_refresh WebSocket messages for AKSK-based
authentication and token renewal.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe_sdk.protocols.identity import IdentityProtocol

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


class AuthHandler:
    """Handle WebSocket auth/auth_refresh messages.

    RFC-307 §Authentication Flow.

    This handler processes:
    - auth: AKSK credentials → access_token + refresh_token
    - auth_refresh: refresh_token → new access_token + refresh_token

    Messages are processed before IdentityMiddleware validation.
    """

    def __init__(self, identity: IdentityProtocol) -> None:
        """Initialize AuthHandler.

        Args:
            identity: IdentityProtocol implementation for authentication.
        """
        self._identity = identity

    def handle_auth(
        self,
        access_key: str,
        secret_key: str,
    ) -> dict:
        """Process auth message with AKSK credentials.

        RFC-307 §WebSocket AKSK Flow.

        Args:
            access_key: Access key (AK-{16 chars}).
            secret_key: Secret key (SK-{32 chars}).

        Returns:
            auth_response message dict with success/error.
        """
        logger.debug("Processing auth request: access_key=%s", access_key[:6] + "...")

        result = self._identity.authenticate(access_key, secret_key)

        if result is None:
            logger.warning("Authentication failed: invalid credentials")
            return {
                "type": "auth_response",
                "success": False,
                "error": "invalid_credentials",
                "message": "Access key or secret key is invalid",
            }

        logger.info(
            "Authentication successful: user=%s expires_in=%ds",
            result.user_id,
            result.expires_in,
        )

        return {
            "type": "auth_response",
            "success": True,
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "expires_in": result.expires_in,
            "user_id": result.user_id,
        }

    def handle_refresh(
        self,
        refresh_token: str,
    ) -> dict:
        """Process auth_refresh message.

        RFC-307 §Token Refresh Flow.

        Args:
            refresh_token: JWT refresh token.

        Returns:
            auth_refresh_response message dict with success/error.
        """
        logger.debug("Processing token refresh request")

        result = self._identity.refresh_token(refresh_token)

        if result is None:
            logger.warning("Token refresh failed: invalid or expired refresh token")
            return {
                "type": "auth_refresh_response",
                "success": False,
                "error": "invalid_refresh_token",
                "message": "Refresh token is invalid, expired, or revoked",
            }

        logger.info("Token refresh successful: expires_in=%ds", result.expires_in)

        return {
            "type": "auth_refresh_response",
            "success": True,
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "expires_in": result.expires_in,
        }


def build_auth_response_error(error_code: str, message: str | None = None) -> dict:
    """Build standardized auth error response.

    RFC-307 §WebSocket Message Types.

    Args:
        error_code: Error code (invalid_credentials, aksk_expired, etc.).
        message: Optional custom message (generic messages preferred for security).

    Returns:
        auth_response dict with success=False.
    """
    error_messages = {
        "invalid_credentials": "Access key or secret key is invalid",
        "aksk_expired": "AKSK has expired",
        "aksk_revoked": "AKSK has been revoked",
        "missing_credentials": "Access key and secret key are required",
        "identity_disabled": "Identity service is not enabled on this daemon",
    }

    return {
        "type": "auth_response",
        "success": False,
        "error": error_code,
        "message": message or error_messages.get(error_code, "Authentication failed"),
    }


def build_refresh_response_error(error_code: str, message: str | None = None) -> dict:
    """Build standardized refresh error response.

    RFC-307 §WebSocket Message Types.

    Args:
        error_code: Error code (invalid_refresh_token, etc.).
        message: Optional custom message.

    Returns:
        auth_refresh_response dict with success=False.
    """
    error_messages = {
        "invalid_refresh_token": "Refresh token is invalid, expired, or revoked",
        "missing_refresh_token": "Refresh token is required",
        "identity_disabled": "Identity service is not enabled on this daemon",
    }

    return {
        "type": "auth_refresh_response",
        "success": False,
        "error": error_code,
        "message": message or error_messages.get(error_code, "Token refresh failed"),
    }

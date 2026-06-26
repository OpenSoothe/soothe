"""WebSocket auth integration tests (RFC-307 §Authentication Flow).

Covers the full WebSocket auth flow end-to-end against a real
``IdentityService`` + ``AuthHandler`` + ``MessageRouter``:

- ``AuthHandler.handle_auth``: valid AKSK → access/refresh tokens
- ``AuthHandler.handle_auth``: invalid credentials, revoked AKSK, expired AKSK
- ``AuthHandler.handle_refresh``: valid refresh → rotated tokens
- ``AuthHandler.handle_refresh``: invalid / revoked refresh token
- ``MessageRouter`` dispatch of ``auth`` / ``auth_refresh`` messages
- ``MessageRouter`` auth handling when identity is disabled
- Error response builders: ``build_auth_response_error``, ``build_refresh_response_error``
- Full round-trip: create user → create AKSK → authenticate → validate → refresh → revoke
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from soothe.core.security.identity_service import IdentityService

from soothe_daemon.protocol import MessageRouter
from soothe_daemon.server.auth_handler import (
    AuthHandler,
    build_auth_response_error,
    build_refresh_response_error,
)

TEST_JWT_KEY = "test-secret-key-for-testing-only-256bit!!"

# Valid-format keys for deterministic AKSK creation (see credentials.py).
KNOWN_ACCESS_KEY = "AK-abcdefghijklmno0"
KNOWN_SECRET_KEY = "SK-abcdefghijklmnopqrstuvwxyz012345"


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
    db_path = tmp_path / "test_identity_ws.db"
    return IdentityService(db_path=db_path, jwt_key=TEST_JWT_KEY)


@pytest.fixture()
def auth_handler(identity_service: IdentityService) -> AuthHandler:
    """AuthHandler wired to the real IdentityService."""
    return AuthHandler(identity_service)


def _provision_aksk(svc: IdentityService, user_id: str = "alice") -> tuple[str, str, str]:
    """Create a user + AKSK with known credentials.

    Returns (access_key, secret_key, aksk_id).
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
# Fake daemon for MessageRouter tests
# ---------------------------------------------------------------------------


class _FakeDaemon:
    """Minimal daemon stub for MessageRouter auth dispatch tests.

    Captures messages sent via ``_send_client_message`` and optionally
    exposes an ``_auth_handler``.
    """

    def __init__(self, auth_handler: AuthHandler | None = None) -> None:
        self._auth_handler = auth_handler
        self.sent: list[tuple[Any, dict[str, Any]]] = []

    async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
        self.sent.append((client_id, msg))


class _MockIdentity:
    """Mock IdentityProtocol for async router tests.

    ``IdentityService`` uses ``run_until_complete()`` internally, which
    conflicts with the already-running pytest-asyncio event loop. This mock
    returns canned results without touching the event loop, so we can test
    the router → AuthHandler message wiring in async tests.
    """

    def __init__(
        self,
        auth_result: Any | None = None,
        refresh_result: Any | None = None,
    ) -> None:
        self._auth_result = auth_result
        self._refresh_result = refresh_result

    def authenticate(self, access_key: str, secret_key: str) -> Any:
        return self._auth_result

    def refresh_token(self, refresh_token: str) -> Any:
        return self._refresh_result


# ---------------------------------------------------------------------------
# AuthHandler.handle_auth
# ---------------------------------------------------------------------------


class TestHandleAuth:
    """Tests for ``AuthHandler.handle_auth`` (AKSK → tokens)."""

    def test_auth_success_returns_tokens(
        self, auth_handler: AuthHandler, identity_service: IdentityService
    ) -> None:
        access_key, secret_key, _ = _provision_aksk(identity_service)

        result = auth_handler.handle_auth(access_key, secret_key)

        assert result["type"] == "auth_response"
        assert result["success"] is True
        assert result["access_token"]
        assert result["refresh_token"]
        assert result["user_id"] == "alice"
        assert isinstance(result["expires_in"], int)
        assert result["expires_in"] > 0

    def test_auth_invalid_secret_key(
        self, auth_handler: AuthHandler, identity_service: IdentityService
    ) -> None:
        access_key, _secret_key, _ = _provision_aksk(identity_service)

        result = auth_handler.handle_auth(access_key, "SK-wrongsecretkey000000000000000000")

        assert result["type"] == "auth_response"
        assert result["success"] is False
        assert result["error"] == "invalid_credentials"
        assert "invalid" in result["message"].lower()

    def test_auth_invalid_access_key_format(
        self, auth_handler: AuthHandler, identity_service: IdentityService
    ) -> None:
        _provision_aksk(identity_service)

        result = auth_handler.handle_auth("not-a-valid-key", KNOWN_SECRET_KEY)

        assert result["success"] is False
        assert result["error"] == "invalid_credentials"

    def test_auth_nonexistent_access_key(
        self, auth_handler: AuthHandler, identity_service: IdentityService
    ) -> None:
        _provision_aksk(identity_service)

        result = auth_handler.handle_auth("AK-nonexistentkey00", KNOWN_SECRET_KEY)

        assert result["success"] is False
        assert result["error"] == "invalid_credentials"

    def test_auth_revoked_aksk(
        self, auth_handler: AuthHandler, identity_service: IdentityService
    ) -> None:
        access_key, secret_key, aksk_id = _provision_aksk(identity_service)
        identity_service.revoke_aksk(aksk_id)

        result = auth_handler.handle_auth(access_key, secret_key)

        assert result["success"] is False
        assert result["error"] == "invalid_credentials"


class TestHandleAuthExpiredAKSK:
    """Tests for expired AKSK authentication."""

    def test_auth_expired_aksk_fails(
        self, auth_handler: AuthHandler, identity_service: IdentityService, tmp_path: Path
    ) -> None:
        """An AKSK whose expiry is in the past must not authenticate."""
        # Use a service that allows no default expiry so we control it
        svc = IdentityService(
            db_path=tmp_path / "expired.db",
            jwt_key=TEST_JWT_KEY,
            default_aksk_expiry_days=None,
        )
        handler = AuthHandler(svc)
        svc.create_user("alice")
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
            # Create AKSK with 1-day expiry, then backdate it in the DB
            aksk = svc.create_aksk("alice", expiry_days=1)

        # Backdate the expiry in the DB so the AKSK is expired
        import sqlite3

        with sqlite3.connect(str(svc.db_path)) as conn:
            conn.execute(
                "UPDATE identity_aksk_pairs SET expires_at = ? WHERE aksk_id = ?",
                (
                    (datetime.now(UTC) - timedelta(days=1)).isoformat(),
                    aksk.aksk_id,
                ),
            )
            conn.commit()

        result = handler.handle_auth(KNOWN_ACCESS_KEY, KNOWN_SECRET_KEY)
        assert result["success"] is False
        assert result["error"] == "invalid_credentials"


# ---------------------------------------------------------------------------
# AuthHandler.handle_refresh
# ---------------------------------------------------------------------------


class TestHandleRefresh:
    """Tests for ``AuthHandler.handle_refresh`` (token rotation)."""

    def test_refresh_success_returns_new_tokens(
        self, auth_handler: AuthHandler, identity_service: IdentityService
    ) -> None:
        access_key, secret_key, _ = _provision_aksk(identity_service)
        auth_result = auth_handler.handle_auth(access_key, secret_key)
        assert auth_result["success"] is True
        refresh_token = auth_result["refresh_token"]

        result = auth_handler.handle_refresh(refresh_token)

        assert result["type"] == "auth_refresh_response"
        assert result["success"] is True
        assert result["access_token"]
        assert result["refresh_token"]
        assert isinstance(result["expires_in"], int)
        # Rotation: new tokens must differ from old
        assert result["refresh_token"] != refresh_token

    def test_refresh_invalid_token(
        self, auth_handler: AuthHandler, identity_service: IdentityService
    ) -> None:
        _provision_aksk(identity_service)

        result = auth_handler.handle_refresh("invalid.jwt.token")

        assert result["type"] == "auth_refresh_response"
        assert result["success"] is False
        assert result["error"] == "invalid_refresh_token"

    def test_refresh_with_access_token_fails(
        self, auth_handler: AuthHandler, identity_service: IdentityService
    ) -> None:
        """Using an access token for refresh must fail (wrong token type)."""
        access_key, secret_key, _ = _provision_aksk(identity_service)
        auth_result = auth_handler.handle_auth(access_key, secret_key)
        access_token = auth_result["access_token"]

        result = auth_handler.handle_refresh(access_token)

        assert result["success"] is False
        assert result["error"] == "invalid_refresh_token"

    def test_refresh_revoked_refresh_token_fails(
        self, auth_handler: AuthHandler, identity_service: IdentityService
    ) -> None:
        """A revoked refresh token must not be usable for rotation."""
        access_key, secret_key, _ = _provision_aksk(identity_service)
        auth_result = auth_handler.handle_auth(access_key, secret_key)
        refresh_token = auth_result["refresh_token"]

        # First refresh succeeds and rotates (revokes old refresh)
        first_refresh = auth_handler.handle_refresh(refresh_token)
        assert first_refresh["success"] is True

        # Second refresh with old (now-revoked) token must fail
        result = auth_handler.handle_refresh(refresh_token)
        assert result["success"] is False
        assert result["error"] == "invalid_refresh_token"


# ---------------------------------------------------------------------------
# Full round-trip auth flow
# ---------------------------------------------------------------------------


class TestAuthFlowRoundTrip:
    """End-to-end: provision → auth → validate → refresh → revoke."""

    def test_full_flow(self, auth_handler: AuthHandler, identity_service: IdentityService) -> None:
        # 1. Provision user + AKSK
        access_key, secret_key, aksk_id = _provision_aksk(identity_service, "bob")

        # 2. Authenticate
        auth_result = auth_handler.handle_auth(access_key, secret_key)
        assert auth_result["success"] is True
        access_token = auth_result["access_token"]
        refresh_token = auth_result["refresh_token"]

        # 3. Validate the access token
        claims = identity_service.validate_token(access_token)
        assert claims is not None
        assert claims.user_id == "bob"
        assert claims.aksk_id == aksk_id
        assert claims.token_type == "access"

        # 4. Refresh tokens
        refresh_result = auth_handler.handle_refresh(refresh_token)
        assert refresh_result["success"] is True
        new_access = refresh_result["access_token"]

        # 5. New access token is valid
        new_claims = identity_service.validate_token(new_access)
        assert new_claims is not None
        assert new_claims.user_id == "bob"

        # 6. Old refresh token is revoked (rotation)
        old_refresh_claims = identity_service.validate_token(refresh_token)
        assert old_refresh_claims is None  # revoked → None

        # 7. Revoke all tokens for user
        identity_service.revoke_all_tokens("bob")
        # New access token is now revoked
        revoked_claims = identity_service.validate_token(new_access)
        assert revoked_claims is None

    def test_revoke_aksk_invalidates_future_auth(
        self, auth_handler: AuthHandler, identity_service: IdentityService
    ) -> None:
        access_key, secret_key, aksk_id = _provision_aksk(identity_service, "carol")

        # Auth works before revocation
        result_before = auth_handler.handle_auth(access_key, secret_key)
        assert result_before["success"] is True

        # Revoke AKSK
        identity_service.revoke_aksk(aksk_id)

        # Auth fails after revocation
        result_after = auth_handler.handle_auth(access_key, secret_key)
        assert result_after["success"] is False
        assert result_after["error"] == "invalid_credentials"


# ---------------------------------------------------------------------------
# MessageRouter auth message dispatch
# ---------------------------------------------------------------------------


class TestRouterAuthDispatch:
    """Tests for ``MessageRouter`` dispatch of ``auth`` / ``auth_refresh``.

    These tests use ``_MockIdentity`` (not the real ``IdentityService``)
    because the real service calls ``run_until_complete()`` internally,
    which conflicts with the already-running pytest-asyncio event loop.
    The real auth flow is covered by the sync ``TestHandleAuth`` and
    ``TestAuthFlowRoundTrip`` tests above.
    """

    @pytest.mark.asyncio
    async def test_router_auth_success(self) -> None:
        from soothe_sdk.protocols.identity import AuthResult

        auth_result = AuthResult(
            access_token="access-jwt",
            refresh_token="refresh-jwt",
            user_id="alice",
            expires_in=3600,
        )
        identity = _MockIdentity(auth_result=auth_result)
        handler = AuthHandler(identity)
        daemon = _FakeDaemon(auth_handler=handler)
        router = MessageRouter(daemon)

        await router.dispatch(
            "client-1",
            {"type": "auth", "access_key": KNOWN_ACCESS_KEY, "secret_key": KNOWN_SECRET_KEY},
        )

        assert len(daemon.sent) == 1
        client_id, msg = daemon.sent[0]
        assert client_id == "client-1"
        assert msg["type"] == "auth_response"
        assert msg["success"] is True
        assert msg["access_token"] == "access-jwt"
        assert msg["refresh_token"] == "refresh-jwt"
        assert msg["user_id"] == "alice"
        assert msg["expires_in"] == 3600

    @pytest.mark.asyncio
    async def test_router_auth_invalid_credentials(self) -> None:
        identity = _MockIdentity(auth_result=None)
        handler = AuthHandler(identity)
        daemon = _FakeDaemon(auth_handler=handler)
        router = MessageRouter(daemon)

        await router.dispatch(
            "client-2",
            {"type": "auth", "access_key": "AK-wrongkey00000000", "secret_key": "SK-wrong"},
        )

        assert len(daemon.sent) == 1
        _, msg = daemon.sent[0]
        assert msg["type"] == "auth_response"
        assert msg["success"] is False
        assert msg["error"] == "invalid_credentials"

    @pytest.mark.asyncio
    async def test_router_auth_missing_credentials(self) -> None:
        identity = _MockIdentity()
        handler = AuthHandler(identity)
        daemon = _FakeDaemon(auth_handler=handler)
        router = MessageRouter(daemon)

        await router.dispatch("client-3", {"type": "auth"})

        assert len(daemon.sent) == 1
        _, msg = daemon.sent[0]
        assert msg["type"] == "auth_response"
        assert msg["success"] is False
        assert msg["error"] == "missing_credentials"

    @pytest.mark.asyncio
    async def test_router_auth_identity_disabled(self) -> None:
        """When identity is disabled, router returns identity_disabled error."""
        daemon = _FakeDaemon(auth_handler=None)
        router = MessageRouter(daemon)

        await router.dispatch(
            "client-4",
            {"type": "auth", "access_key": "AK-test", "secret_key": "SK-test"},
        )

        assert len(daemon.sent) == 1
        _, msg = daemon.sent[0]
        assert msg["type"] == "auth_response"
        assert msg["success"] is False
        assert msg["error"] == "identity_disabled"

    @pytest.mark.asyncio
    async def test_router_auth_refresh_success(self) -> None:
        from soothe_sdk.protocols.identity import TokenRefreshResult

        refresh_result = TokenRefreshResult(
            access_token="new-access-jwt",
            refresh_token="new-refresh-jwt",
            expires_in=3600,
        )
        identity = _MockIdentity(refresh_result=refresh_result)
        handler = AuthHandler(identity)
        daemon = _FakeDaemon(auth_handler=handler)
        router = MessageRouter(daemon)

        await router.dispatch(
            "client-5",
            {"type": "auth_refresh", "refresh_token": "old-refresh-jwt"},
        )

        assert len(daemon.sent) == 1
        _, msg = daemon.sent[0]
        assert msg["type"] == "auth_refresh_response"
        assert msg["success"] is True
        assert msg["access_token"] == "new-access-jwt"
        assert msg["refresh_token"] == "new-refresh-jwt"
        assert msg["expires_in"] == 3600

    @pytest.mark.asyncio
    async def test_router_auth_refresh_missing_token(self) -> None:
        identity = _MockIdentity()
        handler = AuthHandler(identity)
        daemon = _FakeDaemon(auth_handler=handler)
        router = MessageRouter(daemon)

        await router.dispatch("client-6", {"type": "auth_refresh"})

        assert len(daemon.sent) == 1
        _, msg = daemon.sent[0]
        assert msg["type"] == "auth_refresh_response"
        assert msg["success"] is False
        assert msg["error"] == "missing_refresh_token"

    @pytest.mark.asyncio
    async def test_router_auth_refresh_invalid_token(self) -> None:
        identity = _MockIdentity(refresh_result=None)
        handler = AuthHandler(identity)
        daemon = _FakeDaemon(auth_handler=handler)
        router = MessageRouter(daemon)

        await router.dispatch(
            "client-7",
            {"type": "auth_refresh", "refresh_token": "invalid.jwt.token"},
        )

        assert len(daemon.sent) == 1
        _, msg = daemon.sent[0]
        assert msg["type"] == "auth_refresh_response"
        assert msg["success"] is False
        assert msg["error"] == "invalid_refresh_token"

    @pytest.mark.asyncio
    async def test_router_auth_refresh_identity_disabled(self) -> None:
        daemon = _FakeDaemon(auth_handler=None)
        router = MessageRouter(daemon)

        await router.dispatch(
            "client-8",
            {"type": "auth_refresh", "refresh_token": "some-token"},
        )

        assert len(daemon.sent) == 1
        _, msg = daemon.sent[0]
        assert msg["type"] == "auth_refresh_response"
        assert msg["success"] is False
        assert msg["error"] == "identity_disabled"


# ---------------------------------------------------------------------------
# Error response builders
# ---------------------------------------------------------------------------


class TestAuthResponseErrorBuilder:
    """Tests for ``build_auth_response_error``."""

    def test_invalid_credentials(self) -> None:
        result = build_auth_response_error("invalid_credentials")
        assert result["type"] == "auth_response"
        assert result["success"] is False
        assert result["error"] == "invalid_credentials"
        assert "invalid" in result["message"].lower()

    def test_aksk_expired(self) -> None:
        result = build_auth_response_error("aksk_expired")
        assert result["error"] == "aksk_expired"
        assert "expired" in result["message"].lower()

    def test_aksk_revoked(self) -> None:
        result = build_auth_response_error("aksk_revoked")
        assert result["error"] == "aksk_revoked"
        assert "revoked" in result["message"].lower()

    def test_missing_credentials(self) -> None:
        result = build_auth_response_error("missing_credentials")
        assert result["error"] == "missing_credentials"
        assert "required" in result["message"].lower()

    def test_identity_disabled(self) -> None:
        result = build_auth_response_error("identity_disabled")
        assert result["error"] == "identity_disabled"
        assert "not enabled" in result["message"].lower()

    def test_custom_message(self) -> None:
        result = build_auth_response_error("invalid_credentials", "Custom error")
        assert result["message"] == "Custom error"

    def test_unknown_error_code(self) -> None:
        result = build_auth_response_error("unknown_error_code")
        assert result["success"] is False
        assert result["message"] == "Authentication failed"


class TestRefreshResponseErrorBuilder:
    """Tests for ``build_refresh_response_error``."""

    def test_invalid_refresh_token(self) -> None:
        result = build_refresh_response_error("invalid_refresh_token")
        assert result["type"] == "auth_refresh_response"
        assert result["success"] is False
        assert result["error"] == "invalid_refresh_token"
        assert "invalid" in result["message"].lower()

    def test_missing_refresh_token(self) -> None:
        result = build_refresh_response_error("missing_refresh_token")
        assert result["error"] == "missing_refresh_token"
        assert "required" in result["message"].lower()

    def test_identity_disabled(self) -> None:
        result = build_refresh_response_error("identity_disabled")
        assert result["error"] == "identity_disabled"
        assert "not enabled" in result["message"].lower()

    def test_custom_message(self) -> None:
        result = build_refresh_response_error("invalid_refresh_token", "Custom")
        assert result["message"] == "Custom"

    def test_unknown_error_code(self) -> None:
        result = build_refresh_response_error("unknown_error_code")
        assert result["success"] is False
        assert result["message"] == "Token refresh failed"

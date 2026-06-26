"""Unit tests for IdentityMiddleware (RFC-307 §Middleware Integration).

Tests WebSocket token validation, external channel identity resolution,
unmapped sender policies, and disabled-state passthrough.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from soothe.core.security.models import TokenClaims
from soothe.middleware.identity import (
    AKSKConfig,
    IdentityConfig,
    IdentityMiddleware,
    IdentityRuntime,
    TokenConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_claims(
    user_id: str = "alice",
    aksk_id: str = "aksk-123",
    token_type: str = "access",
) -> TokenClaims:
    """Create a TokenClaims instance for testing."""
    now = datetime.now(UTC)
    return TokenClaims(
        jti="jti-test",
        user_id=user_id,
        aksk_id=aksk_id,
        token_type=token_type,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _make_request(
    configurable: dict[str, Any] | None = None,
    tool_call_id: str = "call-1",
    tool_name: str = "grep",
) -> ToolCallRequest:
    """Create a ToolCallRequest with a mocked runtime."""
    if configurable is None:
        configurable = {}
    runtime = MagicMock()
    runtime.config = {"configurable": configurable}
    return ToolCallRequest(
        tool_call={"id": tool_call_id, "name": tool_name, "args": {}},
        tool=None,
        state={"messages": []},
        runtime=runtime,
    )


def _make_middleware(
    identity: Any = None,
    enabled: bool = True,
    unmapped_sender_policy: str = "anonymous",
    thread_context: Any = None,
) -> IdentityMiddleware:
    """Create an IdentityMiddleware with the given config."""
    if identity is None:
        identity = MagicMock()
    config = IdentityConfig(
        enabled=enabled,
        tokens=TokenConfig(),
        aksk=AKSKConfig(),
        unmapped_sender_policy=unmapped_sender_policy,
    )
    runtime = IdentityRuntime(
        service=identity,
        config=config,
        thread_context=thread_context,
    )
    return IdentityMiddleware(runtime)


async def _passthrough_handler(_req: ToolCallRequest) -> ToolMessage:
    """A handler that returns a simple ToolMessage."""
    return ToolMessage(content="ok", tool_call_id="call-1", name="test")


# ---------------------------------------------------------------------------
# Config Models
# ---------------------------------------------------------------------------


class TestTokenConfig:
    """Tests for TokenConfig model."""

    def test_defaults(self) -> None:
        """Default values: 1 hour access, 7 days refresh, no key."""
        cfg = TokenConfig()
        assert cfg.access_token_expiry_hours == 1
        assert cfg.refresh_token_expiry_days == 7
        assert cfg.jwt_signing_key is None

    def test_validation_bounds(self) -> None:
        """access_token_expiry_hours must be 1-24, refresh 1-365."""
        with pytest.raises(Exception):
            TokenConfig(access_token_expiry_hours=0)
        with pytest.raises(Exception):
            TokenConfig(access_token_expiry_hours=25)
        with pytest.raises(Exception):
            TokenConfig(refresh_token_expiry_days=0)
        with pytest.raises(Exception):
            TokenConfig(refresh_token_expiry_days=366)


class TestAKSKConfig:
    """Tests for AKSKConfig model."""

    def test_defaults(self) -> None:
        """Default: 90 days expiry, 365 max."""
        cfg = AKSKConfig()
        assert cfg.default_expiry_days == 90
        assert cfg.max_expiry_days == 365

    def test_none_expiry_allowed(self) -> None:
        """default_expiry_days=None means never expires."""
        cfg = AKSKConfig(default_expiry_days=None)
        assert cfg.default_expiry_days is None


class TestIdentityConfig:
    """Tests for IdentityConfig model."""

    def test_disabled_by_default(self) -> None:
        """Identity is disabled by default for backward compatibility."""
        cfg = IdentityConfig()
        assert cfg.enabled is False

    def test_unmapped_sender_policy_default(self) -> None:
        """Default policy is 'anonymous'."""
        cfg = IdentityConfig()
        assert cfg.unmapped_sender_policy == "anonymous"


# ---------------------------------------------------------------------------
# Disabled Middleware (passthrough)
# ---------------------------------------------------------------------------


class TestDisabledPassthrough:
    """Tests for disabled-state passthrough (backward compat)."""

    @pytest.mark.asyncio
    async def test_disabled_middleware_calls_handler(self) -> None:
        """When disabled, middleware must pass through to handler."""
        mw = _make_middleware(enabled=False)
        request = _make_request(configurable={"auth_token": "some-token"})
        result = await mw.awrap_tool_call(request, _passthrough_handler)
        assert result.content == "ok"

    @pytest.mark.asyncio
    async def test_disabled_no_token_required(self) -> None:
        """When disabled, no token is required."""
        mw = _make_middleware(enabled=False)
        request = _make_request(configurable={})
        result = await mw.awrap_tool_call(request, _passthrough_handler)
        assert result.content == "ok"


# ---------------------------------------------------------------------------
# WebSocket Token Validation
# ---------------------------------------------------------------------------


class TestWebSocketTokenValidation:
    """Tests for WebSocket JWT token validation."""

    @pytest.mark.asyncio
    async def test_valid_token_calls_handler(self) -> None:
        """Valid token must allow the handler to proceed."""
        identity = MagicMock()
        identity.validate_token.return_value = _make_claims()
        mw = _make_middleware(identity=identity, enabled=True)
        request = _make_request(configurable={"auth_token": "valid-jwt", "thread_id": "t1"})
        result = await mw.awrap_tool_call(request, _passthrough_handler)
        assert result.content == "ok"
        identity.validate_token.assert_called_once_with("valid-jwt")

    @pytest.mark.asyncio
    async def test_valid_token_sets_user_context(self) -> None:
        """Valid token must call set_user_id_callback with thread_id and user_id."""
        identity = MagicMock()
        identity.validate_token.return_value = _make_claims(user_id="alice", aksk_id="aksk-1")
        callback = MagicMock()
        mw = _make_middleware(identity=identity, enabled=True, thread_context=callback)
        request = _make_request(configurable={"auth_token": "valid-jwt", "thread_id": "t1"})
        await mw.awrap_tool_call(request, _passthrough_handler)
        callback.set_user_id.assert_called_once_with("t1", "alice", "aksk-1")

    @pytest.mark.asyncio
    async def test_missing_token_returns_error_message(self) -> None:
        """Missing token must return a ToolMessage with auth error."""
        identity = MagicMock()
        mw = _make_middleware(identity=identity, enabled=True)
        request = _make_request(configurable={"thread_id": "t1"})
        result = await mw.awrap_tool_call(request, _passthrough_handler)
        assert isinstance(result, ToolMessage)
        assert "Authentication" in str(result.content) or "token" in str(result.content).lower()
        identity.validate_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_token_returns_error_message(self) -> None:
        """Invalid/expired token must return a ToolMessage with error."""
        identity = MagicMock()
        identity.validate_token.return_value = None
        mw = _make_middleware(identity=identity, enabled=True)
        request = _make_request(configurable={"auth_token": "bad-jwt", "thread_id": "t1"})
        result = await mw.awrap_tool_call(request, _passthrough_handler)
        assert isinstance(result, ToolMessage)
        assert "error" in str(result.content).lower() or "invalid" in str(result.content).lower()

    @pytest.mark.asyncio
    async def test_auth_message_skips_validation(self) -> None:
        """Auth messages (type=auth) must skip token validation."""
        identity = MagicMock()
        mw = _make_middleware(identity=identity, enabled=True)
        request = _make_request(configurable={"message_type": "auth", "thread_id": "t1"})
        result = await mw.awrap_tool_call(request, _passthrough_handler)
        assert result.content == "ok"
        identity.validate_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_auth_refresh_message_skips_validation(self) -> None:
        """Auth refresh messages must skip token validation."""
        identity = MagicMock()
        mw = _make_middleware(identity=identity, enabled=True)
        request = _make_request(configurable={"message_type": "auth_refresh", "thread_id": "t1"})
        result = await mw.awrap_tool_call(request, _passthrough_handler)
        assert result.content == "ok"
        identity.validate_token.assert_not_called()


# ---------------------------------------------------------------------------
# External Channel Identity Resolution
# ---------------------------------------------------------------------------


class TestExternalIdentityResolution:
    """Tests for external channel sender resolution."""

    @pytest.mark.asyncio
    async def test_mapped_sender_calls_handler(self) -> None:
        """Mapped external sender must allow handler to proceed."""
        identity = MagicMock()
        identity.resolve_identity.return_value = "alice"
        mw = _make_middleware(identity=identity, enabled=True)
        request = _make_request(
            configurable={
                "channel_type": "telegram",
                "sender_id": "tg-123",
                "thread_id": "t1",
            }
        )
        result = await mw.awrap_tool_call(request, _passthrough_handler)
        assert result.content == "ok"
        identity.resolve_identity.assert_called_once_with("telegram", "tg-123")

    @pytest.mark.asyncio
    async def test_mapped_sender_sets_user_context(self) -> None:
        """Mapped sender must call set_user_id_callback."""
        identity = MagicMock()
        identity.resolve_identity.return_value = "alice"
        callback = MagicMock()
        mw = _make_middleware(identity=identity, enabled=True, thread_context=callback)
        request = _make_request(
            configurable={
                "channel_type": "telegram",
                "sender_id": "tg-123",
                "thread_id": "t1",
            }
        )
        await mw.awrap_tool_call(request, _passthrough_handler)
        callback.set_user_id.assert_called_once_with("t1", "alice", None)

    @pytest.mark.asyncio
    async def test_unmapped_anonymous_policy_passes(self) -> None:
        """With 'anonymous' policy, unmapped sender passes with None user."""
        identity = MagicMock()
        identity.resolve_identity.return_value = None
        callback = MagicMock()
        mw = _make_middleware(
            identity=identity,
            enabled=True,
            unmapped_sender_policy="anonymous",
            thread_context=callback,
        )
        request = _make_request(
            configurable={
                "channel_type": "telegram",
                "sender_id": "unknown",
                "thread_id": "t1",
            }
        )
        result = await mw.awrap_tool_call(request, _passthrough_handler)
        assert result.content == "ok"
        callback.set_user_id.assert_called_once_with("t1", None, None)

    @pytest.mark.asyncio
    async def test_unmapped_reject_policy_returns_error(self) -> None:
        """With 'reject' policy, unmapped sender must return error."""
        identity = MagicMock()
        identity.resolve_identity.return_value = None
        mw = _make_middleware(
            identity=identity,
            enabled=True,
            unmapped_sender_policy="reject",
        )
        request = _make_request(
            configurable={
                "channel_type": "telegram",
                "sender_id": "unknown",
                "thread_id": "t1",
            }
        )
        result = await mw.awrap_tool_call(request, _passthrough_handler)
        assert isinstance(result, ToolMessage)
        assert "identity" in str(result.content).lower() or "error" in str(result.content).lower()

    @pytest.mark.asyncio
    async def test_unmapped_use_sender_id_policy(self) -> None:
        """With 'use_sender_id' policy, unmapped sender uses channel:sender_id."""
        identity = MagicMock()
        identity.resolve_identity.return_value = None
        callback = MagicMock()
        mw = _make_middleware(
            identity=identity,
            enabled=True,
            unmapped_sender_policy="use_sender_id",
            thread_context=callback,
        )
        request = _make_request(
            configurable={
                "channel_type": "telegram",
                "sender_id": "tg-999",
                "thread_id": "t1",
            }
        )
        result = await mw.awrap_tool_call(request, _passthrough_handler)
        assert result.content == "ok"
        callback.set_user_id.assert_called_once_with("t1", "telegram:tg-999", None)

    @pytest.mark.asyncio
    async def test_no_sender_id_passes_anonymous(self) -> None:
        """External channel without sender_id passes as anonymous."""
        identity = MagicMock()
        mw = _make_middleware(identity=identity, enabled=True)
        request = _make_request(
            configurable={
                "channel_type": "telegram",
                "thread_id": "t1",
            }
        )
        result = await mw.awrap_tool_call(request, _passthrough_handler)
        assert result.content == "ok"
        identity.resolve_identity.assert_not_called()


# ---------------------------------------------------------------------------
# Thread ID Extraction
# ---------------------------------------------------------------------------


class TestThreadIdExtraction:
    """Tests for thread_id extraction from request."""

    @pytest.mark.asyncio
    async def test_no_thread_id_no_callback_call(self) -> None:
        """Without thread_id, set_user_id_callback is not called."""
        identity = MagicMock()
        identity.validate_token.return_value = _make_claims()
        callback = MagicMock()
        mw = _make_middleware(identity=identity, enabled=True, thread_context=callback)
        request = _make_request(configurable={"auth_token": "valid-jwt"})
        await mw.awrap_tool_call(request, _passthrough_handler)
        callback.set_user_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_thread_id_passed_to_callback(self) -> None:
        """thread_id from configurable is passed to callback."""
        identity = MagicMock()
        identity.validate_token.return_value = _make_claims()
        callback = MagicMock()
        mw = _make_middleware(identity=identity, enabled=True, thread_context=callback)
        request = _make_request(configurable={"auth_token": "valid-jwt", "thread_id": "thread-xyz"})
        await mw.awrap_tool_call(request, _passthrough_handler)
        callback.set_user_id.assert_called_once()
        # First positional arg is thread_id
        assert callback.set_user_id.call_args[0][0] == "thread-xyz"

"""Identity middleware for request authentication. RFC-307 §Middleware Integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from pydantic import BaseModel, Field

from soothe.core.security.errors import (
    MissingTokenError,
    TokenError,
    UnmappedIdentityError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from langgraph.types import Command
    from soothe_sdk.protocols.identity import IdentityProtocol


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Identity Config (defined here to avoid soothe → soothe-daemon dependency)
# ---------------------------------------------------------------------------


class TokenConfig(BaseModel):
    """JWT token configuration for identity service (RFC-307).

    Args:
        access_token_expiry_hours: Access token lifetime in hours (1-24).
        refresh_token_expiry_days: Refresh token lifetime in days (1-365).
        jwt_signing_key: JWT signing key (from env, config, or auto-generated).
    """

    access_token_expiry_hours: int = Field(
        default=1,
        ge=1,
        le=24,
        description="Access token expiry in hours",
    )
    refresh_token_expiry_days: int = Field(
        default=7,
        ge=1,
        le=365,
        description="Refresh token expiry in days",
    )
    jwt_signing_key: str | None = Field(
        default=None,
        description="JWT signing key (256-bit). Use SOOTHE_JWT_KEY env var or auto-generate.",
    )


class AKSKConfig(BaseModel):
    """AKSK configuration for identity service (RFC-307).

    Args:
        default_expiry_days: Default AKSK expiry days (None = never expires).
        max_expiry_days: Maximum allowed AKSK expiry days.
    """

    default_expiry_days: int | None = Field(
        default=90,
        description="Default AKSK expiry days (None = never)",
    )
    max_expiry_days: int = Field(
        default=365,
        ge=1,
        description="Maximum allowed AKSK expiry days",
    )


class IdentityConfig(BaseModel):
    """Identity service configuration (RFC-307).

    Provides AKSK-based authentication and JWT token management.
    Disabled by default for backward compatibility.

    Note: This config is defined in soothe core (not soothe-daemon) to avoid
    circular dependency. soothe-daemon re-exports it for YAML config loading.

    Args:
        enabled: Enable identity service (default: False for backward compat).
        tokens: Token configuration (expiry settings).
        aksk: AKSK configuration (expiry defaults).
        unmapped_sender_policy: Policy for unmapped external senders.
    """

    enabled: bool = Field(
        default=False,
        description="Enable identity service. Disabled by default for backward compatibility.",
    )
    tokens: TokenConfig = Field(
        default_factory=TokenConfig,
        description="JWT token configuration",
    )
    aksk: AKSKConfig = Field(
        default_factory=AKSKConfig,
        description="AKSK configuration",
    )
    unmapped_sender_policy: Literal["anonymous", "reject", "use_sender_id"] = Field(
        default="anonymous",
        description=(
            "Policy for unmapped external channel senders: "
            "'anonymous' (fall back to anonymous workspace), "
            "'reject' (reject message), "
            "'use_sender_id' (use channel:sender_id as user_id)"
        ),
    )


class IdentityMiddleware(AgentMiddleware):
    """First middleware in stack for identity validation.

    RFC-307 §Middleware Integration.

    This middleware runs BEFORE PolicyMiddleware to establish user context:
    - WebSocket: Validate JWT auth_token, populate user_id
    - External channels: Resolve sender_id via mapping table

    When identity.enabled = false, middleware passes through unchanged
    (backward compatibility).
    """

    def __init__(
        self,
        identity: IdentityProtocol,
        config: IdentityConfig,
        set_user_id_callback: Callable[[str, str | None, str | None], None] | None = None,
    ) -> None:
        """Initialize IdentityMiddleware.

        Args:
            identity: IdentityProtocol implementation for token validation.
            config: Identity configuration (enabled, unmapped_sender_policy).
            set_user_id_callback: Optional callback to set user context in thread state.
                Signature: (thread_id, user_id, aksk_id) -> None.
                Passed from daemon to avoid core → daemon dependency.
        """
        self._identity = identity
        self._config = config
        self._set_user_id_callback = set_user_id_callback

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> ToolMessage | Command[Any]:
        """Validate identity before allowing tool call to proceed.

        RFC-307 §Middleware order: IdentityMiddleware before PolicyMiddleware.

        Args:
            request: The tool call request.
            handler: The next handler in the middleware chain.

        Returns:
            ToolMessage with error if identity validation fails,
            otherwise result from handler.

        Raises:
            TokenError: If token validation fails.
            UnmappedIdentityError: If external sender not mapped (policy=reject).
        """
        # Skip when disabled (backward compatibility)
        if not self._config.enabled:
            logger.debug("Identity middleware skipped: disabled")
            return await handler(request)

        # Extract context from request
        configurable = request.runtime.config.get("configurable", {})
        thread_id = self._thread_id_from_request(request)
        channel_type = configurable.get("channel_type", "websocket")

        try:
            if channel_type == "websocket":
                user_id, aksk_id = self._validate_websocket_token(configurable)
            else:
                user_id, aksk_id = self._resolve_external_identity(channel_type, configurable)

            # Populate ThreadState with user context via callback
            if thread_id and self._set_user_id_callback:
                self._set_user_id_callback(thread_id, user_id, aksk_id)
                logger.debug(
                    "Identity context set: thread=%s user=%s aksk=%s",
                    thread_id,
                    user_id,
                    aksk_id,
                )

            return await handler(request)

        except TokenError as e:
            logger.warning("Token validation failed: %s", e.error_code)
            tool_call = request.tool_call or {}
            return ToolMessage(
                content=f"Authentication error: {e.message}",
                tool_call_id=tool_call.get("id"),
                name="identity",
            )
        except UnmappedIdentityError as e:
            logger.warning("Unmapped identity: channel=%s", channel_type)
            tool_call = request.tool_call or {}
            return ToolMessage(
                content=f"Identity error: {e.message}",
                tool_call_id=tool_call.get("id"),
                name="identity",
            )

    def _validate_websocket_token(
        self, configurable: dict[str, Any]
    ) -> tuple[str | None, str | None]:
        """Validate WebSocket JWT token.

        RFC-307 §WebSocket AKSK Flow.

        Args:
            configurable: LangGraph configurable dict with auth_token.

        Returns:
            Tuple of (user_id, aksk_id) if valid.

        Raises:
            MissingTokenError: If no token provided (and not auth message).
            TokenError: If token invalid/expired/revoked.
        """
        token = configurable.get("auth_token")

        # Check if this is an auth message (skip validation)
        message_type = configurable.get("message_type")
        if message_type in ("auth", "auth_refresh"):
            logger.debug("Auth message detected, skipping token validation")
            return None, None

        if not token:
            raise MissingTokenError()

        claims = self._identity.validate_token(token)
        if claims is None:
            # Could be expired or revoked - generic error for security
            raise TokenError("Token invalid or expired")

        return claims.user_id, claims.aksk_id

    def _resolve_external_identity(
        self, channel_type: str, configurable: dict[str, Any]
    ) -> tuple[str | None, str | None]:
        """Resolve external channel sender to soothe user.

        RFC-307 §External Channel Resolution.

        Args:
            channel_type: Channel name (telegram, feishu, etc.).
            configurable: LangGraph configurable dict with sender_id.

        Returns:
            Tuple of (user_id, None) - aksk_id not applicable for external.

        Raises:
            UnmappedIdentityError: If sender not mapped and policy=reject.
        """
        sender_id = configurable.get("sender_id")

        if not sender_id:
            logger.debug("No sender_id for external channel: %s", channel_type)
            return None, None

        # Try to resolve mapping
        user_id = self._identity.resolve_identity(channel_type, sender_id)

        if user_id:
            logger.debug(
                "External identity resolved: channel=%s sender=%s user=%s",
                channel_type,
                sender_id,
                user_id,
            )
            return user_id, None

        # Apply unmapped sender policy
        policy = self._config.unmapped_sender_policy

        if policy == "reject":
            logger.warning(
                "Unmapped sender rejected: channel=%s sender=%s",
                channel_type,
                sender_id,
            )
            raise UnmappedIdentityError()

        if policy == "use_sender_id":
            # Use channel:sender_id as user_id
            synthetic_user_id = f"{channel_type}:{sender_id}"
            logger.debug(
                "Using synthetic user_id: %s",
                synthetic_user_id,
            )
            return synthetic_user_id, None

        # Default: anonymous (None)
        logger.debug(
            "Unmapped sender anonymous: channel=%s sender=%s",
            channel_type,
            sender_id,
        )
        return None, None

    def _thread_id_from_request(self, request: ToolCallRequest) -> str | None:
        """Extract thread_id from LangGraph configurable.

        Args:
            request: ToolCallRequest with runtime.config.

        Returns:
            thread_id if found, None otherwise.
        """
        configurable = request.runtime.config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        return str(thread_id) if thread_id else None

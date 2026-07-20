"""Identity middleware for request authentication."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from soothe_sdk.identity.errors import (
    MissingTokenError,
    TokenError,
    UnmappedIdentityError,
)

from soothe.foundation.identity.runtime import IdentityRuntime

if TYPE_CHECKING:
    from collections.abc import Callable

    from langgraph.types import Command

logger = logging.getLogger(__name__)


class IdentityMiddleware(AgentMiddleware):
    """First middleware in stack for identity validation."""

    def __init__(self, runtime: IdentityRuntime) -> None:
        self._runtime = runtime
        self._identity = runtime.service
        self._config = runtime.config
        self._thread_context = runtime.thread_context

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> ToolMessage | Command[Any]:
        """Validate identity before allowing tool call to proceed."""
        if not self._config.enabled:
            logger.debug("Identity middleware skipped: disabled")
            return await handler(request)

        configurable = request.runtime.config.get("configurable", {})
        thread_id = self._thread_id_from_request(request)
        channel_type = configurable.get("channel_type", "websocket")

        try:
            if channel_type == "websocket":
                user_id, aksk_id = self._validate_websocket_token(configurable)
            else:
                user_id, aksk_id = self._resolve_external_identity(channel_type, configurable)

            if thread_id and self._thread_context is not None:
                self._thread_context.set_user_id(thread_id, user_id, aksk_id)
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
        """Validate WebSocket JWT token."""
        token = configurable.get("auth_token")

        message_type = configurable.get("message_type")
        if message_type in ("auth", "auth_refresh"):
            logger.debug("Auth message detected, skipping token validation")
            return None, None

        if not token:
            raise MissingTokenError()

        claims = self._identity.validate_token(token)
        if claims is None:
            raise TokenError("Token invalid or expired")

        return claims.user_id, claims.aksk_id

    def _resolve_external_identity(
        self, channel_type: str, configurable: dict[str, Any]
    ) -> tuple[str | None, str | None]:
        """Resolve external channel sender to soothe user."""
        sender_id = configurable.get("sender_id")

        if not sender_id:
            logger.debug("No sender_id for external channel: %s", channel_type)
            return None, None

        user_id = self._identity.resolve_identity(channel_type, sender_id)

        if user_id:
            logger.debug(
                "External identity resolved: channel=%s sender=%s user=%s",
                channel_type,
                sender_id,
                user_id,
            )
            return user_id, None

        policy = self._config.unmapped_sender_policy

        if policy == "reject":
            logger.warning(
                "Unmapped sender rejected: channel=%s sender=%s",
                channel_type,
                sender_id,
            )
            raise UnmappedIdentityError()

        if policy == "use_sender_id":
            synthetic_user_id = f"{channel_type}:{sender_id}"
            logger.debug("Using synthetic user_id: %s", synthetic_user_id)
            return synthetic_user_id, None

        logger.debug(
            "Unmapped sender anonymous: channel=%s sender=%s",
            channel_type,
            sender_id,
        )
        return None, None

    def _thread_id_from_request(self, request: ToolCallRequest) -> str | None:
        """Extract thread_id from LangGraph configurable."""
        configurable = request.runtime.config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        return str(thread_id) if thread_id else None


__all__ = ["IdentityMiddleware"]

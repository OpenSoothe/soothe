"""Identity runtime/config models shared by daemon and runner wiring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, Field
from soothe_sdk.protocols.identity import IdentityProtocol


class TokenConfig(BaseModel):
    """JWT token configuration for identity service."""

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
    """AKSK configuration for identity service."""

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
    """Identity service configuration."""

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


class ThreadContextProvider(Protocol):
    """Daemon-side hook for persisting authenticated user context per thread."""

    def set_user_id(
        self,
        thread_id: str,
        user_id: str | None,
        aksk_id: str | None = None,
    ) -> None:
        """Record authenticated identity for workspace isolation."""
        ...


@dataclass
class IdentityRuntime:
    """Bundle of identity dependencies injected from daemon into runner stack."""

    service: IdentityProtocol
    config: IdentityConfig
    thread_context: ThreadContextProvider | None = None

    @property
    def enabled(self) -> bool:
        """Return whether identity validation is active."""
        return self.config.enabled


__all__ = [
    "AKSKConfig",
    "IdentityConfig",
    "IdentityRuntime",
    "ThreadContextProvider",
    "TokenConfig",
]

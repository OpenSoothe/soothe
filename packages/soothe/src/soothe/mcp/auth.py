"""MCP authentication utilities (RFC-412).

V1: Bearer tokens + headers + env interpolation.
OAuth is deferred to a follow-on RFC; AuthProvider protocol stub is reserved.
"""

from __future__ import annotations

from typing import Protocol


class AuthProvider(Protocol):
    """Protocol for MCP authentication providers.

    V1 only has StaticHeadersProvider (header interpolation).
    OAuth would implement this protocol with PKCE + DCR + refresh + step-up.
    """

    async def headers(self) -> dict[str, str]:
        """Return headers to add to the request."""
        ...

    async def on_401(self) -> bool:
        """Handle 401 response.

        Returns:
            True if retry should happen (e.g. token refreshed).
            False if the error is unrecoverable.
        """
        ...


class StaticHeadersProvider:
    """V1 auth provider: static headers with env interpolation.

    Headers are interpolated at MCPRegistry.initialize time via config.secret_resolver.
    """

    def __init__(self, headers: dict[str, str]) -> None:
        self._headers = headers

    async def headers(self) -> dict[str, str]:
        return dict(self._headers)

    async def on_401(self) -> bool:
        # Static headers cannot refresh; 401 is terminal
        return False


def interpolate_auth_headers(
    headers: dict[str, str],
    secret_resolver: callable,
) -> dict[str, str]:
    """Interpolate ${ENV_VAR} in auth headers.

    Args:
        headers: Raw headers dict with potential ${ENV_VAR} syntax.
        secret_resolver: Function to resolve env vars (config.secret_resolver).

    Returns:
        Headers dict with resolved values.

    Raises:
        ValueError: If referenced env var is missing.
    """
    resolved = {}
    for key, value in headers.items():
        resolved[key] = secret_resolver(value)
    return resolved

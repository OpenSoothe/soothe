"""RFC-204: Webhook notification service for autopilot events.

Sends outbound HTTP POST notifications for key autopilot events.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Event types that trigger webhooks
AUTONOTIFY_EVENTS = frozenset({
    "goal_completed",
    "goal_failed",
    "dreaming_entered",
    "dreaming_exited",
})


@dataclass
class WebhookConfig:
    """Configuration for a single webhook endpoint."""

    url: str
    events: frozenset[str] = AUTONOTIFY_EVENTS
    timeout: float = 10.0
    retries: int = 3


@dataclass
class WebhookService:
    """Sends webhook notifications for autopilot events.

    Args:
        webhooks: Dict of event_name → list of WebhookConfig.
    """

    webhooks: dict[str, list[WebhookConfig]] = field(default_factory=dict)
    _session: Any = None

    async def notify(self, event_type: str, data: dict[str, Any]) -> None:
        """Send a webhook notification.

        Args:
            event_type: Event type string.
            data: Event payload.
        """
        configs = self.webhooks.get(event_type, [])
        if not configs:
            return

        payload = {
            "event": event_type,
            "timestamp": datetime.now(tz=UTC).isoformat(),
            **data,
        }

        for cfg in configs:
            await self._send_webhook(cfg, payload)

    async def _send_webhook(self, cfg: WebhookConfig, payload: dict[str, Any]) -> None:
        """Send a single webhook POST.

        Args:
            cfg: Webhook configuration.
            payload: Event payload.
        """
        import json

        headers = {"Content-Type": "application/json"}
        body = json.dumps(payload)

        for attempt in range(cfg.retries):
            try:
                async with _get_http_session().post(
                    cfg.url,
                    data=body,
                    headers=headers,
                    timeout=cfg.timeout,
                ) as resp:
                    if resp.status < 400:  # noqa: PLR2004
                        logger.debug("Webhook sent to %s: %s", cfg.url, payload.get("event"))
                        return
                    logger.warning(
                        "Webhook failed (%d) to %s, attempt %d/%d",
                        resp.status,
                        cfg.url,
                        attempt + 1,
                        cfg.retries,
                    )
            except Exception:
                logger.warning(
                    "Webhook error to %s, attempt %d/%d",
                    cfg.url,
                    attempt + 1,
                    cfg.retries,
                    exc_info=True,
                )
            if attempt < cfg.retries - 1:
                await asyncio.sleep(2**attempt)  # Exponential backoff

        logger.error("Webhook failed after %d retries: %s", cfg.retries, cfg.url)


def _get_http_session() -> Any:
    """Get or create an aiohttp ClientSession.

    Returns:
        aiohttp ClientSession instance.
    """
    if WebhookService._session is None:
        try:
            import aiohttp

            WebhookService._session = aiohttp.ClientSession()
        except ImportError:
            logger.warning("aiohttp not installed, webhooks disabled")
            return _FallbackHttp()
    return WebhookService._session


class _FallbackHttp:
    """Fallback HTTP client when aiohttp is not available."""

    async def post(self, *_args: object, **_kwargs: object) -> Any:
        """No-op fallback."""
        logger.debug("Webhook skipped (no aiohttp)")
        return _FallbackResponse()


class _FallbackResponse:
    """Fallback response."""

    status = 200

    from typing import Self

    async def __aenter__(self) -> Self:
        """Enter context manager."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit context manager."""

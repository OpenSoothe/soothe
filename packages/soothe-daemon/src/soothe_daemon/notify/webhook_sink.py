"""HTTP webhook NotifySink (IG-713)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.autopilot.notify.models import DeliveryResult, NotifyIntent, NotifyTarget

from soothe_daemon.notify.render import intent_webhook_payload

if TYPE_CHECKING:
    from soothe.config.models import WebhookNotifySinkConfig

logger = logging.getLogger(__name__)

_KIND_TO_URL_KEY = {
    "job.completed": "job_completed",
    "job.failed": "job_failed",
    "job.suspended_timeout": "job_suspended_timeout",
}


class WebhookNotifySink:
    """POST NotifyIntent JSON to configured URLs."""

    name = "webhook"

    def __init__(
        self,
        config: WebhookNotifySinkConfig,
        *,
        legacy_webhooks: dict[str, str | None] | None = None,
        http_post: Any | None = None,
    ) -> None:
        self._config = config
        self._legacy = dict(legacy_webhooks or {})
        self._http_post = http_post

    def enabled(self) -> bool:
        return bool(self._config.enabled)

    def _resolve_url(self, event_key: str) -> str | None:
        urls = self._config.urls or {}
        raw = urls.get(event_key) or urls.get(f"on_{event_key}")
        if not raw:
            raw = self._legacy.get(event_key) or self._legacy.get(f"on_{event_key}")
        if not raw:
            return None
        text = str(raw).strip()
        return text or None

    async def _post(self, url: str, payload: dict[str, Any]) -> None:
        if self._http_post is not None:
            await self._http_post(url, payload)
            return
        import httpx

        timeout = float(self._config.timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()

    async def deliver(
        self,
        intent: NotifyIntent,
        targets: list[NotifyTarget],
    ) -> DeliveryResult:
        event_key = _KIND_TO_URL_KEY.get(intent.kind, intent.kind.replace(".", "_"))
        urls: list[str] = []
        primary = self._resolve_url(event_key)
        if primary:
            urls.append(primary)
        for t in targets:
            if t.kind == "webhook_url" and t.to_address.strip():
                urls.append(t.to_address.strip())
        seen: set[str] = set()
        unique: list[str] = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)
        if not unique:
            return DeliveryResult(sink=self.name, ok=True, detail="no webhook urls")

        payload = intent_webhook_payload(intent)
        delivered: list[str] = []
        errors: list[str] = []
        for url in unique:
            try:
                await self._post(url, payload)
                delivered.append(url)
            except Exception as exc:
                logger.warning(
                    "Webhook notify failed url=%s job=%s: %s",
                    url,
                    intent.job_id,
                    exc,
                )
                errors.append(str(exc)[:160])
        ok = bool(delivered)
        detail = f"posted={len(delivered)}" if ok else "; ".join(errors)[:300]
        return DeliveryResult(
            sink=self.name,
            ok=ok,
            detail=detail,
            delivered_to=delivered,
        )

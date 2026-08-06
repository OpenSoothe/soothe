"""Build NotifyDispatcher from Autopilot notify config (IG-713)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.autopilot.notify.models import NotifyTarget

from soothe_daemon.notify.email_sink import EmailNotifySink
from soothe_daemon.notify.feishu_sink import FeishuNotifySink
from soothe_daemon.notify.protocol import NotifyDispatcher
from soothe_daemon.notify.webhook_sink import WebhookNotifySink

if TYPE_CHECKING:
    from soothe.config.models import AutopilotConfig, AutopilotNotifyConfig

logger = logging.getLogger(__name__)


def build_notify_dispatcher(
    notify: AutopilotNotifyConfig,
    *,
    legacy_webhooks: dict[str, str | None] | None = None,
) -> NotifyDispatcher:
    """Construct dispatcher with email, webhook, and Feishu sinks."""
    dispatcher = NotifyDispatcher()
    dispatcher.set_global_targets(
        [NotifyTarget(kind=t.kind, address=t.address) for t in notify.targets]
    )
    dispatcher.register(EmailNotifySink(notify.sinks.email))
    legacy = dict(legacy_webhooks or {})
    webhook_cfg = notify.sinks.webhook
    if not webhook_cfg.enabled and any(v for v in legacy.values() if v):
        # Treat legacy webhooks map as enabling the webhook sink without
        # mutating the caller's config object.
        from soothe.config.models import WebhookNotifySinkConfig

        webhook_cfg = WebhookNotifySinkConfig(
            enabled=True,
            urls=dict(webhook_cfg.urls),
            timeout_seconds=webhook_cfg.timeout_seconds,
        )
    dispatcher.register(WebhookNotifySink(webhook_cfg, legacy_webhooks=legacy))
    dispatcher.register(FeishuNotifySink(notify.sinks.feishu))
    logger.info(
        "NotifyDispatcher built sinks=%s notify_enabled=%s",
        [s.name for s in dispatcher.sinks],
        notify.enabled,
    )
    return dispatcher


def build_notify_dispatcher_from_autopilot(autopilot: AutopilotConfig) -> NotifyDispatcher:
    """Convenience: build from full AutopilotConfig."""
    return build_notify_dispatcher(
        autopilot.notify,
        legacy_webhooks=autopilot.webhooks,
    )

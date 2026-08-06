"""Feishu/Lark NotifySink stub (IG-713 Phase 1).

Config schema + registry participation; live IM send is a follow-up.
When enabled without credentials / live path, deliver returns a clear
skipped result so operators see the extension point.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.autopilot.notify.models import DeliveryResult, NotifyIntent, NotifyTarget

if TYPE_CHECKING:
    from soothe.config.models import FeishuNotifySinkConfig

logger = logging.getLogger(__name__)


class FeishuNotifySink:
    """Outbound Feishu IM alerts (stub — no live API send in Phase 1)."""

    name = "feishu"

    def __init__(self, config: FeishuNotifySinkConfig) -> None:
        self._config = config

    def enabled(self) -> bool:
        return bool(self._config.enabled)

    def _resolve_targets(
        self,
        targets: list[NotifyTarget],
    ) -> list[NotifyTarget]:
        out: list[NotifyTarget] = []
        for t in list(targets) + list(self._config.targets):
            if t.kind in {"feishu_chat_id", "feishu_open_id"} and t.to_address.strip():
                out.append(t)
        return out

    async def deliver(
        self,
        intent: NotifyIntent,
        targets: list[NotifyTarget],
    ) -> DeliveryResult:
        resolved = self._resolve_targets(targets)
        if not self._config.app_id or not self._config.app_secret:
            logger.info(
                "Feishu notify stub skipped (missing app credentials) job=%s kind=%s",
                intent.job_id,
                intent.kind,
            )
            return DeliveryResult(
                sink=self.name,
                ok=True,
                detail="stub: missing app_id/app_secret (live send deferred)",
            )
        if not resolved:
            return DeliveryResult(
                sink=self.name,
                ok=True,
                detail="stub: no feishu targets",
            )
        # Phase 1: do not call Lark API — prove registry path only.
        logger.info(
            "Feishu notify stub (live send deferred) job=%s kind=%s targets=%d",
            intent.job_id,
            intent.kind,
            len(resolved),
        )
        return DeliveryResult(
            sink=self.name,
            ok=True,
            detail="stub: live Feishu send deferred",
            delivered_to=[t.to_address for t in resolved],
        )

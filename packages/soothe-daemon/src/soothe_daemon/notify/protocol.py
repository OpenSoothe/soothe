"""Daemon NotifySink protocol and dispatcher."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol, runtime_checkable

from soothe_autopilot.notify.models import DeliveryResult, NotifyIntent, NotifyTarget

logger = logging.getLogger(__name__)


@runtime_checkable
class NotifySink(Protocol):
    """One-shot outbound delivery adapter (email, webhook, Feishu, …)."""

    name: str

    def enabled(self) -> bool:
        """Whether this sink should receive intents."""

    async def deliver(
        self,
        intent: NotifyIntent,
        targets: list[NotifyTarget],
    ) -> DeliveryResult:
        """Push one intent. Must not start an agent turn. Fail soft."""


class NotifyDispatcher:
    """Fan-out NotifyIntent to all enabled sinks (fail-soft, parallel)."""

    def __init__(self, sinks: list[NotifySink] | None = None) -> None:
        self._sinks: list[NotifySink] = list(sinks or [])
        self._global_targets: list[NotifyTarget] = []

    def register(self, sink: NotifySink) -> None:
        """Register a sink (replaces same ``name`` if already present)."""
        self._sinks = [s for s in self._sinks if s.name != sink.name]
        self._sinks.append(sink)

    def set_global_targets(self, targets: list[NotifyTarget]) -> None:
        """Default targets from ``notify.targets`` config."""
        self._global_targets = list(targets)

    @property
    def sinks(self) -> list[NotifySink]:
        return list(self._sinks)

    async def dispatch(self, intent: NotifyIntent) -> list[DeliveryResult]:
        """Deliver to every enabled sink; one failure does not cancel others."""
        enabled = [s for s in self._sinks if s.enabled()]
        if not enabled:
            logger.debug(
                "Notify dispatch skipped (no enabled sinks) kind=%s job=%s",
                intent.kind,
                intent.job_id,
            )
            return []

        async def _one(sink: NotifySink) -> DeliveryResult:
            try:
                return await sink.deliver(intent, list(self._global_targets))
            except Exception as exc:
                logger.exception(
                    "Notify sink %s crashed kind=%s job=%s",
                    sink.name,
                    intent.kind,
                    intent.job_id,
                )
                return DeliveryResult(sink=sink.name, ok=False, detail=str(exc)[:300])

        results = await asyncio.gather(*[_one(s) for s in enabled])
        for result in results:
            level = logging.INFO if result.ok else logging.WARNING
            logger.log(
                level,
                "Notify sink=%s ok=%s kind=%s job=%s detail=%s",
                result.sink,
                result.ok,
                intent.kind,
                intent.job_id,
                (result.detail or "")[:160],
            )
        return list(results)

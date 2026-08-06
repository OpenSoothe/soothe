"""Production SMTP EmailNotifySink (IG-713)."""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
import time
from email.message import EmailMessage
from typing import TYPE_CHECKING

from soothe.autopilot.notify.models import DeliveryResult, NotifyIntent, NotifyTarget

from soothe_daemon.notify.render import intent_html_body, intent_plain_body, intent_subject

if TYPE_CHECKING:
    from soothe.config.models import EmailNotifySinkConfig

logger = logging.getLogger(__name__)


class EmailNotifySink:
    """Outbound-only SMTP delivery for job lifecycle alerts."""

    name = "email"

    def __init__(self, config: EmailNotifySinkConfig) -> None:
        self._config = config
        self._last_sent_at: dict[str, float] = {}
        self._min_interval_seconds = 5.0

    def enabled(self) -> bool:
        return bool(
            self._config.enabled
            and self._config.smtp_host
            and (self._config.from_address or self._config.smtp_username)
        )

    def _resolve_recipients(
        self,
        intent: NotifyIntent,
        targets: list[NotifyTarget],
    ) -> list[str]:
        del intent
        addrs: list[str] = []
        seen: set[str] = set()
        extras = [NotifyTarget(kind=t.kind, to_address=t.to_address) for t in self._config.targets]
        for t in list(targets) + extras:
            if t.kind != "email":
                continue
            addr = (t.to_address or "").strip()
            if not addr or addr in seen:
                continue
            seen.add(addr)
            addrs.append(addr)
        return addrs

    def _rate_limited(self, key: str) -> bool:
        now = time.monotonic()
        last = self._last_sent_at.get(key)
        if last is not None and (now - last) < self._min_interval_seconds:
            return True
        self._last_sent_at[key] = now
        return False

    def _smtp_send(self, msg: EmailMessage) -> None:
        timeout = float(self._config.connect_timeout_seconds)
        host = self._config.smtp_host
        port = int(self._config.smtp_port)
        user = self._config.smtp_username
        password = self._config.smtp_password
        if self._config.smtp_use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=timeout) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
            return
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            if self._config.smtp_use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)

    def _build_message(self, intent: NotifyIntent, to_addr: str) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self._config.from_address or self._config.smtp_username
        msg["To"] = to_addr
        msg["Subject"] = intent_subject(intent)
        msg.set_content(intent_plain_body(intent))
        msg.add_alternative(intent_html_body(intent), subtype="html")
        return msg

    async def deliver(
        self,
        intent: NotifyIntent,
        targets: list[NotifyTarget],
    ) -> DeliveryResult:
        recipients = self._resolve_recipients(intent, targets)
        if not recipients:
            return DeliveryResult(
                sink=self.name,
                ok=True,
                detail="no email targets",
            )
        delivered: list[str] = []
        errors: list[str] = []
        retries = max(0, int(self._config.max_retries))
        for to_addr in recipients:
            rate_key = f"{intent.job_id}:{intent.kind}:{to_addr}"
            if self._rate_limited(rate_key):
                errors.append(f"rate_limited:{to_addr}")
                continue
            msg = self._build_message(intent, to_addr)
            last_exc: Exception | None = None
            for attempt in range(retries + 1):
                try:
                    await asyncio.to_thread(self._smtp_send, msg)
                    delivered.append(to_addr)
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt < retries:
                        await asyncio.sleep(0.5 * (attempt + 1))
            if last_exc is not None:
                logger.warning(
                    "Email notify failed to=%s job=%s: %s",
                    to_addr,
                    intent.job_id,
                    last_exc,
                )
                errors.append(f"{to_addr}:{last_exc!s}"[:200])
        ok = bool(delivered)
        if errors and not delivered:
            ok = False
        detail = ""
        if delivered and not errors:
            detail = f"sent={len(delivered)}"
        elif delivered and errors:
            detail = f"partial sent={len(delivered)}; " + "; ".join(errors)[:240]
        elif errors:
            detail = "; ".join(errors)[:300]
        else:
            detail = "no deliveries"
        return DeliveryResult(
            sink=self.name,
            ok=ok,
            detail=detail,
            delivered_to=delivered,
        )

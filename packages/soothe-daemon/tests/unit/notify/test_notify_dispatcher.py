"""IG-713: NotifyDispatcher + email/webhook/feishu sinks."""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any

import pytest
from soothe.autopilot.notify.models import NotifyIntent, NotifyTarget
from soothe.config.models import (
    AutopilotNotifyConfig,
    EmailNotifySinkConfig,
    FeishuNotifySinkConfig,
    NotifyTargetConfig,
    WebhookNotifySinkConfig,
)

from soothe_daemon.notify.email_sink import EmailNotifySink
from soothe_daemon.notify.factory import build_notify_dispatcher
from soothe_daemon.notify.feishu_sink import FeishuNotifySink
from soothe_daemon.notify.protocol import NotifyDispatcher
from soothe_daemon.notify.webhook_sink import WebhookNotifySink


def _intent(kind: str = "job.failed") -> NotifyIntent:
    return NotifyIntent(
        kind=kind,  # type: ignore[arg-type]
        job_id="abc12345",
        title="[Soothe] Job abc12345 failed",
        body="Job: abc12345\nStatus: failed",
        severity="error",
        status="failed",
        generation="g1",
    )


@pytest.mark.asyncio
async def test_dispatcher_fanout_fail_soft() -> None:
    results_ok: list[str] = []

    class OkSink:
        name = "ok"

        def enabled(self) -> bool:
            return True

        async def deliver(self, intent: NotifyIntent, targets: list[NotifyTarget]) -> Any:
            from soothe.autopilot.notify.models import DeliveryResult

            del targets
            results_ok.append(intent.job_id)
            return DeliveryResult(sink=self.name, ok=True, detail="ok")

    class BoomSink:
        name = "boom"

        def enabled(self) -> bool:
            return True

        async def deliver(self, intent: NotifyIntent, targets: list[NotifyTarget]) -> Any:
            del intent, targets
            raise RuntimeError("boom")

    dispatcher = NotifyDispatcher([OkSink(), BoomSink()])
    results = await dispatcher.dispatch(_intent())
    assert len(results) == 2
    assert results_ok == ["abc12345"]
    by_name = {r.sink: r for r in results}
    assert by_name["ok"].ok is True
    assert by_name["boom"].ok is False


@pytest.mark.asyncio
async def test_email_sink_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[EmailMessage] = []

    cfg = EmailNotifySinkConfig(
        enabled=True,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="user",
        smtp_password="pass",
        from_address="soothe@example.com",
        targets=[NotifyTargetConfig(kind="email", to_address="ops@example.com")],
    )
    sink = EmailNotifySink(cfg)

    def _fake_send(self: EmailNotifySink, msg: EmailMessage) -> None:
        del self
        sent.append(msg)

    monkeypatch.setattr(EmailNotifySink, "_smtp_send", _fake_send)
    result = await sink.deliver(_intent(), [])
    assert result.ok is True
    assert sent and sent[0]["To"] == "ops@example.com"
    assert "failed" in (sent[0]["Subject"] or "")


@pytest.mark.asyncio
async def test_webhook_sink_posts() -> None:
    posts: list[tuple[str, dict[str, Any]]] = []

    async def _post(url: str, payload: dict[str, Any]) -> None:
        posts.append((url, payload))

    sink = WebhookNotifySink(
        WebhookNotifySinkConfig(
            enabled=True,
            urls={"job_failed": "https://hooks.example/job-failed"},
        ),
        http_post=_post,
    )
    result = await sink.deliver(_intent("job.failed"), [])
    assert result.ok is True
    assert posts and posts[0][0] == "https://hooks.example/job-failed"
    assert posts[0][1]["job_id"] == "abc12345"


@pytest.mark.asyncio
async def test_feishu_stub_skipped_when_disabled() -> None:
    sink = FeishuNotifySink(FeishuNotifySinkConfig(enabled=False))
    assert sink.enabled() is False


@pytest.mark.asyncio
async def test_feishu_stub_when_enabled() -> None:
    sink = FeishuNotifySink(
        FeishuNotifySinkConfig(
            enabled=True,
            app_id="cli_x",
            app_secret="sec",
            targets=[NotifyTargetConfig(kind="feishu_chat_id", to_address="oc_1")],
        )
    )
    assert sink.enabled() is True
    result = await sink.deliver(_intent(), [])
    assert result.ok is True
    assert "stub" in result.detail
    assert result.delivered_to == ["oc_1"]


@pytest.mark.asyncio
async def test_factory_registers_three_sinks() -> None:
    cfg = AutopilotNotifyConfig(enabled=True)
    dispatcher = build_notify_dispatcher(cfg)
    names = {s.name for s in dispatcher.sinks}
    assert names == {"email", "webhook", "feishu"}

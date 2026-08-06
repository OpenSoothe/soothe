"""Shared text rendering for notify sinks (IG-713)."""

from __future__ import annotations

from soothe.autopilot.notify.models import NotifyIntent


def intent_subject(intent: NotifyIntent) -> str:
    """Email / IM subject line from intent title."""
    return intent.title


def intent_plain_body(intent: NotifyIntent) -> str:
    """Plain-text body for email and simple IM messages."""
    return intent.body


def intent_html_body(intent: NotifyIntent) -> str:
    """Minimal HTML multipart alternative."""
    escaped = (
        intent.body.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>\n")
    )
    return (
        f"<html><body><p><strong>{_escape(intent.title)}</strong></p><p>{escaped}</p></body></html>"
    )


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def intent_webhook_payload(intent: NotifyIntent) -> dict:
    """JSON body for webhook POSTs."""
    return intent.model_dump(mode="json")

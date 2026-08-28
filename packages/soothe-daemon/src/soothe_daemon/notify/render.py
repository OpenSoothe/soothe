"""Shared text rendering for notify sinks."""

from __future__ import annotations

from html import escape
from typing import Any

from soothe_autopilot.notify.models import NotifyIntent

_SEVERITY_COLOR = {
    "info": "#2563eb",
    "warning": "#d97706",
    "error": "#dc2626",
}


def intent_subject(intent: NotifyIntent) -> str:
    """Email / IM subject line from intent title."""
    return intent.title


def intent_plain_body(intent: NotifyIntent) -> str:
    """Plain-text body for email and simple IM messages."""
    return intent.body


def intent_html_body(intent: NotifyIntent) -> str:
    """Structured HTML multipart alternative (progress counts, not full DAG)."""
    color = _SEVERITY_COLOR.get(intent.severity, "#334155")
    status = escape(str(intent.status or intent.kind))
    title = escape(intent.title)
    parts: list[str] = [
        "<!DOCTYPE html><html><body "
        'style="font-family:system-ui,-apple-system,sans-serif;'
        'font-size:14px;line-height:1.45;color:#0f172a;">',
        f'<p style="margin:0 0 12px 0;"><span style="display:inline-block;'
        f"padding:2px 8px;border-radius:4px;background:{color};color:#fff;"
        f'font-size:12px;font-weight:600;">{status}</span></p>',
        f'<h2 style="margin:0 0 8px 0;font-size:16px;">{title}</h2>',
    ]

    if intent.description:
        parts.append(
            f'<p style="margin:0 0 12px 0;color:#334155;">{escape(intent.description)}</p>'
        )

    meta_rows: list[tuple[str, str]] = [("Job", intent.job_id)]
    if intent.workspace:
        meta_rows.append(("Workspace", intent.workspace))
    if intent.error:
        meta_rows.append(("Error", intent.error))
    if intent.suspended_for_seconds is not None:
        mins = int(intent.suspended_for_seconds // 60)
        meta_rows.append(
            (
                "Suspended",
                f"{mins} minutes ({int(intent.suspended_for_seconds)}s)",
            )
        )
    maturity = intent.maturity if isinstance(intent.maturity, dict) else None
    if maturity:
        if "acceptance_met" in maturity:
            meta_rows.append(("Acceptance met", str(maturity.get("acceptance_met"))))
        if maturity.get("level"):
            meta_rows.append(("Maturity", str(maturity.get("level"))))
        blockers = maturity.get("blockers") or []
        if blockers:
            meta_rows.append(("Blockers", ", ".join(str(b) for b in blockers[:5])))

    parts.append(_meta_table(meta_rows))
    progress_html = _progress_html(intent.progress)
    if progress_html:
        parts.append(progress_html)

    parts.append(
        f'<p style="margin:16px 0 0 0;color:#64748b;font-size:12px;">'
        f"Inspect: <code>soothe autopilot job {escape(intent.job_id)}</code></p>"
    )
    parts.append("</body></html>")
    return "".join(parts)


def _meta_table(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return ""
    cells = "".join(
        f'<tr><td style="padding:2px 12px 2px 0;color:#64748b;vertical-align:top;">'
        f"{escape(label)}</td>"
        f'<td style="padding:2px 0;vertical-align:top;">{escape(value)}</td></tr>'
        for label, value in rows
        if value
    )
    return f'<table style="border-collapse:collapse;margin:0 0 12px 0;">{cells}</table>'


def _progress_html(progress: dict[str, Any] | None) -> str:
    if not progress or not isinstance(progress, dict):
        return ""
    total = int(progress.get("total_goals") or 0)
    if total <= 0:
        return ""
    completed = int(progress.get("completed_goals") or 0)
    pct = int(progress.get("pct_complete") or 0)
    pct = max(0, min(100, pct))
    bar = (
        f'<div style="margin:0 0 8px 0;background:#e2e8f0;border-radius:4px;'
        f'height:8px;overflow:hidden;">'
        f'<div style="width:{pct}%;height:8px;background:#2563eb;"></div></div>'
    )
    counts = (
        f'<p style="margin:0 0 8px 0;"><strong>Progress:</strong> '
        f"{completed}/{total} goals ({pct}%)</p>"
        f'<p style="margin:0 0 12px 0;color:#475569;font-size:13px;">'
        f"completed={int(progress.get('completed_goals') or 0)} · "
        f"failed={int(progress.get('failed_goals') or 0)} · "
        f"active={int(progress.get('active_goals') or 0)} · "
        f"pending={int(progress.get('pending_goals') or 0)} · "
        f"suspended={int(progress.get('suspended_goals') or 0)} · "
        f"cancelled={int(progress.get('cancelled_goals') or 0)}</p>"
    )
    highlights = progress.get("highlights") or []
    highlight_block = ""
    if isinstance(highlights, list) and highlights:
        rows = []
        for raw in highlights:
            if not isinstance(raw, dict):
                continue
            short = escape(str(raw.get("id") or "")[:8])
            status = escape(str(raw.get("status") or ""))
            role = escape(str(raw.get("role") or "").strip())
            desc = escape(str(raw.get("description") or "").strip())
            role_cell = f"<td style='padding:4px 8px;'>{role}</td>" if role else "<td></td>"
            rows.append(
                f"<tr>"
                f"<td style='padding:4px 8px;font-family:ui-monospace,monospace;'>"
                f"{short}</td>"
                f"<td style='padding:4px 8px;'>{status}</td>"
                f"{role_cell}"
                f"<td style='padding:4px 8px;'>{desc}</td>"
                f"</tr>"
            )
        omitted = int(progress.get("highlights_omitted") or 0)
        omit_note = (
            f'<p style="margin:4px 0 0 0;color:#64748b;font-size:12px;">'
            f"… ({omitted} more omitted)</p>"
            if omitted > 0
            else ""
        )
        highlight_block = (
            '<p style="margin:0 0 4px 0;"><strong>Needs attention</strong></p>'
            '<table style="border-collapse:collapse;width:100%;'
            'font-size:13px;margin:0 0 8px 0;">'
            "<thead><tr>"
            "<th align='left' style='padding:4px 8px;border-bottom:1px solid #e2e8f0;'>ID</th>"
            "<th align='left' style='padding:4px 8px;border-bottom:1px solid #e2e8f0;'>Status</th>"
            "<th align='left' style='padding:4px 8px;border-bottom:1px solid #e2e8f0;'>Role</th>"
            "<th align='left' style='padding:4px 8px;border-bottom:1px solid #e2e8f0;'>Description</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>{omit_note}"
        )
    return (
        '<div style="margin:12px 0;padding:12px;background:#f8fafc;'
        f'border-radius:6px;border:1px solid #e2e8f0;">{bar}{counts}{highlight_block}</div>'
    )


def intent_webhook_payload(intent: NotifyIntent) -> dict:
    """JSON body for webhook POSTs."""
    return intent.model_dump(mode="json")

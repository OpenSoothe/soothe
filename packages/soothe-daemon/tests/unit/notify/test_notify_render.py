"""IG-713: email HTML render includes progress, not full goal dump."""

from __future__ import annotations

from soothe.autopilot.notify.models import NotifyIntent

from soothe_daemon.notify.render import intent_html_body, intent_plain_body, intent_subject


def _intent_with_progress() -> NotifyIntent:
    return NotifyIntent(
        kind="job.failed",
        job_id="abcdefghijklmnop",
        title="[Soothe] Job abcdefgh failed (2/5)",
        body=(
            "Job: abcdefghijklmnop\n"
            "Status: failed\n"
            "\n"
            "Progress: 2/5 goals (40%)\n"
            "  completed=2 failed=1 active=0 pending=1 suspended=1 cancelled=0\n"
            "\n"
            "Needs attention:\n"
            "  - fail0001 (failed) [verify] boom\n"
        ),
        severity="error",
        status="failed",
        description="Ship feature",
        error="child verify failed",
        progress={
            "total_goals": 5,
            "completed_goals": 2,
            "failed_goals": 1,
            "active_goals": 0,
            "pending_goals": 1,
            "suspended_goals": 1,
            "cancelled_goals": 0,
            "pct_complete": 40,
            "highlights": [
                {
                    "id": "fail0001",
                    "status": "failed",
                    "role": "verify",
                    "description": "boom",
                }
            ],
            "highlights_omitted": 0,
        },
        generation="g1",
    )


def test_html_includes_progress_bar_and_highlights() -> None:
    html = intent_html_body(_intent_with_progress())
    assert "Progress:" in html
    assert "2/5 goals" in html
    assert "Needs attention" in html
    assert "fail0001"[:8] in html or "fail0001" in html
    assert "verify" in html
    assert "width:40%" in html
    assert "soothe autopilot job abcdefghijklmnop" in html
    # Must not dump every goal id as a row factory — only highlights table.
    assert html.count("<tbody>") == 1


def test_subject_and_plain_passthrough() -> None:
    intent = _intent_with_progress()
    assert intent_subject(intent) == intent.title
    assert intent_plain_body(intent) == intent.body

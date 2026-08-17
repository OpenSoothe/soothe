"""Drift review dashboard filter and trend-chart logic.

Tests the pure helpers in ``drift_review.py``:

- ``filter_findings`` — module/severity/time-range filtering
- ``bucket_by_day`` — daily alert-trend aggregation
- ``render_trend_bars`` — Unicode sparkline bar rendering
- ``parse_drift_json`` — parsing the drift script's JSON output
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from soothe_cli.tui.widgets.drift_review import (
    TIME_RANGE_SECONDS,
    bucket_by_day,
    filter_findings,
    parse_drift_json,
    render_trend_bars,
)


def _finding(
    module: str,
    severity: str,
    message: str,
    *,
    days_ago: float = 0.0,
) -> dict[str, str]:
    ts = (datetime.now(tz=timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {
        "module": module,
        "severity": severity,
        "message": message,
        "timestamp": ts,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# parse_drift_json
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_parse_drift_json_extracts_findings() -> None:
    """parse_drift_json returns findings list + generated_at from script output."""
    payload = {
        "errors": ["e1"],
        "warnings": ["w1"],
        "error_count": 1,
        "warning_count": 1,
        "strict": False,
        "generated_at": "2026-08-17T12:00:00+00:00",
        "findings": [
            {
                "module": "schema",
                "severity": "error",
                "message": "e1",
                "timestamp": "2026-08-17T12:00:01+00:00",
            },
            {
                "module": "field",
                "severity": "warning",
                "message": "w1",
                "timestamp": "2026-08-17T12:00:02+00:00",
            },
        ],
    }
    result = parse_drift_json(json.dumps(payload))
    assert result.generated_at == "2026-08-17T12:00:00+00:00"
    assert len(result.findings) == 2
    assert result.findings[0]["module"] == "schema"
    assert result.findings[1]["severity"] == "warning"


def test_parse_drift_json_handles_missing_findings_key() -> None:
    """Older/empty output without findings key yields empty list."""
    payload = {"errors": [], "warnings": [], "error_count": 0, "warning_count": 0}
    result = parse_drift_json(json.dumps(payload))
    assert result.findings == []
    assert result.generated_at == ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# filter_findings
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_filter_findings_by_module() -> None:
    """Module filter narrows findings to the selected module."""
    findings = [
        _finding("schema", "error", "a"),
        _finding("registry", "error", "b"),
        _finding("field", "warning", "c"),
    ]
    filtered = filter_findings(findings, module="schema", severity="all", time_range="all")
    assert len(filtered) == 1
    assert filtered[0]["module"] == "schema"


def test_filter_findings_by_severity() -> None:
    """Severity filter narrows to errors-only or warnings-only."""
    findings = [
        _finding("schema", "error", "a"),
        _finding("field", "warning", "b"),
        _finding("client", "warning", "c"),
    ]
    errors = filter_findings(findings, module="all", severity="error", time_range="all")
    assert len(errors) == 1
    warnings = filter_findings(findings, module="all", severity="warning", time_range="all")
    assert len(warnings) == 2


def test_filter_findings_by_time_range() -> None:
    """Time-range filter excludes findings older than the window."""
    findings = [
        _finding("schema", "error", "recent", days_ago=0.5),
        _finding("schema", "error", "old", days_ago=10.0),
    ]
    # 7-day window
    week = filter_findings(
        findings, module="all", severity="all", time_range="7d"
    )
    assert len(week) == 1
    assert week[0]["message"] == "recent"
    # 24-hour window
    day = filter_findings(
        findings, module="all", severity="all", time_range="24h"
    )
    assert len(day) == 1
    # all-time
    everything = filter_findings(
        findings, module="all", severity="all", time_range="all"
    )
    assert len(everything) == 2


def test_filter_findings_combined_filters() -> None:
    """All three filters compose with AND semantics."""
    findings = [
        _finding("schema", "error", "match", days_ago=1.0),
        _finding("schema", "warning", "wrong severity", days_ago=1.0),
        _finding("registry", "error", "wrong module", days_ago=1.0),
        _finding("schema", "error", "too old", days_ago=30.0),
    ]
    filtered = filter_findings(
        findings, module="schema", severity="error", time_range="7d"
    )
    assert len(filtered) == 1
    assert filtered[0]["message"] == "match"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# bucket_by_day
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_bucket_by_day_groups_by_date() -> None:
    """Findings on the same calendar day collapse into one bucket."""
    findings = [
        _finding("schema", "error", "a", days_ago=0.1),
        _finding("schema", "error", "b", days_ago=0.2),
        _finding("schema", "error", "c", days_ago=1.5),
    ]
    buckets = bucket_by_day(findings, days=7)
    assert len(buckets) == 7  # 7-day window → 7 day-slots (incl. empty days)
    # Two findings fall on the most recent day
    today_bucket = buckets[-1]
    assert today_bucket.count == 2


def test_bucket_by_day_severity_split() -> None:
    """Each day bucket splits counts by severity."""
    findings = [
        _finding("schema", "error", "e", days_ago=0.1),
        _finding("field", "warning", "w", days_ago=0.2),
    ]
    buckets = bucket_by_day(findings, days=3)
    today = buckets[-1]
    assert today.errors == 1
    assert today.warnings == 1
    assert today.count == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# render_trend_bars
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_render_trend_bars_scales_to_max() -> None:
    """Bar lengths scale relative to the peak day."""
    from soothe_cli.tui.widgets.drift_review import DayBucket

    buckets = [
        DayBucket(date="2026-08-15", errors=0, warnings=0),
        DayBucket(date="2026-08-16", errors=2, warnings=0),
        DayBucket(date="2026-08-17", errors=0, warnings=4),
    ]
    bars = render_trend_bars(buckets, max_width=20)
    assert len(bars) == 3
    # The peak day (count=4) should produce the longest bar
    assert len(bars[2].bar) > len(bars[0].bar)
    assert len(bars[1].bar) < len(bars[2].bar)


def test_render_trend_bars_empty_buckets() -> None:
    """All-zero buckets render empty bars."""
    from soothe_cli.tui.widgets.drift_review import DayBucket

    buckets = [
        DayBucket(date="2026-08-15", errors=0, warnings=0),
        DayBucket(date="2026-08-16", errors=0, warnings=0),
    ]
    bars = render_trend_bars(buckets, max_width=10)
    assert all(b.bar == "" for b in bars)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TIME_RANGE_SECONDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_time_range_seconds_mapping() -> None:
    """Known time-range keys map to expected second counts."""
    assert TIME_RANGE_SECONDS["24h"] == 86400
    assert TIME_RANGE_SECONDS["7d"] == 7 * 86400
    assert TIME_RANGE_SECONDS["30d"] == 30 * 86400
    assert TIME_RANGE_SECONDS["all"] is None

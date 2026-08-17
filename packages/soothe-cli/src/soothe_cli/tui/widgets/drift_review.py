"""Drift review dashboard (RFC-450 §11.3).

An interactive modal screen that renders AsyncAPI drift findings with
module / severity / time-range filters and a Unicode alert-trend chart
that updates on every filter change.

The dashboard sources its data from ``scripts/check_asyncapi_drift.py --json``
(via subprocess) and persists each run's findings to a JSONL history file
under ``SOOTHE_HOME`` so the time-range filter and trend chart have a
history to draw on across invocations.

No external charting library is available in this repo (only Textual/Rich),
so the alert-trend chart is a pure-Unicode stacked bar rendered as a
:class:`Static` widget.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Select, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.widgets import Select as SelectWidget

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Data source — drift script invocation + history persistence
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Repository root: this file lives at packages/soothe-cli/src/soothe_cli/tui/widgets/
_REPO_ROOT = Path(__file__).resolve().parents[5]
_DRIFT_SCRIPT = _REPO_ROOT / "scripts" / "check_asyncapi_drift.py"

# History JSONL lives under SOOTHE_HOME so it survives across sessions.
try:
    from soothe_sdk.paths import SOOTHE_HOME
except Exception:  # pragma: no cover - sdk always present in installed env
    SOOTHE_HOME = str(Path.home() / ".soothe")
_HISTORY_PATH = Path(SOOTHE_HOME) / "data" / "drift_history.jsonl"


def _history_path() -> Path:
    """Return the drift-history JSONL path, creating the parent dir if needed."""
    path = _HISTORY_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("Could not create drift history dir %s", path.parent)
    return path


def run_drift_check() -> list[dict[str, str]]:
    """Run the drift detector script and return its structured findings.

    Returns:
        A list of finding dicts (``module``, ``severity``, ``message``,
        ``timestamp``). Returns an empty list on failure.
    """
    if not _DRIFT_SCRIPT.exists():
        logger.error("Drift script not found at %s", _DRIFT_SCRIPT)
        return []
    try:
        proc = subprocess.run(
            [sys.executable, str(_DRIFT_SCRIPT), "--json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.error("Drift check subprocess failed: %s", exc)
        return []
    if proc.returncode not in (0, 1):
        logger.error("Drift check exited with %s: %s", proc.returncode, proc.stderr)
        return []
    result = parse_drift_json(proc.stdout)
    return result.findings


@dataclass
class DriftPayload:
    """Parsed output of ``check_asyncapi_drift.py --json``."""

    findings: list[dict[str, str]] = field(default_factory=list)
    generated_at: str = ""
    error_count: int = 0
    warning_count: int = 0


def parse_drift_json(stdout: str) -> DriftPayload:
    """Parse the drift script's JSON stdout into a :class:`DriftPayload`.

    Tolerates missing keys; returns an empty payload on invalid JSON.
    """
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return DriftPayload()
    if not isinstance(payload, dict):
        return DriftPayload()
    raw_findings = payload.get("findings", [])
    findings: list[dict[str, str]] = []
    if isinstance(raw_findings, list):
        for f in raw_findings:
            if isinstance(f, dict):
                findings.append(
                    {
                        "module": str(f.get("module", "")),
                        "severity": str(f.get("severity", "")),
                        "message": str(f.get("message", "")),
                        "timestamp": str(f.get("timestamp", "")),
                    }
                )
    return DriftPayload(
        findings=findings,
        generated_at=str(payload.get("generated_at", "")),
        error_count=int(payload.get("error_count", 0)),
        warning_count=int(payload.get("warning_count", 0)),
    )


def append_history(findings: list[dict[str, str]]) -> None:
    """Append a run's findings to the JSONL history file.

    Each line is a JSON object: ``{"run_at": <iso>, "findings": [...]}``.
    """
    if not findings:
        return
    record = {"run_at": datetime.now(tz=timezone.utc).isoformat(), "findings": findings}
    path = _history_path()
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        logger.warning("Could not append drift history to %s", path)


def load_history() -> list[dict[str, Any]]:
    """Load all historical drift runs from the JSONL file.

    Returns:
        A list of ``{"run_at": str, "findings": [dict, ...]}`` records,
        oldest first.
    """
    path = _history_path()
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict) and "findings" in rec:
                    records.append(rec)
    except OSError:
        logger.warning("Could not read drift history at %s", path)
    return records


def all_findings(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Flatten history records into a single findings list."""
    out: list[dict[str, str]] = []
    for rec in history:
        run_at = str(rec.get("run_at", ""))
        for f in rec.get("findings", []):
            if isinstance(f, dict):
                # Prefer the finding's own timestamp, fall back to run_at.
                f = dict(f)
                f.setdefault("timestamp", run_at)
                out.append(f)
    return out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Filter + trend logic (pure functions — unit-testable without Textual)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SEVERITIES = ("error", "warning")
MODULES = ("schema", "registry", "client", "field")
TIME_RANGES = ("1h", "24h", "7d", "30d", "all")

#: Time-range keys → cutoff in seconds (``None`` means all-time). Used by the
#: filter logic and surfaced as a public constant for tests / config consumers.
TIME_RANGE_SECONDS: dict[str, int | None] = {
    "1h": 3600,
    "24h": 86400,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
    "all": None,
}

_RANGE_DELTAS: dict[str, timedelta | None] = {
    key: timedelta(seconds=secs) if secs is not None else None
    for key, secs in TIME_RANGE_SECONDS.items()
}


def filter_findings(
    findings: list[dict[str, str]],
    *,
    module: str,
    severity: str,
    time_range: str,
) -> list[dict[str, str]]:
    """Filter findings by module, severity, and time range.

    Args:
        findings: Flat list of finding dicts.
        module: Module filter value; ``"all"`` disables the module filter.
        severity: Severity filter value; ``"all"`` disables the severity filter.
        time_range: One of ``TIME_RANGES``; ``"all"`` disables the time filter.

    Returns:
        The subset of findings matching all three filters.
    """
    now = datetime.now(tz=timezone.utc)
    delta = _RANGE_DELTAS.get(time_range)
    cutoff = now - delta if delta is not None else None

    out: list[dict[str, str]] = []
    for f in findings:
        if module != "all" and f.get("module") != module:
            continue
        if severity != "all" and f.get("severity") != severity:
            continue
        if cutoff is not None:
            ts = _parse_ts(f.get("timestamp", ""))
            if ts is None or ts < cutoff:
                continue
        out.append(f)
    return out


def _parse_ts(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp; return None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class DayBucket:
    """One calendar-day bucket of alert counts for the trend chart.

    Attributes:
        date: ``YYYY-MM-DD`` label for the bucket.
        errors: Number of error-severity findings in this day.
        warnings: Number of warning-severity findings in this day.
    """

    date: str
    errors: int = 0
    warnings: int = 0

    @property
    def count(self) -> int:
        """Total findings (errors + warnings) in this bucket."""
        return self.errors + self.warnings


@dataclass
class TrendBar:
    """A rendered Unicode bar for one time bucket in the alert-trend chart.

    Attributes:
        label: The bucket's date/hour label.
        bar: The Unicode bar string (``█`` for errors, ``░`` for warnings).
        count: Total findings represented by this bar.
    """

    label: str
    bar: str
    count: int


def bucket_by_day(
    findings: list[dict[str, str]], *, days: int = 7
) -> list[DayBucket]:
    """Bucket findings into ``days`` consecutive calendar-day slots.

    Returns one :class:`DayBucket` per day in the window (including empty
    days so the chart shows gaps), oldest first. Findings outside the window
    or with unparseable timestamps are dropped.

    Args:
        findings: Flat list of finding dicts (already module/severity filtered).
        days: Number of day-slots to produce (oldest → newest).

    Returns:
        ``days`` :class:`DayBucket` entries, oldest first.
    """
    today = datetime.now(tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    slots: dict[datetime, list[int, int]] = {}
    for d in range(days):
        slot = today - timedelta(days=days - 1 - d)
        slots[slot] = [0, 0]
    for f in findings:
        ts = _parse_ts(f.get("timestamp", ""))
        if ts is None:
            continue
        slot = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        if slot not in slots:
            continue  # outside the window
        sev = f.get("severity", "warning")
        if sev == "error":
            slots[slot][0] += 1
        else:
            slots[slot][1] += 1
    return [
        DayBucket(
            date=slot.strftime("%Y-%m-%d"),
            errors=e,
            warnings=w,
        )
        for slot, (e, w) in sorted(slots.items())
    ]


def render_trend_bars(
    buckets: list[DayBucket], *, max_width: int = 20
) -> list[TrendBar]:
    """Render Unicode bars for a list of :class:`DayBucket` entries.

    Bar lengths scale relative to the peak day's total count. Empty buckets
    (count 0) produce an empty bar string.

    Args:
        buckets: Day buckets (e.g. from :func:`bucket_by_day`).
        max_width: Character width of the longest bar.

    Returns:
        One :class:`TrendBar` per input bucket, in order.
    """
    max_total = max((b.count for b in buckets), default=0) or 1
    scale = max_width / max_total
    bars: list[TrendBar] = []
    for b in buckets:
        e_len = int(b.errors * scale)
        w_len = int(b.warnings * scale)
        bar = ("█" * e_len) + ("░" * w_len)
        bars.append(TrendBar(label=b.date, bar=bar, count=b.count))
    return bars


def trend_buckets(
    findings: list[dict[str, str]],
    *,
    time_range: str,
) -> list[tuple[str, int, int]]:
    """Bucket findings into time buckets for the alert-trend chart.

    Args:
        findings: Already-filtered findings (module + severity applied).
        time_range: The active time range, used to pick bucket granularity.

    Returns:
        A list of ``(label, error_count, warning_count)`` tuples, oldest
        first. The number of buckets depends on the time range.
    """
    if time_range == "all":
        return _bucket_by_day(findings, max_days=14)
    if time_range == "30d":
        return _bucket_by_day(findings, max_days=30)
    if time_range == "7d":
        return _bucket_by_day(findings, max_days=7)
    if time_range == "24h":
        return _bucket_by_hour(findings, max_hours=24)
    # 1h
    return _bucket_by_hour(findings, max_hours=6)


def _bucket_by_hour(
    findings: list[dict[str, str]], *, max_hours: int
) -> list[tuple[str, int, int]]:
    """Bucket findings into hourly slots."""
    now = datetime.now(tz=timezone.utc)
    buckets: dict[datetime, list[int, int]] = {}
    for h in range(max_hours):
        slot = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=h)
        buckets[slot] = [0, 0]
    for f in findings:
        ts = _parse_ts(f.get("timestamp", ""))
        if ts is None:
            continue
        slot = ts.replace(minute=0, second=0, microsecond=0)
        if slot not in buckets:
            continue  # outside the window
        sev = f.get("severity", "warning")
        if sev == "error":
            buckets[slot][0] += 1
        else:
            buckets[slot][1] += 1
    ordered = sorted(buckets.items())
    return [(slot.strftime("%H:00"), e, w) for slot, (e, w) in ordered]


def _bucket_by_day(
    findings: list[dict[str, str]], *, max_days: int
) -> list[tuple[str, int, int]]:
    """Bucket findings into daily slots."""
    now = datetime.now(tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    buckets: dict[datetime, list[int, int]] = {}
    for d in range(max_days):
        slot = now - timedelta(days=d)
        buckets[slot] = [0, 0]
    for f in findings:
        ts = _parse_ts(f.get("timestamp", ""))
        if ts is None:
            continue
        slot = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        if slot not in buckets:
            continue
        sev = f.get("severity", "warning")
        if sev == "error":
            buckets[slot][0] += 1
        else:
            buckets[slot][1] += 1
    ordered = sorted(buckets.items())
    return [(slot.strftime("%m-%d"), e, w) for slot, (e, w) in ordered]


def render_trend_chart(
    buckets: list[tuple[str, int, int]], *, max_bar_width: int = 20
) -> str:
    """Render a Unicode stacked bar chart for the alert trend.

    Args:
        buckets: Output of :func:`trend_buckets`.
        max_bar_width: Character width of the longest bar.

    Returns:
        A multi-line string suitable for a :class:`Static` widget.
    """
    if not buckets:
        return "(no data in range)"

    max_total = max((e + w for _, e, w in buckets), default=0) or 1
    scale = max_bar_width / max_total

    lines: list[str] = []
    # Header
    lines.append(f"{'Time':<8} {'Errors':<7} {'Warns':<6} Trend")
    lines.append("─" * (8 + 1 + 7 + 1 + 6 + 1 + max_bar_width + 2))
    for label, errs, warns in buckets:
        total = errs + warns
        e_bar = "█" * int(errs * scale)
        w_bar = "░" * int(warns * scale)
        bar = e_bar + w_bar
        lines.append(f"{label:<8} {errs:<7} {warns:<6} {bar}")
    legend = "█ errors  ░ warnings"
    lines.append("")
    lines.append(legend)
    return "\n".join(lines)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Widgets
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AlertTrendChart(Static):
    """A Unicode bar chart showing error/warning counts over time buckets.

    Update by setting :attr:`buckets`; the render refreshes reactively.
    """

    buckets: reactive[list[tuple[str, int, int]]] = reactive(list, layout=True)

    def __init__(self, *, classes: str = "") -> None:
        """Initialize the chart with no data."""
        super().__init__("", classes=classes)

    def watch_buckets(self, _buckets: list[tuple[str, int, int]]) -> None:
        """Re-render the chart when buckets change."""
        self.update(render_trend_chart(_buckets))


class DriftReviewScreen(ModalScreen[None]):
    """Interactive drift review dashboard.

    Renders three :class:`Select` filters (module, severity, time-range),
    an :class:`AlertTrendChart`, and a scrollable alert list. Changing any
    filter re-runs :func:`filter_findings` and refreshes both the chart and
    the list.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("r", "refresh", "Refresh", show=False),
    ]

    CSS = """
    DriftReviewScreen {
        align: center middle;
        background: transparent;
    }

    DriftReviewScreen > Vertical {
        width: 96;
        max-width: 95%;
        height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    DriftReviewScreen .drift-title {
        text-style: bold;
        color: $primary;
        text-align: center;
        margin-bottom: 1;
    }

    DriftReviewScreen .drift-filters {
        height: 3;
        margin-bottom: 1;
    }

    DriftReviewScreen .drift-filters Select {
        width: 1fr;
        margin: 0 1;
    }

    DriftReviewScreen .drift-filters Select:first-child {
        margin-left: 0;
    }

    DriftReviewScreen .drift-filters Select:last-child {
        margin-right: 0;
    }

    DriftReviewScreen .drift-chart {
        height: auto;
        min-height: 8;
        max-height: 16;
        background: $background;
        border: solid $surface-lighten-2;
        padding: 1 2;
        margin-bottom: 1;
    }

    DriftReviewScreen .drift-chart-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    DriftReviewScreen .drift-list {
        height: 1fr;
        min-height: 5;
        background: $background;
        border: solid $surface-lighten-2;
        padding: 0 1;
    }

    DriftReviewScreen .drift-row {
        height: auto;
        padding: 0 1;
    }

    DriftReviewScreen .drift-row-error {
        color: $error;
    }

    DriftReviewScreen .drift-row-warning {
        color: $warning;
    }

    DriftReviewScreen .drift-empty {
        color: $text-muted;
        text-style: italic;
        padding: 1 2;
    }

    DriftReviewScreen .drift-help {
        height: 1;
        color: $text-muted;
        text-style: italic;
        margin-top: 1;
        text-align: center;
    }
    """

    def __init__(self, *, findings: list[dict[str, str]] | None = None) -> None:
        """Initialize the dashboard.

        Args:
            findings: Pre-loaded findings (current run + history). When
                ``None``, the screen runs the drift check and loads history
                on mount.
        """
        super().__init__()
        self._all_findings: list[dict[str, str]] = findings or []
        self._filtered: list[dict[str, str]] = []

        # Reactive filter state
        self._module: str = "all"
        self._severity: str = "all"
        self._time_range: str = "all"

    def compose(self) -> ComposeResult:
        """Compose the dashboard layout."""
        with Vertical():
            yield Static("AsyncAPI Drift Review", classes="drift-title")
            with Horizontal(classes="drift-filters"):
                yield Select(
                    [(label, value) for value, label in self._module_options()],
                    id="drift-module-select",
                    value="all",
                )
                yield Select(
                    [(label, value) for value, label in self._severity_options()],
                    id="drift-severity-select",
                    value="all",
                )
                yield Select(
                    [(label, value) for value, label in self._time_range_options()],
                    id="drift-time-range-select",
                    value="all",
                )
            yield Static("Alert Trend", classes="drift-chart-title")
            yield AlertTrendChart(classes="drift-chart", id="drift-trend-chart")
            with VerticalScroll(classes="drift-list"):
                yield Static(
                    "(no findings)", classes="drift-empty", id="drift-list-empty"
                )
            yield Static(
                "Tab between filters • R refresh • Esc close",
                classes="drift-help",
            )

    @staticmethod
    def _module_options() -> list[tuple[str, str]]:
        opts = [("All modules", "all")]
        opts += [(m, m) for m in MODULES]
        return opts

    @staticmethod
    def _severity_options() -> list[tuple[str, str]]:
        opts = [("All severities", "all")]
        opts += [(s, s) for s in SEVERITIES]
        return opts

    @staticmethod
    def _time_range_options() -> list[tuple[str, str]]:
        labels = {"1h": "Last hour", "24h": "Last 24h", "7d": "Last 7 days", "all": "All time"}
        return [(labels[r], r) for r in TIME_RANGES]

    def on_mount(self) -> None:
        """Load findings (run drift check + history) then render."""
        if not self._all_findings:
            self._load_findings()
        self._apply_filters()

    def _load_findings(self) -> None:
        """Run the drift check and merge with history."""
        current = run_drift_check()
        if current:
            append_history(current)
        history = load_history()
        self._all_findings = all_findings(history) if history else current

    def _apply_filters(self) -> None:
        """Re-filter findings and refresh the chart + list."""
        self._filtered = filter_findings(
            self._all_findings,
            module=self._module,
            severity=self._severity,
            time_range=self._time_range,
        )
        self._refresh_chart()
        self._refresh_list()

    def _refresh_chart(self) -> None:
        """Update the alert-trend chart with bucketed, filtered findings."""
        chart = self.query_one("#drift-trend-chart", AlertTrendChart)
        buckets = trend_buckets(self._filtered, time_range=self._time_range)
        chart.buckets = buckets

    def _refresh_list(self) -> None:
        """Re-render the alert list rows."""
        container = self.query_one(".drift-list", VerticalScroll)
        # Remove existing rows (keep the empty placeholder)
        for child in list(container.children):
            if child.id != "drift-list-empty":
                container.remove(child)

        empty = container.query_one("#drift-list-empty", Static)
        if not self._filtered:
            empty.display = True
            empty.update("(no findings match the current filters)")
            return

        empty.display = False
        for f in self._filtered:
            sev = f.get("severity", "?")
            mod = f.get("module", "?")
            ts = f.get("timestamp", "")
            msg = f.get("message", "")
            row_cls = (
                "drift-row drift-row-error" if sev == "error" else "drift-row drift-row-warning"
            )
            label = f"[{sev}] {mod} • {ts}\n  {msg}"
            container.mount(Static(label, classes=row_cls))

    # ── Filter change handlers ───────────────────────────────────────

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle a filter change and refresh the dashboard."""
        if event.select.id == "drift-module-select":
            self._module = str(event.value)
        elif event.select.id == "drift-severity-select":
            self._severity = str(event.value)
        elif event.select.id == "drift-time-range-select":
            self._time_range = str(event.value)
        else:
            return
        self._apply_filters()

    # ── Actions ───────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        """Re-run the drift check and reload the dashboard."""
        self._all_findings = []
        self._load_findings()
        self._apply_filters()
        self.notify("Drift review refreshed", timeout=2)

    def action_cancel(self) -> None:
        """Close the dashboard."""
        self.dismiss(None)


__all__ = [
    "AlertTrendChart",
    "DayBucket",
    "DriftReviewScreen",
    "TIME_RANGE_SECONDS",
    "TrendBar",
    "all_findings",
    "append_history",
    "bucket_by_day",
    "filter_findings",
    "load_history",
    "parse_drift_json",
    "render_trend_bars",
    "render_trend_chart",
    "run_drift_check",
    "trend_buckets",
]

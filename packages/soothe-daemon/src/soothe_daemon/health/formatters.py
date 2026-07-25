"""Output formatters for health check reports."""

from __future__ import annotations

import json
import sys
from typing import TextIO

from soothe_daemon.health.models import CategoryResult, CheckStatus, HealthReport

STATUS_SYMBOLS_COLOR = {
    CheckStatus.OK: "✓",
    CheckStatus.WARNING: "⚠",
    CheckStatus.ERROR: "✗",
    CheckStatus.INFO: "ℹ",  # noqa: RUF001
    CheckStatus.SKIPPED: "○",
}

STATUS_SYMBOLS_PLAIN = {
    CheckStatus.OK: "[OK]",
    CheckStatus.WARNING: "[WARN]",
    CheckStatus.ERROR: "[ERROR]",
    CheckStatus.INFO: "[INFO]",
    CheckStatus.SKIPPED: "[SKIP]",
}

COLORS = {
    CheckStatus.OK: "\033[92m",
    CheckStatus.WARNING: "\033[93m",
    CheckStatus.ERROR: "\033[91m",
    CheckStatus.INFO: "\033[94m",
    CheckStatus.SKIPPED: "\033[90m",
    "reset": "\033[0m",
}


def _symbols(use_color: bool) -> dict[CheckStatus, str]:  # noqa: FBT001
    return STATUS_SYMBOLS_COLOR if use_color else STATUS_SYMBOLS_PLAIN


def _colorize(text: str, status: CheckStatus, *, use_color: bool) -> str:
    if not use_color:
        return text
    return f"{COLORS[status]}{text}{COLORS['reset']}"


def _format_check_lines(
    check_message: str,
    status: CheckStatus,
    details: dict,
    *,
    use_color: bool,
) -> list[str]:
    symbols = _symbols(use_color)
    lines = [_colorize(f"  {symbols[status]} {check_message}", status, use_color=use_color)]
    if status in (CheckStatus.ERROR, CheckStatus.WARNING) and details:
        for key, value in details.items():
            if key in ("impact", "remediation"):
                lines.append(
                    _colorize(f"    └─ {key.title()}: {value}", status, use_color=use_color)
                )
    return lines


def format_category_block(category: CategoryResult, *, use_color: bool = True) -> str:
    """Format a single category block for progressive or batch text output."""
    symbols = _symbols(use_color)
    title = category.category.replace("_", " ").title()
    header = f"{symbols[category.status]} {title}"
    if category.message:
        header += f" {category.message}"
    lines = [_colorize(header, category.status, use_color=use_color)]
    for check in category.checks:
        lines.extend(
            _format_check_lines(
                check.message,
                check.status,
                check.details,
                use_color=use_color,
            )
        )
    return "\n".join(lines)


def format_summary(report: HealthReport, *, use_color: bool = True) -> str:
    """Format overall status summary lines."""
    summary = report.get_summary()
    if report.overall_status == CheckStatus.OK:
        overall_msg = "All checks passed"
        overall_symbol = "✓" if use_color else "[OK]"
    elif report.overall_status in (CheckStatus.INFO, CheckStatus.SKIPPED):
        skipped_count = summary["skipped"] + summary["info"]
        overall_msg = f"System healthy ({skipped_count} optional checks skipped)"
        overall_symbol = "✓" if use_color else "[OK]"
    elif report.overall_status == CheckStatus.WARNING:
        overall_msg = f"WARNINGS ({summary['warning']} warnings, {summary['error']} errors)"
        overall_symbol = "⚠" if use_color else "[WARN]"
    else:
        overall_msg = f"CRITICAL ({summary['error']} errors, {summary['warning']} warnings)"
        overall_symbol = "✗" if use_color else "[ERROR]"

    line = _colorize(
        f"Overall Status: {overall_symbol} {overall_msg}",
        report.overall_status,
        use_color=use_color,
    )
    return f"{'━' * 60}\n{line}\n"


class ProgressiveReporter:
    """Stream diagnosis lines as each category finishes (text mode)."""

    def __init__(
        self,
        *,
        use_color: bool = True,
        stream: TextIO | None = None,
    ) -> None:
        self.use_color = use_color
        self.stream = stream if stream is not None else sys.stdout
        self._started = False

    def start(self) -> None:
        """Print progressive diagnosis header."""
        if self._started:
            return
        self._started = True
        self.stream.write("Soothe doctor — progressive diagnosis\n")
        self.stream.write("━" * 60 + "\n\n")
        self.stream.flush()

    def category_start(self, category: str) -> None:
        """Announce that a category is starting."""
        self.start()
        title = category.replace("_", " ").title()
        self.stream.write(f"▸ {title} …\n")
        self.stream.flush()

    def category_done(self, result: CategoryResult) -> None:
        """Print category results as soon as they are available."""
        # Replace the start marker with full block (re-print checks under category).
        # Keep the ▸ line already printed; append check lines only.
        for check in result.checks:
            for line in _format_check_lines(
                check.message,
                check.status,
                check.details,
                use_color=self.use_color,
            ):
                self.stream.write(f"{line}\n")
        # Category-level status hint
        symbols = _symbols(self.use_color)
        title = result.category.replace("_", " ").title()
        status_line = _colorize(
            f"  {symbols[result.status]} {title}: {result.status.value}",
            result.status,
            use_color=self.use_color,
        )
        self.stream.write(f"{status_line}\n\n")
        self.stream.flush()

    def finish(self, report: HealthReport) -> None:
        """Print overall summary after all categories."""
        self.stream.write(format_summary(report, use_color=self.use_color))
        self.stream.flush()


def format_text(report: HealthReport, use_color: bool = True) -> str:  # noqa: FBT001, FBT002
    """Format health report for terminal output.

    Args:
        report: Health report to format
        use_color: Whether to use ANSI color codes

    Returns:
        Formatted string for terminal output
    """
    lines = ["Soothe Health Check", "━" * 60, ""]
    for category in report.categories:
        lines.append(format_category_block(category, use_color=use_color))
        lines.append("")
    lines.append(format_summary(report, use_color=use_color).rstrip("\n"))
    lines.append("")
    return "\n".join(lines)


def format_json(report: HealthReport) -> str:
    """Format health report as JSON."""
    data = report.to_dict()
    data["summary"] = report.get_summary()
    return json.dumps(data, indent=2)


def format_markdown(report: HealthReport) -> str:
    """Format health report as Markdown."""
    lines = [
        "# Soothe Health Check Report",
        "",
        f"**Timestamp**: {report.timestamp}",
        f"**Daemon**: {report.daemon_version}",
        f"**Framework**: {report.soothe_version}",
    ]
    if report.config_path:
        lines.append(f"**Config**: `{report.config_path}`")
    lines.append("")

    status_emoji = {
        CheckStatus.OK: "✅",
        CheckStatus.WARNING: "⚠️",
        CheckStatus.ERROR: "❌",
        CheckStatus.INFO: "ℹ️",  # noqa: RUF001
        CheckStatus.SKIPPED: "⚪",
    }

    summary = report.get_summary()
    lines.extend(
        [
            "## Summary",
            "",
            f"- **Total Checks**: {summary['total']}",
            f"- {status_emoji[CheckStatus.OK]} **Passed**: {summary['ok']}",
            f"- {status_emoji[CheckStatus.WARNING]} **Warnings**: {summary['warning']}",
            f"- {status_emoji[CheckStatus.ERROR]} **Errors**: {summary['error']}",
            "",
            "## Details",
            "",
        ]
    )

    for category in report.categories:
        emoji = status_emoji[category.status]
        lines.append(f"### {emoji} {category.category.replace('_', ' ').title()}")
        lines.append("")
        for check in category.checks:
            check_emoji = status_emoji[check.status]
            lines.append(f"- {check_emoji} **{check.name}**: {check.message}")
            if check.details:
                for key, value in check.details.items():
                    if key in ("impact", "remediation"):
                        lines.append(f"  - **{key.title()}**: {value}")
        lines.append("")

    return "\n".join(lines)


def aggregate_status(statuses: list[CheckStatus]) -> CheckStatus:
    """Aggregate multiple statuses into one (worst wins)."""
    if not statuses:
        return CheckStatus.OK
    return max(statuses, key=lambda s: s.severity)

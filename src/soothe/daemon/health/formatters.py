"""Output formatters for health check reports."""

import json

from soothe.daemon.health.models import CheckStatus, HealthReport


def format_text(report: HealthReport, use_color: bool = True) -> str:  # noqa: FBT001, FBT002
    """Format health report for terminal output.

    Args:
        report: Health report to format
        use_color: Whether to use ANSI color codes

    Returns:
        Formatted string for terminal output
    """
    lines = []

    # Header
    lines.append("Soothe Health Check")
    lines.append("━" * 60)
    lines.append("")

    # Status symbols
    status_symbols = {
        CheckStatus.OK: "✓" if use_color else "[OK]",
        CheckStatus.WARNING: "⚠" if use_color else "[WARN]",
        CheckStatus.ERROR: "✗" if use_color else "[ERROR]",
        CheckStatus.INFO: "ℹ" if use_color else "[INFO]",  # noqa: RUF001
        CheckStatus.SKIPPED: "○" if use_color else "[SKIP]",
    }

    # Color codes
    colors = {
        CheckStatus.OK: "\033[92m",  # Green
        CheckStatus.WARNING: "\033[93m",  # Yellow
        CheckStatus.ERROR: "\033[91m",  # Red
        CheckStatus.INFO: "\033[94m",  # Blue
        CheckStatus.SKIPPED: "\033[90m",  # Gray
        "reset": "\033[0m",
    }

    def colorize(text: str, status: CheckStatus) -> str:
        """Apply color to text if enabled."""
        if not use_color:
            return text
        return f"{colors[status]}{text}{colors['reset']}"

    # Format each category
    for category in report.categories:
        symbol = status_symbols[category.status]
        category_line = f"{symbol} {category.category.replace('_', ' ').title()}"
        # Add category message if present (e.g., "(optional for basic usage)")
        if category.message:
            category_line += f" {category.message}"
        lines.append(colorize(category_line, category.status))

        # Format each check
        for check in category.checks:
            check_symbol = status_symbols[check.status]
            check_line = f"  {check_symbol} {check.message}"
            lines.append(colorize(check_line, check.status))

            # Add details for errors/warnings
            if check.status in (CheckStatus.ERROR, CheckStatus.WARNING) and check.details:
                for key, value in check.details.items():
                    if key in ("impact", "remediation"):
                        indent = "    └─ "
                        detail_line = f"{indent}{key.title()}: {value}"
                        lines.append(colorize(detail_line, check.status))

        lines.append("")

    # Summary
    lines.append("━" * 60)
    summary = report.get_summary()

    # Improved overall status message
    if report.overall_status == CheckStatus.OK:
        overall_msg = "All checks passed"
        overall_symbol = "✓"
    elif report.overall_status in (CheckStatus.INFO, CheckStatus.SKIPPED):
        # INFO/SKIPPED are non-critical
        skipped_count = summary["skipped"] + summary["info"]
        overall_msg = f"System healthy ({skipped_count} optional checks skipped)"
        overall_symbol = "✓"
    elif report.overall_status == CheckStatus.WARNING:
        overall_msg = f"WARNINGS ({summary['warning']} warnings, {summary['error']} errors)"
        overall_symbol = "⚠"
    else:  # ERROR
        overall_msg = f"CRITICAL ({summary['error']} errors, {summary['warning']} warnings)"
        overall_symbol = "✗"

    lines.append(colorize(f"Overall Status: {overall_symbol} {overall_msg}", report.overall_status))
    lines.append("")

    return "\n".join(lines)


def format_json(report: HealthReport) -> str:
    """Format health report as JSON.

    Args:
        report: Health report to format

    Returns:
        JSON string
    """
    data = report.to_dict()
    data["summary"] = report.get_summary()
    return json.dumps(data, indent=2)


def format_markdown(report: HealthReport) -> str:
    """Format health report as Markdown.

    Args:
        report: Health report to format

    Returns:
        Markdown string
    """
    lines = []

    # Header
    lines.append("# Soothe Health Check Report")
    lines.append("")
    lines.append(f"**Timestamp**: {report.timestamp}")
    lines.append(f"**Version**: {report.soothe_version}")
    if report.config_path:
        lines.append(f"**Config**: `{report.config_path}`")
    lines.append("")

    # Status emojis
    status_emoji = {
        CheckStatus.OK: "✅",
        CheckStatus.WARNING: "⚠️",
        CheckStatus.ERROR: "❌",
        CheckStatus.INFO: "ℹ️",  # noqa: RUF001
        CheckStatus.SKIPPED: "⚪",
    }

    # Summary
    summary = report.get_summary()
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total Checks**: {summary['total']}")
    lines.append(f"- {status_emoji[CheckStatus.OK]} **Passed**: {summary['ok']}")
    lines.append(f"- {status_emoji[CheckStatus.WARNING]} **Warnings**: {summary['warning']}")
    lines.append(f"- {status_emoji[CheckStatus.ERROR]} **Errors**: {summary['error']}")
    lines.append("")

    # Categories
    lines.append("## Details")
    lines.append("")

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
    """Aggregate multiple statuses into one (worst wins).

    Args:
        statuses: List of check statuses

    Returns:
        Aggregated status (worst severity)
    """
    if not statuses:
        return CheckStatus.OK

    # Find the worst status
    worst = CheckStatus.OK
    for status in statuses:
        worst = max(worst, status)

    return worst

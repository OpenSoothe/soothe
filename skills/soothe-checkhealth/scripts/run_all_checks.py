#!/usr/bin/env python3
"""Run all health checks and generate comprehensive report.

Orchestrates all check scripts and produces a markdown health report.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Color codes for terminal output
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"  # No Color


def echo_info(msg: str) -> None:
    """Print info message."""
    print(f"{BLUE}[INFO]{NC} {msg}")


def echo_ok(msg: str) -> None:
    """Print success message."""
    print(f"{GREEN}[OK]{NC}   {msg}")


def echo_warn(msg: str) -> None:
    """Print warning message."""
    print(f"{YELLOW}[WARN]{NC} {msg}")


def echo_err(msg: str) -> None:
    """Print error message."""
    print(f"{RED}[ERR]{NC}  {msg}")


def run_script(script_name: str) -> dict[str, Any]:
    """Run a check script and return its JSON output."""
    script_path = Path(__file__).parent / script_name

    # Set PYTHONPATH to include the source directory
    import os

    repo_root = Path(__file__).parent.parent.parent.parent
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src") + ":" + env.get("PYTHONPATH", "")

    try:
        result = subprocess.run(
            ["uv", "run", "python", str(script_path)],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )

        if result.returncode not in (0, 1, 2):
            echo_warn(f"{script_name} returned unexpected exit code {result.returncode}")

        output = json.loads(result.stdout)
        return output

    except subprocess.TimeoutExpired:
        echo_err(f"{script_name} timed out")
        return {
            "category": script_name.replace("check_", "").replace(".py", ""),
            "status": "error",
            "checks": [
                {
                    "name": "script_timeout",
                    "status": "error",
                    "message": f"Script {script_name} timed out",
                }
            ],
        }
    except json.JSONDecodeError as e:
        echo_err(f"{script_name} produced invalid JSON: {e}")
        return {
            "category": script_name.replace("check_", "").replace(".py", ""),
            "status": "error",
            "checks": [
                {
                    "name": "json_error",
                    "status": "error",
                    "message": f"Invalid JSON from {script_name}: {e}",
                }
            ],
        }
    except Exception as e:
        echo_err(f"Failed to run {script_name}: {e}")
        return {
            "category": script_name.replace("check_", "").replace(".py", ""),
            "status": "error",
            "checks": [
                {
                    "name": "script_error",
                    "status": "error",
                    "message": f"Failed to run {script_name}: {e}",
                }
            ],
        }


def flatten_checks(categories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten nested checks into a single list."""
    flat = []
    for cat in categories:
        if "checks" in cat:
            for check in cat["checks"]:
                if "checks" in check:
                    # Nested checks (e.g., protocol subcategories)
                    flat.extend(check["checks"])
                else:
                    flat.append(check)
        else:
            flat.append(cat)
    return flat


def generate_report(results: list[dict[str, Any]], config_path: str) -> str:
    """Generate markdown health report."""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Count checks
    flat_checks = flatten_checks(results)
    total = len(flat_checks)
    passed = sum(1 for c in flat_checks if c["status"] == "ok")
    warnings = sum(1 for c in flat_checks if c["status"] in ("warning", "info"))
    errors = sum(1 for c in flat_checks if c["status"] == "error")

    # Determine overall status
    if errors > 0:
        overall = "CRITICAL"
        overall_icon = "❌"
    elif warnings > 0:
        overall = "WARNINGS"
        overall_icon = "⚠️"
    else:
        overall = "HEALTHY"
        overall_icon = "✅"

    # Build report
    lines = [
        "# Soothe Health Report",
        "",
        f"**Generated**: {timestamp}",
        "**Soothe Version**: 1.0.0",
        f"**Configuration**: {config_path}",
        f"**Overall Status**: {overall_icon} {overall}",
        "",
        "## Summary",
        "",
        "| Category | Status | Checks Passed | Total Checks |",
        "|----------|--------|---------------|--------------|",
    ]

    # Category summary
    for cat in results:
        cat_name = cat.get("category", "unknown").replace("_", " ").title()
        cat_checks = flatten_checks([cat])
        cat_total = len(cat_checks)
        cat_passed = sum(1 for c in cat_checks if c["status"] == "ok")

        if cat["status"] == "healthy":
            icon = "✅"
            status = "Healthy"
        elif cat["status"] == "warning":
            icon = "⚠️"
            status = "Warnings"
        else:
            icon = "❌"
            status = "Critical"

        lines.append(f"| {cat_name} | {icon} {status} | {cat_passed}/{cat_total} | {cat_total} |")

    lines.extend(
        [
            "",
            f"**Total**: {passed}/{total} checks passed ({100 * passed // total if total > 0 else 0}%)",
            "",
            "## Detailed Results",
            "",
        ]
    )

    # Detailed results per category
    for cat in results:
        cat_name = cat.get("category", "unknown").replace("_", " ").title()
        lines.append(f"### {cat_name}")
        lines.append("")

        cat_checks = flatten_checks([cat])
        for check in cat_checks:
            name = check.get("name", "unknown").replace("_", " ").title()
            status = check.get("status", "unknown")
            message = check.get("message", "No message")

            if status == "ok":
                icon = "✅"
            elif status in ("warning", "info"):
                icon = "⚠️" if status == "warning" else "ℹ️"
            else:
                icon = "❌"

            lines.append(f"#### {name}")
            lines.append(f"- **Status**: {icon} {status.upper()}")
            lines.append(f"- **Details**: {message}")

            if "details" in check:
                for key, value in check["details"].items():
                    lines.append(f"- **{key.replace('_', ' ').title()}**: {value}")

            lines.append("")

    # Issues section
    lines.extend(
        [
            "## Issues Found",
            "",
        ]
    )

    critical_issues = [c for c in flat_checks if c["status"] == "error"]
    warning_issues = [c for c in flat_checks if c["status"] == "warning"]
    info_issues = [c for c in flat_checks if c["status"] == "info"]

    # Critical issues
    if critical_issues:
        lines.append("### Critical Issues")
        lines.append("")
        for i, issue in enumerate(critical_issues, 1):
            name = issue.get("name", "unknown").replace("_", " ").title()
            message = issue.get("message", "No message")
            lines.append(f"{i}. **{name}**")
            lines.append(f"   - **Message**: {message}")
            lines.append("   - **Impact**: This may prevent core functionality")
            lines.append("   - **Remediation**: Check logs and configuration")
            lines.append("")
    else:
        lines.extend(
            [
                "### Critical Issues",
                "None",
                "",
            ]
        )

    # Warnings
    if warning_issues:
        lines.append("### Warnings")
        lines.append("")
        for i, issue in enumerate(warning_issues, 1):
            name = issue.get("name", "unknown").replace("_", " ").title()
            message = issue.get("message", "No message")
            lines.append(f"{i}. **{name}**")
            lines.append(f"   - **Message**: {message}")
            lines.append("   - **Impact**: May affect optional features")
            lines.append("   - **Remediation**: Check configuration or install missing dependencies")
            lines.append("")
    else:
        lines.extend(
            [
                "### Warnings",
                "None",
                "",
            ]
        )

    # Info
    if info_issues:
        lines.append("### Informational")
        lines.append("")
        for i, issue in enumerate(info_issues, 1):
            name = issue.get("name", "unknown").replace("_", " ").title()
            message = issue.get("message", "No message")
            lines.append(f"{i}. **{name}**")
            lines.append(f"   - **Message**: {message}")
            lines.append("")
    else:
        lines.extend(
            [
                "### Informational",
                "None",
                "",
            ]
        )

    # Recommendations
    lines.extend(
        [
            "## Recommendations",
            "",
        ]
    )

    if critical_issues or warning_issues:
        recs = []
        if any("daemon" in c.get("name", "") for c in critical_issues):
            recs.append("Restart the daemon: `soothe --daemon`")
        if any("postgresql" in c.get("name", "") for c in critical_issues + warning_issues):
            recs.append("Check PostgreSQL connection and run migrations if needed")
        if any("rocksdb" in c.get("name", "") for c in warning_issues):
            recs.append("Install RocksDB: `pip install python-rocksdb`")
        if any("browser" in c.get("name", "") for c in warning_issues):
            recs.append("Fix chromedriver: `bash scripts/check_chrome.sh`")

        if not recs:
            recs.append("Review the issues above and check configuration")

        for i, rec in enumerate(recs, 1):
            lines.append(f"{i}. {rec}")
        lines.append("")
    else:
        lines.extend(
            [
                "All checks passed. No recommendations at this time.",
                "",
            ]
        )

    lines.extend(
        [
            "---",
            "*Generated by Soothe Health Check Skill*",
        ]
    )

    return "\n".join(lines)


def main() -> int:
    """Run all health checks and generate report."""
    parser = argparse.ArgumentParser(description="Run Soothe health checks")
    parser.add_argument(
        "--config",
        type=str,
        default="~/.soothe/config/config.yml",
        help="Config file path (default: ~/.soothe/config/config.yml)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output report path (default: ~/.soothe/health_report_<timestamp>.md)",
    )
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path.home() / ".soothe" / f"health_report_{timestamp}.md"

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    echo_info("Starting Soothe health checks...")
    print()

    # Run all check scripts
    scripts = [
        "check_daemon.py",
        "check_protocols.py",
        "check_persistence.py",
        "check_tui.py",
        "check_subagents.py",
        "check_external_apis.py",
    ]

    results = []
    for script in scripts:
        echo_info(f"Running {script}...")
        result = run_script(script)
        results.append(result)

        # Print summary
        cat_name = result.get("category", "unknown").replace("_", " ").title()
        if result["status"] == "healthy":
            echo_ok(f"{cat_name}: All checks passed")
        elif result["status"] == "warning":
            echo_warn(f"{cat_name}: Warnings detected")
        else:
            echo_err(f"{cat_name}: Critical issues found")

    print()
    echo_info("Generating health report...")

    # Generate report
    report = generate_report(results, str(config_path))

    # Write report
    output_path.write_text(report)
    echo_ok(f"Report saved to: {output_path}")

    # Determine exit code
    flat_checks = flatten_checks(results)
    errors = sum(1 for c in flat_checks if c["status"] == "error")
    warnings = sum(1 for c in flat_checks if c["status"] in ("warning", "info"))

    print()
    if errors > 0:
        echo_err(f"Health check complete: {errors} critical issues, {warnings} warnings")
        return 2
    if warnings > 0:
        echo_warn(f"Health check complete: {warnings} warnings")
        return 1
    echo_ok("Health check complete: All systems healthy")
    return 0


if __name__ == "__main__":
    sys.exit(main())

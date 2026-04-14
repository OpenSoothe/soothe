"""Health check CLI command implementation."""

import asyncio
import sys
from typing import Annotated, Literal

import typer

from soothe.ux.shared import load_config


def run_health_checks(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    output: Annotated[
        Literal["text", "json"],
        typer.Option("--output", "-o", help="Output format: text or json."),
    ] = "text",
    quiet: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--quiet", "-q", help="Suppress output, return exit code only."),
    ] = False,
    categories: Annotated[
        list[str] | None,
        typer.Option("--check", help="Run specific checks (can be used multiple times)."),
    ] = None,
    exclude: Annotated[
        list[str] | None,
        typer.Option("--exclude", help="Exclude checks (can be used multiple times)."),
    ] = None,
    save_report: Annotated[
        str | None,
        typer.Option("--save-report", help="Save report to file (markdown format)."),
    ] = None,
) -> None:
    """Run comprehensive health checks.

    Validates configuration and checks backend service availability including
    PostgreSQL, LLM providers, vector stores, and external APIs.

    Exit codes:
        0: All checks passed
        1: Warnings present (non-critical issues)
        2: Critical issues found

    Examples:
        soothe doctor
        soothe doctor --output json
        soothe doctor --check daemon --check persistence
        soothe doctor --exclude external_apis
        soothe doctor --save-report report.md
        soothe doctor --quiet
    """
    from pathlib import Path

    from soothe.daemon.health import HealthChecker, format_json, format_markdown, format_text
    from soothe.daemon.health.models import CheckStatus

    try:
        # Load config if provided
        cfg = None
        try:
            if config:
                cfg = load_config(config)
        except Exception as e:
            if not quiet:
                typer.echo(f"Warning: Could not load config: {e}", err=True)
                typer.echo("Running basic checks without config.\n", err=True)

        # Create health checker
        checker = HealthChecker(cfg)

        # Run health checks
        if not quiet and output == "text":
            typer.echo("Running health checks...\n")

        report = asyncio.run(checker.run_all_checks(categories=categories, exclude=exclude))

        # Output results
        if not quiet:
            output_str = format_json(report) if output == "json" else format_text(report, use_color=True)
            typer.echo(output_str)

        # Save report if requested
        if save_report:
            report_path = Path(save_report)
            report_content = format_markdown(report)

            # Use FrameworkFilesystem for consistency
            try:
                from soothe.core import FrameworkFilesystem

                backend = FrameworkFilesystem.get()
                backend.write(str(report_path), report_content)
            except RuntimeError:
                # FrameworkFilesystem not initialized - fallback to direct write
                report_path.write_text(report_content)

            if not quiet:
                typer.echo(f"\nReport saved to: {report_path}")

        # Set exit code based on severity
        # INFO/SKIPPED are non-critical (exit 0 if only INFO/SKIPPED)
        # WARNING is caution (exit 1)
        # ERROR is critical (exit 2)
        if report.overall_status in (CheckStatus.OK, CheckStatus.INFO, CheckStatus.SKIPPED):
            exit_code = 0
        elif report.overall_status == CheckStatus.WARNING:
            exit_code = 1
        else:  # ERROR
            exit_code = 2

        sys.exit(exit_code)

    except KeyboardInterrupt:
        typer.echo("\nInterrupted.")
        sys.exit(130)
    except Exception as e:
        if not quiet:
            typer.echo(f"Error: {e}", err=True)
        sys.exit(2)

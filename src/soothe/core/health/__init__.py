"""Health check library for Soothe.

This module provides comprehensive health checking for Soothe components
including configuration, daemon, persistence, providers, and external services.

Example usage:

    from soothe.core.health import HealthChecker
    from soothe.ux.core import load_config

    # With config
    config = load_config()
    checker = HealthChecker(config)
    report = await checker.run_all_checks()

    # Standalone (no config)
    checker = HealthChecker()
    report = await checker.run_all_checks()

    # Specific categories only
    report = await checker.run_all_checks(
        categories=["daemon", "persistence"]
    )

    # Get JSON output
    from soothe.core.health import format_json
    json_output = format_json(report)
"""

from soothe.core.health.checker import HealthChecker
from soothe.core.health.formatters import format_json, format_markdown, format_text
from soothe.core.health.models import CategoryResult, CheckResult, CheckStatus, HealthReport

__all__ = [
    "CategoryResult",
    "CheckResult",
    "CheckStatus",
    "HealthChecker",
    "HealthReport",
    "format_json",
    "format_markdown",
    "format_text",
]

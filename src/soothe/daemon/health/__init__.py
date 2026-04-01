"""Health check library for Soothe.

This module provides comprehensive health checking for Soothe components
including configuration, daemon, persistence, providers, and external services.

Example usage:

    from soothe.daemon.health import HealthChecker
    from soothe.ux.core import load_config

    # With config
    config = load_config()
    checker = HealthChecker(config)
    report = await checker.run_all_checks()

    # Basic checks (no config)
    checker = HealthChecker()
    report = await checker.run_all_checks()

    # Specific categories only
    report = await checker.run_all_checks(
        categories=["daemon", "persistence"]
    )

    # Get JSON output
    from soothe.daemon.health import format_json
    json_output = format_json(report)
"""

from soothe.daemon.health.checker import HealthChecker
from soothe.daemon.health.formatters import format_json, format_markdown, format_text
from soothe.daemon.health.models import CategoryResult, CheckResult, CheckStatus, HealthReport

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

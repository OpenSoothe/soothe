"""Health check library for Soothe.

This module provides comprehensive health checking for Soothe components
including configuration, daemon, persistence, providers, and external services.

Example usage:

    from soothe.config import SootheConfig
    from soothe_daemon.config import SootheDaemonConfig
    from soothe_daemon.health import HealthChecker

    # With config
    config = SootheConfig()
    daemon_config = SootheDaemonConfig()
    checker = HealthChecker(config, daemon_config)
    report = await checker.run_all_checks()

    # Basic checks (no config)
    checker = HealthChecker()
    report = await checker.run_all_checks()

    # Specific categories only
    report = await checker.run_all_checks(
        categories=["daemon", "persistence"]
    )

    # Get JSON output
    from soothe_daemon.health import format_json
    json_output = format_json(report)
"""

from soothe_daemon.health.checker import HealthChecker
from soothe_daemon.health.formatters import format_json, format_markdown, format_text
from soothe_daemon.health.models import (
    CategoryResult,
    CheckResult,
    CheckStatus,
    HealthReport,
)

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

"""Health check library for Soothe.

Vital-first doctor checks for soothed (tool deps, persistence, providers,
observability, daemon) with optional ``--deep`` categories.

Example usage:

    from soothe.config import SootheConfig
    from soothe_daemon.config import SootheDaemonConfig
    from soothe_daemon.health import HealthChecker

    checker = HealthChecker(config, daemon_config)
    report = await checker.run_all_checks()  # vitals
    report = await checker.run_all_checks(deep=True)  # + optional
"""

from soothe_daemon.health.checker import (
    ALL_CATEGORIES,
    DEEP_CATEGORIES,
    VITAL_CATEGORIES,
    HealthChecker,
)
from soothe_daemon.health.formatters import (
    ProgressiveReporter,
    format_json,
    format_markdown,
    format_text,
)
from soothe_daemon.health.models import (
    CategoryResult,
    CheckResult,
    CheckStatus,
    HealthReport,
)

__all__ = [
    "ALL_CATEGORIES",
    "DEEP_CATEGORIES",
    "VITAL_CATEGORIES",
    "CategoryResult",
    "CheckResult",
    "CheckStatus",
    "HealthChecker",
    "HealthReport",
    "ProgressiveReporter",
    "format_json",
    "format_markdown",
    "format_text",
]

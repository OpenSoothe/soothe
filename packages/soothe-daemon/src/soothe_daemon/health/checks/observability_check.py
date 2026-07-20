"""Observability and tracing health check implementation."""

import importlib.util
import os
from typing import Any

from soothe.config import SootheConfig
from soothe_nano.utils.observability.langfuse import resolve_langfuse_config_str

from soothe_daemon.health.formatters import aggregate_status
from soothe_daemon.health.models import CategoryResult, CheckResult, CheckStatus


def _check_langfuse_from_config(config: SootheConfig | None) -> CheckResult:
    """Check Langfuse integration when enabled in ``observability.langfuse``."""
    if config is None:
        return CheckResult(
            name="langfuse",
            status=CheckStatus.INFO,
            message="Langfuse: no config loaded (skipped)",
            details={},
        )
    lf = config.observability.langfuse
    if not lf.enabled:
        return CheckResult(
            name="langfuse",
            status=CheckStatus.INFO,
            message="Langfuse integration disabled (observability.langfuse.enabled=false)",
            details={"enabled": False},
        )
    if importlib.util.find_spec("langfuse") is None:
        return CheckResult(
            name="langfuse",
            status=CheckStatus.WARNING,
            message="Langfuse enabled in config but the langfuse package is not installed",
            details={
                "enabled": True,
                "remediation": "pip install langfuse",
            },
        )

    pub = (
        resolve_langfuse_config_str(lf.public_key)
        or os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    )
    sec = (
        resolve_langfuse_config_str(lf.secret_key)
        or os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    )
    details: dict[str, Any] = {
        "enabled": True,
        "public_key_present": bool(pub),
        "secret_key_present": bool(sec),
    }
    host = resolve_langfuse_config_str(lf.host) or os.environ.get("LANGFUSE_HOST", "").strip()
    if host:
        details["host"] = host

    if pub and sec:
        details["cost_dashboard"] = "model pricing and verification"
        return CheckResult(
            name="langfuse",
            status=CheckStatus.OK,
            message="Langfuse tracing enabled with credentials available",
            details=details,
        )
    return CheckResult(
        name="langfuse",
        status=CheckStatus.WARNING,
        message="Langfuse enabled but credentials are incomplete",
        details={
            **details,
            "remediation": "Set observability.langfuse.public_key / secret_key (or LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY)",
        },
    )


def _check_dotenv_availability() -> CheckResult:
    """Check if python-dotenv is available and .env file exists.

    Returns:
        CheckResult with dotenv status
    """
    try:
        from pathlib import Path

        # Check if .env file exists in current directory or parent directories
        env_file = Path(".env")
        env_exists = env_file.exists()

        details = {
            "dotenv_installed": True,
            "env_file_exists": env_exists,
        }

        if env_exists:
            # Check if .env is in .gitignore
            gitignore = Path(".gitignore")
            if gitignore.exists():
                gitignore_content = gitignore.read_text()
                env_ignored = ".env" in gitignore_content
                details["env_in_gitignore"] = env_ignored

                if not env_ignored:
                    return CheckResult(
                        name="dotenv_setup",
                        status=CheckStatus.WARNING,
                        message=".env file exists but not in .gitignore",
                        details={
                            **details,
                            "remediation": "Add .env to .gitignore to prevent committing secrets",
                        },
                    )

            return CheckResult(
                name="dotenv_setup",
                status=CheckStatus.OK,
                message=".env file found and properly configured",
                details=details,
            )
        return CheckResult(
            name="dotenv_setup",
            status=CheckStatus.INFO,
            message="No .env file found (using system environment)",
            details={
                **details,
                "remediation": "Set observability.langfuse in config YAML and export referenced env vars (or use literals for local dev only)",
            },
        )

    except ImportError:
        return CheckResult(
            name="dotenv_setup",
            status=CheckStatus.WARNING,
            message="python-dotenv not installed",
            details={
                "dotenv_installed": False,
                "remediation": "Install python-dotenv: pip install python-dotenv",
            },
        )


async def check_observability(config: SootheConfig | None = None) -> CategoryResult:
    """Check observability and tracing configuration.

    Validates Langfuse configuration when enabled, environment variable setup,
    and observability tooling configuration.

    Args:
        config: SootheConfig instance (used for Langfuse integration checks).

    Returns:
        CategoryResult with observability check results
    """
    checks = [
        _check_langfuse_from_config(config),
        _check_dotenv_availability(),
    ]

    overall_status = aggregate_status([check.status for check in checks])

    return CategoryResult(
        category="observability",
        status=overall_status,
        checks=checks,
    )

"""Observability and tracing health check implementation."""

import os

from soothe.config import SootheConfig
from soothe.daemon.health.formatters import aggregate_status
from soothe.daemon.health.models import CategoryResult, CheckResult, CheckStatus


def _check_langsmith_config() -> CheckResult:
    """Check LangSmith configuration and availability.

    Returns:
        CheckResult with LangSmith configuration status
    """
    # Check for LangSmith environment variables (new naming)
    langsmith_tracing = os.getenv("LANGSMITH_TRACING", "").lower()
    langsmith_api_key = os.getenv("LANGSMITH_API_KEY")
    langsmith_project = os.getenv("LANGSMITH_PROJECT")
    langsmith_endpoint = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")

    # Check for legacy LangChain environment variables
    langchain_tracing = os.getenv("LANGCHAIN_TRACING_V2", "").lower()
    langchain_api_key = os.getenv("LANGCHAIN_API_KEY")
    langchain_project = os.getenv("LANGCHAIN_PROJECT")

    # Determine if tracing is enabled
    tracing_enabled = langsmith_tracing == "true" or langchain_tracing == "true"
    has_api_key = bool(langsmith_api_key or langchain_api_key)

    # Build details dict
    details = {
        "tracing_enabled": tracing_enabled,
        "api_key_present": has_api_key,
    }

    if langsmith_project:
        details["project"] = langsmith_project
    elif langchain_project:
        details["project"] = langchain_project

    if langsmith_endpoint:
        details["endpoint"] = langsmith_endpoint

    # Determine status
    if tracing_enabled and has_api_key:
        project_name = langsmith_project or langchain_project or "default"
        return CheckResult(
            name="langsmith",
            status=CheckStatus.OK,
            message=f"LangSmith tracing enabled (project: {project_name})",
            details=details,
        )
    if tracing_enabled and not has_api_key:
        return CheckResult(
            name="langsmith",
            status=CheckStatus.ERROR,
            message="LangSmith tracing enabled but API key missing",
            details={
                **details,
                "remediation": "Set LANGSMITH_API_KEY or LANGCHAIN_API_KEY in .env file",
            },
        )
    if not tracing_enabled and has_api_key:
        return CheckResult(
            name="langsmith",
            status=CheckStatus.INFO,
            message="LangSmith API key present but tracing disabled",
            details={
                **details,
                "remediation": "Set LANGSMITH_TRACING=true to enable tracing",
            },
        )
    return CheckResult(
        name="langsmith",
        status=CheckStatus.INFO,
        message="LangSmith tracing not configured (optional)",
        details={
            **details,
            "remediation": "Add LANGSMITH_TRACING=true and LANGSMITH_API_KEY to .env to enable tracing",
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
                "remediation": "Create .env file from config/env.example for easier configuration",
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


async def check_observability(config: SootheConfig | None = None) -> CategoryResult:  # noqa: ARG001
    """Check observability and tracing configuration.

    Validates LangSmith integration, environment variable setup,
    and observability tooling configuration.

    Args:
        config: SootheConfig instance (not used for observability checks)

    Returns:
        CategoryResult with observability check results
    """
    checks = [
        _check_langsmith_config(),
        _check_dotenv_availability(),
    ]

    overall_status = aggregate_status([check.status for check in checks])

    return CategoryResult(
        category="observability",
        status=overall_status,
        checks=checks,
    )

"""Configuration health check implementation."""

from pathlib import Path

from soothe.config import SOOTHE_HOME, SootheConfig
from soothe.daemon.health.formatters import aggregate_status
from soothe.daemon.health.models import CategoryResult, CheckResult, CheckStatus


def _check_config_file(config: SootheConfig | None) -> CheckResult:
    """Check if config file exists and is valid."""
    if config is None:
        return CheckResult(
            name="config_file_valid",
            status=CheckStatus.WARNING,
            message="No configuration loaded (optional for basic usage)",
            details={
                "impact": "Cannot run config-driven checks",
                "remediation": "Run 'soothe config init'",
            },
        )

    # Config is already loaded and validated by Pydantic
    return CheckResult(
        name="config_file_valid",
        status=CheckStatus.OK,
        message="Configuration file is valid",
    )


def _check_env_vars_resolved(config: SootheConfig | None) -> CheckResult:
    """Check if environment variables are resolved."""
    if config is None:
        return CheckResult(
            name="env_vars_resolved",
            status=CheckStatus.SKIPPED,
            message="Skipped (no config loaded)",
        )

    # Check for unresolved ${VAR} patterns in config
    # This is a basic check - the actual resolution happens in config loader
    unresolved = [
        f"{provider.name}.api_key"
        for provider in config.providers
        if provider.api_key and "${" in provider.api_key
    ]

    if unresolved:
        return CheckResult(
            name="env_vars_resolved",
            status=CheckStatus.WARNING,
            message=f"Unresolved environment variables in: {', '.join(unresolved)}",
            details={
                "fields": unresolved,
                "remediation": "Set the required environment variables or update config",
            },
        )

    return CheckResult(
        name="env_vars_resolved",
        status=CheckStatus.OK,
        message="All environment variables resolved",
    )


def _check_default_model(config: SootheConfig | None) -> CheckResult:
    """Check if default model is configured."""
    if config is None:
        return CheckResult(
            name="default_model_configured",
            status=CheckStatus.SKIPPED,
            message="Skipped (no config loaded)",
        )

    try:
        # Try to resolve the default model
        default_model = config.router.default
        provider_name, model_name = (
            default_model.split(":", 1) if ":" in default_model else (default_model, "default")
        )

        # Verify provider exists
        provider_names = [p.name for p in config.providers]
        if provider_name not in provider_names:
            return CheckResult(
                name="default_model_configured",
                status=CheckStatus.ERROR,
                message=f"Default model provider '{provider_name}' not configured",
                details={
                    "default": default_model,
                    "available_providers": provider_names,
                    "remediation": f"Add provider '{provider_name}' to config or change router.default",
                },
            )

        return CheckResult(
            name="default_model_configured",
            status=CheckStatus.OK,
            message=f"Default model: {provider_name}/{model_name}",
            details={"provider": provider_name, "model": model_name},
        )

    except Exception as e:
        return CheckResult(
            name="default_model_configured",
            status=CheckStatus.ERROR,
            message=f"Failed to resolve default model: {e}",
        )


def _check_soothe_home() -> CheckResult:
    """Check SOOTHE_HOME directory exists and has correct permissions."""
    home = Path(SOOTHE_HOME).expanduser()

    if not home.exists():
        return CheckResult(
            name="soothe_home_exists",
            status=CheckStatus.ERROR,
            message=f"SOOTHE_HOME directory not found: {home}",
            details={
                "path": str(home),
                "remediation": "Run 'soothe config init' to create directory",
            },
        )

    # Check if we can write to it
    if not home.is_dir():
        return CheckResult(
            name="soothe_home_exists",
            status=CheckStatus.ERROR,
            message=f"SOOTHE_HOME is not a directory: {home}",
            details={"path": str(home)},
        )

    # Check write permissions
    test_file = home / ".health_check_test"
    try:
        test_file.touch()
        test_file.unlink()
    except PermissionError:
        return CheckResult(
            name="soothe_home_exists",
            status=CheckStatus.ERROR,
            message=f"SOOTHE_HOME not writable: {home}",
            details={"path": str(home), "remediation": "Fix directory permissions"},
        )

    # Check required subdirectories
    required_subdirs = ["config", "runs", "logs", "data"]
    missing = [subdir for subdir in required_subdirs if not (home / subdir).exists()]

    if missing:
        return CheckResult(
            name="soothe_home_exists",
            status=CheckStatus.WARNING,
            message=f"SOOTHE_HOME exists but missing subdirectories: {', '.join(missing)}",
            details={
                "path": str(home),
                "missing": missing,
                "remediation": "Run 'soothe config init'",
            },
        )

    return CheckResult(
        name="soothe_home_exists",
        status=CheckStatus.OK,
        message=f"SOOTHE_HOME directory ready: {home}",
        details={"path": str(home)},
    )


async def check_config(config: SootheConfig | None = None) -> CategoryResult:
    """Check configuration format and values.

    Args:
        config: SootheConfig instance to check

    Returns:
        CategoryResult with config check results
    """
    checks = [
        _check_config_file(config),
        _check_env_vars_resolved(config),
        _check_default_model(config),
        _check_soothe_home(),
    ]

    overall_status = aggregate_status([check.status for check in checks])

    return CategoryResult(
        category="configuration",
        status=overall_status,
        checks=checks,
    )

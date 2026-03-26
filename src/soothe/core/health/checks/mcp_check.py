"""MCP server health check implementation."""

from soothe.config import SootheConfig
from soothe.core.health.formatters import aggregate_status
from soothe.core.health.models import CategoryResult, CheckResult, CheckStatus


def _check_mcp_configs(config: SootheConfig | None) -> CheckResult:
    """Check MCP server configurations."""
    if config is None:
        return CheckResult(
            name="mcp_configs",
            status=CheckStatus.SKIPPED,
            message="Skipped (no config loaded)",
        )

    if not hasattr(config, "mcp_servers") or not config.mcp_servers:
        return CheckResult(
            name="mcp_configs",
            status=CheckStatus.INFO,
            message="No MCP servers configured",
        )

    # Check each MCP server config
    invalid = []
    for server in config.mcp_servers:
        if not server.name:
            invalid.append("server missing name")
        if not server.command:
            invalid.append(f"'{server.name}' missing command")

    if invalid:
        return CheckResult(
            name="mcp_configs",
            status=CheckStatus.ERROR,
            message=f"Invalid MCP server configs: {', '.join(invalid)}",
            details={"remediation": "Fix MCP server configuration in config file"},
        )

    return CheckResult(
        name="mcp_configs",
        status=CheckStatus.OK,
        message=f"{len(config.mcp_servers)} MCP server(s) configured",
        details={"servers": [s.name for s in config.mcp_servers]},
    )


def _check_mcp_availability(config: SootheConfig | None) -> CheckResult:
    """Check if MCP server executables are available."""
    if config is None:
        return CheckResult(
            name="mcp_availability",
            status=CheckStatus.SKIPPED,
            message="Skipped (no config loaded)",
        )

    if not hasattr(config, "mcp_servers") or not config.mcp_servers:
        return CheckResult(
            name="mcp_availability",
            status=CheckStatus.INFO,
            message="No MCP servers to check",
        )

    # Check if each server's command exists
    from shutil import which

    missing = []
    available = []

    for server in config.mcp_servers:
        cmd = server.command.split()[0] if server.command else None
        if cmd:
            if which(cmd):
                available.append(server.name)
            else:
                missing.append(f"{server.name} ({cmd})")

    if missing:
        return CheckResult(
            name="mcp_availability",
            status=CheckStatus.WARNING,
            message=f"MCP servers not found: {', '.join(missing)}",
            details={
                "missing": missing,
                "remediation": "Install missing MCP servers or update config",
            },
        )

    return CheckResult(
        name="mcp_availability",
        status=CheckStatus.OK,
        message=f"All {len(available)} MCP server command(s) found",
        details={"available": available},
    )


async def check_mcp_servers(config: SootheConfig | None = None) -> CategoryResult:
    """Check MCP servers.

    Args:
        config: SootheConfig instance

    Returns:
        CategoryResult with MCP server check results
    """
    checks = [
        _check_mcp_configs(config),
        _check_mcp_availability(config),
    ]

    overall_status = aggregate_status([check.status for check in checks])

    return CategoryResult(
        category="mcp_servers",
        status=overall_status,
        checks=checks,
    )

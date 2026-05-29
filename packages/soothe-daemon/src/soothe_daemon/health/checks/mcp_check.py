"""MCP server health check implementation (RFC-412)."""

from shutil import which

from soothe.config import SootheConfig
from soothe.config.models import MCPTransport

from soothe_daemon.health.formatters import aggregate_status
from soothe_daemon.health.models import CategoryResult, CheckResult, CheckStatus


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
        # name is required in RFC-412
        if not server.name:
            invalid.append("server missing name")
            continue
        # Validate transport-specific requirements
        if server.transport == MCPTransport.STDIO:
            if not server.command:
                invalid.append(f"'{server.name}' missing command for stdio transport")
        elif server.transport in (
            MCPTransport.SSE,
            MCPTransport.STREAMABLE_HTTP,
            MCPTransport.WEBSOCKET,
        ):
            if not server.url:
                invalid.append(
                    f"'{server.name}' missing url for {server.transport.value} transport"
                )

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
    """Check if MCP server executables/URLs are available."""
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

    # Check stdio server commands exist; remote servers marked as "remote"
    missing = []
    available = []
    remote = []

    for server in config.mcp_servers:
        if server.transport == MCPTransport.STDIO:
            cmd = server.command.split()[0] if server.command else None
            if cmd:
                if which(cmd):
                    available.append(server.name)
                else:
                    missing.append(f"{server.name} ({cmd})")
        else:
            # Remote transports: connectivity checked at runtime
            remote.append(server.name)

    if missing:
        return CheckResult(
            name="mcp_availability",
            status=CheckStatus.WARNING,
            message=f"MCP servers not found: {', '.join(missing)}",
            details={
                "missing": missing,
                "available": available,
                "remote": remote,
                "remediation": "Install missing MCP servers or update config",
            },
        )

    details = {"available": available, "remote": remote}
    msg_parts = []
    if available:
        msg_parts.append(f"{len(available)} stdio command(s) found")
    if remote:
        msg_parts.append(f"{len(remote)} remote server(s)")

    return CheckResult(
        name="mcp_availability",
        status=CheckStatus.OK,
        message="All MCP servers: " + ", ".join(msg_parts) if msg_parts else "No servers",
        details=details,
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

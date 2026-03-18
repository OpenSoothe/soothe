"""Status commands for Soothe CLI."""

import logging
import sys
from typing import Annotated

import typer

from soothe.cli.core import load_config
from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


def list_subagents(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file (YAML or JSON)."),
    ] = None,
) -> None:
    """List available subagents and their enabled/disabled status."""
    try:
        cfg = load_config(config)

        from rich.table import Table

        from soothe.cli.commands.subagent_names import BUILTIN_SUBAGENT_NAMES, SUBAGENT_DISPLAY_NAMES

        table = Table(title="Available Subagents")
        table.add_column("Name", style="cyan")
        table.add_column("Technical ID", style="yellow")
        table.add_column("Status", justify="center")

        for subagent_id in BUILTIN_SUBAGENT_NAMES:
            display_name = SUBAGENT_DISPLAY_NAMES[subagent_id]
            enabled = True
            if subagent_id in cfg.subagents:
                enabled = cfg.subagents[subagent_id].enabled
            status = "[green]✓ enabled[/green]" if enabled else "[red]✗ disabled[/red]"
            table.add_row(display_name, subagent_id, status)

        typer.echo(table)

        # Also show custom subagents if any
        custom_subagents = set(cfg.subagents.keys()) - set(BUILTIN_SUBAGENT_NAMES)
        if custom_subagents:
            typer.echo("\nCustom subagents:")
            for subagent_id in sorted(custom_subagents):
                enabled = cfg.subagents[subagent_id].enabled
                status = "enabled" if enabled else "disabled"
                typer.echo(f"  - {subagent_id}: {status}")

    except KeyboardInterrupt:
        typer.echo("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        logger.exception("Config generation error")
        from soothe.utils.error_format import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        sys.exit(1)


def list_subagents_status() -> None:
    """List all available subagents and their status."""
    try:
        cfg = SootheConfig()
        from soothe.core.resolver import SUBAGENT_FACTORIES as _SUBAGENT_FACTORIES

        typer.echo("\nAvailable Subagents:")
        typer.echo("-" * 50)
        for name, sub_cfg in cfg.subagents.items():
            status = "enabled" if sub_cfg.enabled else "disabled"
            model = sub_cfg.model or cfg.resolve_model("default")
            typer.echo(f"  {name}: {status}")
            typer.echo(f"    Model: {model}")
        typer.echo("-" * 50)
        typer.echo(f"\nTotal configured: {len([s for s in cfg.subagents.values() if s.enabled])} active")
        typer.echo(f"Total available: {len(_SUBAGENT_FACTORIES)}")
    except Exception as e:
        logger.exception("Subagents list error")
        from soothe.utils.error_format import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        sys.exit(1)


def show_config(
    *,
    show_sensitive: Annotated[
        bool,
        typer.Option("--show-sensitive", "-s", help="Show sensitive values like API keys."),
    ] = False,
) -> None:
    """Display current configuration."""
    try:
        cfg = SootheConfig()

        typer.echo("\nSoothe Configuration:")
        typer.echo("=" * 50)

        typer.echo("\n[Model Router]")
        typer.echo(f"  default: {cfg.router.default}")
        for role in ("think", "fast", "image", "embedding"):
            value = getattr(cfg.router, role, None)
            if value:
                typer.echo(f"  {role}: {value}")

        typer.echo("\n[Providers]")
        if cfg.providers:
            for p in cfg.providers:
                key_display = "[REDACTED]" if p.api_key and not show_sensitive else (p.api_key or "(not set)")
                typer.echo(
                    f"  {p.name}: type={p.provider_type}, url={p.api_base_url or '(default)'}, key={key_display}"
                )
        else:
            typer.echo("  (none)")

        typer.echo(f"  debug: {cfg.debug}")

        typer.echo("\n[Tools]")
        if cfg.tools:
            for tool in cfg.tools:
                typer.echo(f"  - {tool}")
        else:
            typer.echo("  (none)")

        typer.echo("\n[Subagents]")
        for name, sub_cfg in cfg.subagents.items():
            status = "enabled" if sub_cfg.enabled else "disabled"
            typer.echo(f"  {name}: {status}")

        typer.echo("\n[MCP Servers]")
        if cfg.mcp_servers:
            for i, server in enumerate(cfg.mcp_servers, 1):
                if server.command:
                    typer.echo(f"  {i}. {server.command} {' '.join(server.args)}")
                elif server.url:
                    typer.echo(f"  {i}. HTTP: {server.url}")
        else:
            typer.echo("  (none)")

        typer.echo("\n[Protocols]")
        typer.echo(f"  context_backend: {cfg.protocols.context.backend}")
        typer.echo(f"  memory_backend: {cfg.protocols.memory.backend}")
        typer.echo(f"  planner_routing: {cfg.protocols.planner.routing}")

        typer.echo("\n[Vector Stores]")
        if cfg.vector_stores:
            for vs in cfg.vector_stores:
                typer.echo(f"  - {vs.name} ({vs.provider_type})")
        else:
            typer.echo("  (none)")

        if cfg.vector_store_router.default:
            typer.echo(f"\n  Router default: {cfg.vector_store_router.default}")
        if cfg.vector_store_router.context:
            typer.echo(f"  Router context: {cfg.vector_store_router.context}")
        if cfg.vector_store_router.skillify:
            typer.echo(f"  Router skillify: {cfg.vector_store_router.skillify}")
        if cfg.vector_store_router.weaver_reuse:
            typer.echo(f"  Router weaver_reuse: {cfg.vector_store_router.weaver_reuse}")

        typer.echo("\n" + "=" * 50)

    except Exception as e:
        logger.exception("Show config error")
        from soothe.utils.error_format import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        sys.exit(1)

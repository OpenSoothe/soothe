"""Status commands for Soothe CLI."""

import logging
import sys
from typing import Annotated

import typer

from soothe.cli.core import load_config

logger = logging.getLogger(__name__)


def agent_list(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    enabled: Annotated[
        bool,
        typer.Option("--enabled", help="Show only enabled agents."),
    ] = False,
    disabled: Annotated[
        bool,
        typer.Option("--disabled", help="Show only disabled agents."),
    ] = False,
) -> None:
    """List available agents and their status.

    Examples:
        soothe agent list
        soothe agent list --enabled
        soothe agent list --disabled
    """
    try:
        cfg = load_config(config)

        from rich.table import Table

        from soothe.cli.commands.subagent_names import BUILTIN_SUBAGENT_NAMES, SUBAGENT_DISPLAY_NAMES

        table = Table(title="Available Agents")
        table.add_column("Name", style="cyan")
        table.add_column("Technical ID", style="yellow")
        table.add_column("Status", justify="center")

        for subagent_id in BUILTIN_SUBAGENT_NAMES:
            is_enabled = True
            if subagent_id in cfg.subagents:
                is_enabled = cfg.subagents[subagent_id].enabled

            # Filter by status
            if enabled and not is_enabled:
                continue
            if disabled and is_enabled:
                continue

            display_name = SUBAGENT_DISPLAY_NAMES[subagent_id]
            status = "[green]✓ enabled[/green]" if is_enabled else "[red]✗ disabled[/red]"
            table.add_row(display_name, subagent_id, status)

        typer.echo(table)

        # Also show custom subagents if any
        custom_subagents = set(cfg.subagents.keys()) - set(BUILTIN_SUBAGENT_NAMES)
        if custom_subagents:
            typer.echo("\nCustom agents:")
            for subagent_id in sorted(custom_subagents):
                is_enabled = cfg.subagents[subagent_id].enabled
                status = "enabled" if is_enabled else "disabled"
                typer.echo(f"  - {subagent_id}: {status}")

    except KeyboardInterrupt:
        typer.echo("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        logger.exception("Agent list error")
        from soothe.utils.error_format import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        sys.exit(1)


def agent_status(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Show detailed agent status.

    Examples:
        soothe agent status
    """
    try:
        cfg = load_config(config)
        from soothe.core.resolver import SUBAGENT_FACTORIES as _SUBAGENT_FACTORIES

        typer.echo("\nAgent Status:")
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
        logger.exception("Agent status error")
        from soothe.utils.error_format import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        sys.exit(1)

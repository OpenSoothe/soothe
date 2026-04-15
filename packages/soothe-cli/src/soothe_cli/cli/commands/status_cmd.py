"""Status commands for Soothe CLI."""

import logging
import sys
from typing import Annotated

import typer

logger = logging.getLogger(__name__)


def agent_list(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    enabled: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--enabled", help="Show only enabled agents."),
    ] = False,
    disabled: Annotated[  # noqa: FBT002
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
    from soothe_cli.shared import load_config

    try:
        cfg = load_config(config)

        from rich.console import Console
        from rich.table import Table

        from soothe_cli.cli.commands.subagent_names import (
            BUILTIN_SUBAGENT_NAMES,
            SUBAGENT_DISPLAY_NAMES,
        )

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

        console = Console()
        console.print(table)

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
        from soothe_sdk import format_cli_error

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
    from soothe_cli.shared import load_config

    try:
        cfg = load_config(config)

        typer.echo("\nAgent Status:")
        typer.echo("-" * 50)
        for name, sub_cfg in cfg.subagents.items():
            status = "enabled" if sub_cfg.enabled else "disabled"
            model = sub_cfg.model or cfg.resolve_model("default")
            typer.echo(f"  {name}: {status}")
            typer.echo(f"    Model: {model}")
        typer.echo("-" * 50)
        enabled_count = len([s for s in cfg.subagents.values() if s.enabled])
        total_count = len(cfg.subagents)
        typer.echo(f"\nTotal: {enabled_count}/{total_count} agents enabled")
    except Exception as e:
        logger.exception("Agent status error")
        from soothe_sdk import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        sys.exit(1)

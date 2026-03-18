"""Config command for Soothe CLI."""

import json
import logging
import sys
from typing import Annotated

import typer

from soothe.cli.core import load_config

logger = logging.getLogger(__name__)


def config(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file (YAML or JSON)."),
    ] = None,
    format_output: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: json or summary."),
    ] = "summary",
) -> None:
    """Display current configuration."""
    try:
        cfg = load_config(config)

        if format_output == "json":
            # Output full config as JSON
            config_dict = cfg.model_dump(mode="python", exclude_unset=True)
            typer.echo(json.dumps(config_dict, indent=2, default=str))
        else:
            # Summary output
            from rich.panel import Panel
            from rich.table import Table

            # Providers summary
            providers_table = Table(title="Model Providers")
            providers_table.add_column("Name", style="cyan")
            providers_table.add_column("Models", style="yellow")
            providers_table.add_column("Default", justify="center")

            for provider in cfg.providers:
                model_count = len(provider.models)
                providers_table.add_row(
                    provider.name,
                    f"{model_count} models",
                    "✓" if cfg.router.default.startswith(f"{provider.name}:") else "",
                )

            if not cfg.providers:
                providers_table.add_row("None configured", "", "")

            # Subagents summary
            from soothe.cli.commands.subagent_names import BUILTIN_SUBAGENT_NAMES, SUBAGENT_DISPLAY_NAMES

            subagents_table = Table(title="Subagents")
            subagents_table.add_column("Name", style="cyan")
            subagents_table.add_column("Status", justify="center")

            for subagent_id in BUILTIN_SUBAGENT_NAMES:
                display_name = SUBAGENT_DISPLAY_NAMES.get(subagent_id, subagent_id.replace("_", " ").title())
                enabled = True
                if subagent_id in cfg.subagents:
                    enabled = cfg.subagents[subagent_id].enabled
                status = "[green]Enabled[/green]" if enabled else "[red]Disabled[/red]"
                subagents_table.add_row(display_name, status)

            # General info
            general_table = Table(title="General Configuration")
            general_table.add_column("Setting", style="cyan")
            general_table.add_column("Value", style="yellow")
            general_table.add_row("Debug Mode", "[green]Yes[/green]" if cfg.debug else "[red]No[/red]")
            general_table.add_row("Context Backend", cfg.protocols.context.backend.title())
            general_table.add_row("Memory Backend", cfg.protocols.memory.backend.title())
            general_table.add_row("Policy Profile", cfg.protocols.policy.profile)
            general_table.add_row("Progress Verbosity", cfg.logging.progress_verbosity)
            # Show vector store providers count
            vs_count = len(cfg.vector_stores)
            general_table.add_row("Vector Store Providers", f"{vs_count} configured")

            typer.echo(Panel(providers_table, border_style="blue"))
            typer.echo(Panel(subagents_table, border_style="blue"))
            typer.echo(Panel(general_table, border_style="blue"))

    except KeyboardInterrupt:
        typer.echo("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        logger.exception("Config command error")
        from soothe.utils.error_format import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        sys.exit(1)

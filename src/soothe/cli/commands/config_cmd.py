"""Config command for Soothe CLI."""

import json
import logging
import sys
from typing import Annotated

import typer

from soothe.cli.core import load_config

logger = logging.getLogger(__name__)


def config_show(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    format_output: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: json or summary."),
    ] = "summary",
    show_sensitive: Annotated[
        bool,
        typer.Option("--show-sensitive", "-s", help="Show sensitive values like API keys."),
    ] = False,
) -> None:
    """Display current configuration.

    Examples:
        soothe config show
        soothe config show --show-sensitive
        soothe config show --format json
    """
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

            subagents_table = Table(title="Agents")
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


def config_init(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing configuration."),
    ] = False,
) -> None:
    """Initialize ~/.soothe with a default configuration.

    Examples:
        soothe config init
        soothe config init --force  # Overwrite existing
    """
    import shutil
    from importlib.resources import as_file, files
    from pathlib import Path

    from soothe.config import SOOTHE_HOME

    home = Path(SOOTHE_HOME).expanduser()
    target = home / "config" / "config.yml"

    if target.exists() and not force:
        typer.echo(f"Config already exists at {target}. Use --force to overwrite.")
        return

    target.parent.mkdir(parents=True, exist_ok=True)

    # Try loading from installed package resources first
    template_found = False
    try:
        config_resource = files("soothe.config").joinpath("config.yml")
        with as_file(config_resource) as template_path:
            if template_path.exists():
                shutil.copy2(template_path, target)
                typer.echo(f"Created {target}")
                template_found = True
    except (FileNotFoundError, TypeError, AttributeError):
        pass

    # Fallback for development/editable installs
    if not template_found:
        template = Path(__file__).resolve().parent.parent.parent.parent / "config" / "config.yml"
        if template.exists():
            shutil.copy2(template, target)
            typer.echo(f"Created {target}")
            template_found = True

    # Create minimal config if template not found
    if not template_found:
        target.write_text("# Soothe configuration\n# See docs/user_guide.md for options\n")
        typer.echo(f"Created minimal {target}")

    for subdir in ("runs", "generated_agents", "logs"):
        (home / subdir).mkdir(parents=True, exist_ok=True)

    typer.echo(f"Soothe home initialized at {home}")


def config_validate(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Validate configuration file.

    Examples:
        soothe config validate
        soothe config validate --config custom.yml
    """
    try:
        load_config(config)
        typer.echo("✓ Configuration is valid.")
    except Exception as e:
        typer.echo(f"✗ Configuration error: {e}", err=True)
        sys.exit(1)

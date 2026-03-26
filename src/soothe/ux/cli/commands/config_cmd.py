"""Config command for Soothe CLI."""

import json
import logging
import sys
from typing import Annotated

import typer

from soothe.ux.core import load_config

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
    show_sensitive: Annotated[  # noqa: ARG001, FBT002
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
            # Note: show_sensitive parameter reserved for future use
            typer.echo(json.dumps(config_dict, indent=2, default=str))
        else:
            # Summary output
            from rich.console import Console
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
            from soothe.ux.cli.commands.subagent_names import BUILTIN_SUBAGENT_NAMES, SUBAGENT_DISPLAY_NAMES

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
            general_table.add_row("Memory Backend", cfg.protocols.memory.database_provider.title())
            general_table.add_row("Policy Profile", cfg.protocols.policy.profile)
            general_table.add_row("Progress Verbosity", cfg.logging.verbosity)
            # Show vector store providers count
            vs_count = len(cfg.vector_stores)
            general_table.add_row("Vector Store Providers", f"{vs_count} configured")

            console = Console()
            console.print(Panel(providers_table, border_style="blue"))
            console.print(Panel(subagents_table, border_style="blue"))
            console.print(Panel(general_table, border_style="blue"))

    except KeyboardInterrupt:
        typer.echo("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        logger.exception("Config command error")
        from soothe.utils.error_format import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        sys.exit(1)


def config_init(
    force: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--force", "-f", help="Overwrite existing configuration without confirmation."),
    ] = False,
) -> None:
    """Initialize ~/.soothe with a default configuration.

    Examples:
        soothe config init
        soothe config init --force  # Overwrite existing without confirmation
    """
    import shutil
    from importlib.resources import as_file, files
    from pathlib import Path

    from soothe.config import SOOTHE_HOME

    home = Path(SOOTHE_HOME).expanduser()
    target = home / "config" / "config.yml"

    # Check if config file exists and ask for confirmation
    if target.exists() and not force:
        typer.echo(f"Config file already exists at: {target}")
        overwrite = typer.confirm("Do you want to overwrite it?", default=False)
        if not overwrite:
            typer.echo("Cancelled.")
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
    """Validate configuration file and show basic info.

    Examples:
        soothe config validate
        soothe config validate --config custom.yml
    """
    from pathlib import Path

    from soothe.config import SOOTHE_HOME

    try:
        cfg = load_config(config)

        # Determine config file path
        if config:
            config_path = Path(config).expanduser().resolve()
        else:
            config_path = Path(SOOTHE_HOME).expanduser() / "config" / "config.yml"

        # Show basic information
        typer.echo(f"\nConfig file: {config_path}")
        typer.echo("Status: ✓ Valid\n")

        # Show default model provider info
        typer.echo("Default Model Configuration:")
        default_model = cfg.router.default
        provider_name, model_name = default_model.split(":", 1) if ":" in default_model else (default_model, "default")
        typer.echo(f"  Provider: {provider_name}")
        typer.echo(f"  Model: {model_name}")

        # Show available providers
        if cfg.providers:
            typer.echo(f"\nConfigured Providers: {len(cfg.providers)}")
            for provider in cfg.providers:
                model_count = len(provider.models)
                is_default = default_model.startswith(f"{provider.name}:")
                default_marker = " (default)" if is_default else ""
                typer.echo(f"  • {provider.name}: {model_count} models{default_marker}")
        else:
            typer.echo("\nNo custom providers configured (using defaults)")

        # Show enabled subagents count
        enabled_subagents = sum(1 for s in cfg.subagents.values() if s.enabled)
        typer.echo(f"\nSubagents: {enabled_subagents} enabled")

        typer.echo()  # Blank line at end

    except Exception as e:
        typer.echo(f"\n✗ Configuration error: {e}", err=True)
        sys.exit(1)

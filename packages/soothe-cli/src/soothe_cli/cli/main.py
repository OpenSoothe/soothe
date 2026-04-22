"""Main CLI entry point using Typer."""

# Load environment variables from .env file BEFORE any langchain imports
# This is required for LangSmith tracing to be activated at import time
from dotenv import load_dotenv

load_dotenv()

from importlib.metadata import version  # noqa: E402
from typing import Annotated  # noqa: E402

import typer  # noqa: E402

app = typer.Typer(
    name="soothe",
    help="Intelligent AI assistant for complex tasks",
    no_args_is_help=False,
    add_completion=False,
)


def add_help_alias(nested_app: typer.Typer) -> None:
    """Add -h as an alias for --help to a nested Typer app.

    This is a workaround for Typer not supporting -h for nested command groups.
    Must be called AFTER creating the nested app but BEFORE adding commands.

    Args:
        nested_app: The nested Typer app to add -h support to.
    """

    # Add a callback that defines -h option
    @nested_app.callback(invoke_without_command=True)
    def help_callback(
        ctx: typer.Context,
        show_help: Annotated[  # noqa: FBT002
            bool,
            typer.Option("-h", "--help", is_flag=True, help="Show this message and exit."),
        ] = False,
    ) -> None:
        # If -h/--help is passed, show help and exit before command parsing
        if show_help:
            typer.echo(ctx.get_help())
            raise typer.Exit(code=0)

        # If no subcommand and no help flag, show help by default
        if ctx.invoked_subcommand is None:
            typer.echo(ctx.get_help())
            raise typer.Exit(code=0)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config: Annotated[
        str | None,
        typer.Option(
            "--config",
            "-c",
            help="Ignored for client settings; edit ~/.soothe/config/cli_config.yml instead.",
        ),
    ] = None,
    prompt: Annotated[
        str | None,
        typer.Option(
            "--prompt", "-p", help="Prompt to send as user message (headless single-shot mode)."
        ),
    ] = None,
    no_tui: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--no-tui", help="Disable TUI; run single prompt and exit."),
    ] = False,
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format for headless mode: text or jsonl."),
    ] = "text",
    show_help: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--help", "-h", is_flag=True, help="Show this message and exit."),
    ] = False,
    show_version: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--version", is_flag=True, help="Show version and exit."),
    ] = False,
) -> None:
    """Soothe CLI - Intelligent AI assistant client.

    Run without arguments for interactive TUI mode, or provide a prompt via --prompt/-p option.

    Note: This is the CLI client. Use 'soothe-daemon' command to manage the daemon server.

    Examples:
        soothe                           # Interactive TUI mode
        soothe -p "Research AI advances" # Headless single-prompt mode
        soothe --config custom.yml       # Ignored for client settings; use ~/.soothe/config/cli_config.yml
        soothe thread list               # List conversation threads
    """
    # Handle -h/--help flag
    if show_help:
        typer.echo(ctx.get_help())
        raise typer.Exit

    # Handle --version flag
    if show_version:
        typer.echo(f"soothe {version('soothe-cli')}")
        raise typer.Exit

    # Only run default behavior if no subcommand is being invoked
    if ctx.invoked_subcommand is None:
        from soothe_cli.cli.commands.run_cmd import run_impl

        run_impl(
            prompt=prompt,
            config=config,
            thread_id=None,
            no_tui=no_tui,
            autonomous=False,
            max_iterations=None,
            output_format=output_format,
        )


# ---------------------------------------------------------------------------
# Thread Command (Nested Subcommands) - Read-Only Diagnostics
# ---------------------------------------------------------------------------
# NOTE: Thread commands are read-only diagnostics per RFC-503 (Loop-First UX).
# Users manage loops (primary entity), not threads (internal execution contexts).
# For thread lifecycle management, use loop commands: soothe loop <subcommand>

thread_app = typer.Typer(
    name="thread",
    help="Inspect conversation threads (read-only diagnostics)",
)
add_help_alias(thread_app)
app.add_typer(thread_app)


@thread_app.command("list")
def _thread_list(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    status: Annotated[
        str | None,
        typer.Option("--status", "-s", help="Filter by status (active, archived)."),
    ] = None,
) -> None:
    """List all agent threads (read-only diagnostics).

    Examples:
        soothe thread list
        soothe thread list --status active

    Note: For thread lifecycle management, use loop commands (RFC-503).
    """
    from soothe_cli.cli.commands.thread_cmd import thread_list

    thread_list(config=config, status=status)


@thread_app.command("show")
def _thread_show(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to show.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Show thread details (read-only diagnostics).

    Example:
        soothe thread show abc123

    Note: For thread lifecycle management, use loop commands (RFC-503).
    """
    from soothe_cli.cli.commands.thread_cmd import thread_show

    thread_show(thread_id=thread_id, config=config)


@thread_app.command("export")
def _thread_export(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to export.")],
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Output file path."),
    ] = None,
    export_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Export format: jsonl or md."),
    ] = "jsonl",
) -> None:
    """Export thread conversation to a file (read-only diagnostics).

    Example:
        soothe thread export abc123 --output out.jsonl

    Note: For thread lifecycle management, use loop commands (RFC-503).
    """
    from soothe_cli.cli.commands.thread_cmd import thread_export

    thread_export(thread_id=thread_id, output=output, export_format=export_format)


@thread_app.command("stats")
def _thread_stats(
    thread_id: Annotated[str, typer.Argument(help="Thread ID.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Show thread execution statistics (read-only diagnostics).

    Example:
        soothe thread stats abc123

    Note: For thread lifecycle management, use loop commands (RFC-503).
    """
    from soothe_cli.cli.commands.thread_cmd import thread_stats

    thread_stats(thread_id=thread_id, config=config)


@thread_app.command("artifacts")
def _thread_artifacts(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to list artifacts for.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """List artifacts for a thread (read-only diagnostics).

    Example:
        soothe thread artifacts abc123

    Note: For thread lifecycle management, use loop commands (RFC-503).
    """
    from soothe_cli.cli.commands.thread_cmd import thread_artifacts

    thread_artifacts(thread_id=thread_id, config=config)


# ---------------------------------------------------------------------------
# Loop Command (Nested Subcommands)
# ---------------------------------------------------------------------------

from soothe_cli.loop_commands import loop_app as _loop_app  # noqa: E402

add_help_alias(_loop_app)
app.add_typer(_loop_app, name="loop")


# ---------------------------------------------------------------------------
# Config Command (Nested Subcommands)
# ---------------------------------------------------------------------------

config_app = typer.Typer(name="config", help="Manage Soothe configuration")
add_help_alias(config_app)
app.add_typer(config_app)


@config_app.command("show")
def _config_show(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    format_output: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: json or summary."),
    ] = "summary",
    show_sensitive: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--show-sensitive", help="Show sensitive values like API keys."),
    ] = False,
) -> None:
    """Display current configuration.

    Examples:
        soothe config show
        soothe config show --show-sensitive
        soothe config show --format json
    """
    from soothe_cli.cli.commands.config_cmd import config_show

    config_show(config=config, format_output=format_output, show_sensitive=show_sensitive)


@config_app.command("init")
def _config_init(
    force: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--force", "-f", help="Overwrite existing configuration without confirmation."
        ),
    ] = False,
) -> None:
    """Initialize ~/.soothe with a default configuration.

    Examples:
        soothe config init
        soothe config init --force
    """
    from soothe_cli.cli.commands.config_cmd import config_init

    config_init(force=force)


@config_app.command("validate")
def _config_validate(
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
    from soothe_cli.cli.commands.config_cmd import config_validate

    config_validate(config=config)


# ---------------------------------------------------------------------------
# Agent Command (Nested Subcommands)
# ---------------------------------------------------------------------------

agent_app = typer.Typer(name="agent", help="List and manage agents")
add_help_alias(agent_app)
app.add_typer(agent_app)


@agent_app.command("list")
def _agent_list(
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
    from soothe_cli.cli.commands.status_cmd import agent_list

    agent_list(config=config, enabled=enabled, disabled=disabled)


@agent_app.command("status")
def _agent_status(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Show detailed agent status.

    Example:
        soothe agent status
    """
    from soothe_cli.cli.commands.status_cmd import agent_status

    agent_status(config=config)


# ---------------------------------------------------------------------------
# Autopilot Command (Nested Subcommands)
# ---------------------------------------------------------------------------

from soothe_cli.cli.commands.autopilot_cmd import app as _autopilot_app  # noqa: E402

add_help_alias(_autopilot_app)
app.add_typer(_autopilot_app, name="autopilot")


# ---------------------------------------------------------------------------
# Help Command
# ---------------------------------------------------------------------------


@app.command(name="help")
def help_command(ctx: typer.Context) -> None:
    """Show help message and exit."""
    # Get the parent context (the main app) to show full help
    parent_ctx = ctx.parent or ctx
    typer.echo(parent_ctx.get_help())


if __name__ == "__main__":
    app()

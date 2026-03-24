"""Main CLI entry point using Typer."""

from importlib.metadata import version
from typing import Annotated, Literal

import typer

app = typer.Typer(
    name="soothe",
    help="Intelligent AI assistant for complex tasks",
    no_args_is_help=False,
    add_completion=False,
)


def add_help_alias(app: typer.Typer) -> None:
    """Add -h as alias for --help to a Typer app."""

    @app.callback(invoke_without_command=True)
    def callback(
        ctx: typer.Context,
        show_help: Annotated[  # noqa: FBT002
            bool,
            typer.Option("-h", "--help", is_flag=True, help="Show this message and exit."),
        ] = False,
    ) -> None:
        if show_help:
            typer.echo(ctx.get_help())
            raise typer.Exit


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    no_tui: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--no-tui", help="Disable TUI; run single prompt and exit."),
    ] = False,
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format for headless mode: text or jsonl."),
    ] = "text",
    progress_verbosity: Annotated[
        Literal["minimal", "normal", "detailed", "debug"] | None,
        typer.Option(
            "--progress-verbosity",
            "-v",
            help="Progress visibility: minimal, normal, detailed, debug.",
        ),
    ] = None,
    show_help: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--help", "-h", is_flag=True, help="Show this message and exit."),
    ] = False,
    show_version: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--version", is_flag=True, help="Show version and exit."),
    ] = False,
) -> None:
    """Soothe - Intelligent AI assistant for complex tasks.

    Run without arguments for interactive TUI mode, or provide a prompt as the first argument.

    Examples:
        soothe                           # Interactive TUI mode
        soothe "Research AI advances"    # Headless single-prompt mode
        soothe --config custom.yml       # Use custom config
    """
    # Handle -h/--help flag
    if show_help:
        typer.echo(ctx.get_help())
        raise typer.Exit

    # Handle --version flag
    if show_version:
        typer.echo(f"soothe {version('soothe')}")
        raise typer.Exit

    # Only run default behavior if no subcommand is being invoked
    if ctx.invoked_subcommand is None:
        # Get prompt from remaining args
        prompt = " ".join(ctx.args) if ctx.args else None

        from soothe.ux.cli.commands.run_cmd import run_impl

        run_impl(
            prompt=prompt,
            config=config,
            thread_id=None,
            no_tui=no_tui,
            autonomous=False,
            max_iterations=None,
            output_format=output_format,
            progress_verbosity=progress_verbosity,
        )


# ---------------------------------------------------------------------------
# Thread Command (Flat)
# ---------------------------------------------------------------------------


@app.command()
def thread(
    ctx: typer.Context,
    thread_id: Annotated[
        str | None,
        typer.Argument(help="Thread ID to operate on."),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", help="Path to configuration file."),
    ] = None,
    # Action flags
    list_threads: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--list", "-l", help="List all threads."),
    ] = False,
    show_thread: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--show", "-s", help="Show thread details."),
    ] = False,
    continue_thread: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--continue", "-c", help="Continue thread in TUI."),
    ] = False,
    archive_thread: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--archive", "-a", help="Archive thread."),
    ] = False,
    delete_thread: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--delete", "-d", help="Delete thread."),
    ] = False,
    export_thread: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--export", "-e", help="Export thread."),
    ] = False,
    stats_thread: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--stats", help="Show thread statistics."),
    ] = False,
    tag_thread: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--tag", help="Add/remove tags from thread."),
    ] = False,
    # Additional options for specific actions
    status_filter: Annotated[
        str | None,
        typer.Option("--status", help="Filter by status (active, archived)."),
    ] = None,
    daemon: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--daemon", help="Attach to running daemon for continue."),
    ] = False,
    new: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--new", help="Create new thread for continue."),
    ] = False,
    yes: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation for delete."),
    ] = False,
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Output file path for export."),
    ] = None,
    export_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Export format: jsonl or md."),
    ] = "jsonl",
    tags: Annotated[
        list[str] | None,
        typer.Argument(help="Tags to add/remove (use with --tag)."),
    ] = None,
    remove: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--remove", help="Remove tags instead of adding."),
    ] = False,
    show_help: Annotated[  # noqa: FBT002
        bool,
        typer.Option("-h", "--help", is_flag=True, help="Show this message and exit."),
    ] = False,
) -> None:
    """Manage conversation threads.

    Default action (no flags): Show thread details if thread_id provided, else list threads.

    Examples:
        soothe thread                    # List all threads
        soothe thread -l                 # List all threads (explicit)
        soothe thread abc123             # Show thread details
        soothe thread -c abc123          # Continue thread in TUI
        soothe thread -c --daemon abc123 # Continue via daemon
        soothe thread -a abc123          # Archive thread
        soothe thread -d abc123          # Delete thread
        soothe thread -e abc123 -o out.json  # Export thread
        soothe thread --stats abc123     # Show thread stats
        soothe thread --tag abc123 research analysis  # Add tags
    """
    # Handle -h/--help flag
    if show_help:
        typer.echo(ctx.get_help())
        raise typer.Exit

    from soothe.ux.cli.commands.thread_cmd import (
        thread_archive,
        thread_continue,
        thread_delete,
        thread_export,
        thread_list,
        thread_show,
        thread_stats,
        thread_tag,
    )

    # Handle --list flag
    if list_threads:
        thread_list(config=config, status=status_filter)
        return

    # Handle --tag flag
    if tag_thread:
        if not thread_id:
            typer.echo("Error: Thread ID required for --tag", err=True)
            raise typer.Exit(1)
        thread_tag(thread_id=thread_id, tags=tags or [], config=config, remove=remove)
        return

    # Handle --stats flag
    if stats_thread:
        if not thread_id:
            typer.echo("Error: Thread ID required for --stats", err=True)
            raise typer.Exit(1)
        thread_stats(thread_id=thread_id, config=config)
        return

    # Handle --export flag
    if export_thread:
        if not thread_id:
            typer.echo("Error: Thread ID required for --export", err=True)
            raise typer.Exit(1)
        thread_export(thread_id=thread_id, output=output, export_format=export_format)
        return

    # Handle --delete flag
    if delete_thread:
        if not thread_id:
            typer.echo("Error: Thread ID required for --delete", err=True)
            raise typer.Exit(1)
        thread_delete(thread_id=thread_id, config=config, yes=yes)
        return

    # Handle --archive flag
    if archive_thread:
        if not thread_id:
            typer.echo("Error: Thread ID required for --archive", err=True)
            raise typer.Exit(1)
        thread_archive(thread_id=thread_id, config=config)
        return

    # Handle --continue flag
    if continue_thread:
        thread_continue(thread_id=thread_id, config=config, daemon=daemon, new=new)
        return

    # Handle --show flag or default with thread_id
    if show_thread or thread_id:
        if not thread_id:
            typer.echo("Error: Thread ID required for --show", err=True)
            raise typer.Exit(1)
        thread_show(thread_id=thread_id, config=config)
        return

    # Default: list threads
    thread_list(config=config, status=status_filter)


# ---------------------------------------------------------------------------
# Daemon Command (Nested Subcommands)
# ---------------------------------------------------------------------------

daemon_app = typer.Typer(name="daemon", help="Manage daemon process")
add_help_alias(daemon_app)
app.add_typer(daemon_app)


@daemon_app.command("start")
def _daemon_start(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    *,
    foreground: Annotated[
        bool,
        typer.Option("--foreground", help="Run in foreground (don't daemonize)."),
    ] = False,
) -> None:
    """Start the Soothe daemon."""
    from soothe.ux.cli.commands.daemon_cmd import daemon_start

    daemon_start(config=config, foreground=foreground)


@daemon_app.command("stop")
def _daemon_stop() -> None:
    """Stop the running Soothe daemon."""
    from soothe.ux.cli.commands.daemon_cmd import daemon_stop

    daemon_stop()


@daemon_app.command("status")
def _daemon_status() -> None:
    """Show Soothe daemon status."""
    from soothe.ux.cli.commands.daemon_cmd import daemon_status

    daemon_status()


@daemon_app.command("restart")
def _daemon_restart(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Restart the Soothe daemon."""
    from soothe.ux.cli.commands.daemon_cmd import daemon_restart

    daemon_restart(config=config)


# ---------------------------------------------------------------------------
# Config Command (Flat)
# ---------------------------------------------------------------------------


@app.command()
def config(
    ctx: typer.Context,
    config_path: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    # Action flags
    show: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--show", "-s", help="Show current configuration."),
    ] = False,
    init: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--init", "-i", help="Initialize default configuration."),
    ] = False,
    validate: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--validate", help="Validate configuration file."),
    ] = False,
    # Additional options
    force: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--force", help="Force overwrite (with --init)."),
    ] = False,
    format_output: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: json or summary (with --show)."),
    ] = "summary",
    show_sensitive: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--show-sensitive", help="Show sensitive values (with --show)."),
    ] = False,
    show_help: Annotated[  # noqa: FBT002
        bool,
        typer.Option("-h", "--help", is_flag=True, help="Show this message and exit."),
    ] = False,
) -> None:
    """Manage Soothe configuration.

    Default action (no flags): Show current configuration.

    Examples:
        soothe config              # Show configuration summary
        soothe config -i           # Initialize default config
        soothe config --validate   # Validate config
        soothe config -s --format json  # Show as JSON
    """
    # Handle -h/--help flag
    if show_help:
        typer.echo(ctx.get_help())
        raise typer.Exit

    from soothe.ux.cli.commands.config_cmd import config_init, config_show, config_validate

    # Handle --init flag
    if init:
        config_init(force=force)
        return

    # Handle --validate flag
    if validate:
        config_validate(config=config_path)
        return

    # Handle --show flag or default
    config_show(config=config_path, format_output=format_output, show_sensitive=show_sensitive)


# ---------------------------------------------------------------------------
# Agent Command (Flat)
# ---------------------------------------------------------------------------


@app.command()
def agent(
    ctx: typer.Context,
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    # Action flags
    list_agents: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--list", "-l", help="List available agents."),
    ] = False,
    status: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--status", help="Show detailed agent status."),
    ] = False,
    # Additional options
    enabled: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--enabled", help="Show only enabled agents (with --list)."),
    ] = False,
    disabled: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--disabled", help="Show only disabled agents (with --list)."),
    ] = False,
    show_help: Annotated[  # noqa: FBT002
        bool,
        typer.Option("-h", "--help", is_flag=True, help="Show this message and exit."),
    ] = False,
) -> None:
    """List and manage agents.

    Default action (no flags): List available agents.

    Examples:
        soothe agent           # List all agents
        soothe agent -l        # List all agents (explicit)
        soothe agent --status  # Show detailed status
        soothe agent -l --enabled  # List only enabled agents
    """
    # Handle -h/--help flag
    if show_help:
        typer.echo(ctx.get_help())
        raise typer.Exit

    from soothe.ux.cli.commands.status_cmd import agent_list, agent_status

    # Handle --status flag
    if status:
        agent_status(config=config)
        return

    # Handle --list flag or default
    agent_list(config=config, enabled=enabled, disabled=disabled)


# ---------------------------------------------------------------------------
# Autopilot Command
# ---------------------------------------------------------------------------


@app.command()
def autopilot(
    ctx: typer.Context,
    prompt: Annotated[
        str | None,
        typer.Argument(help="Task for autonomous execution."),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    max_iterations: Annotated[
        int | None,
        typer.Option("--max-iterations", help="Maximum autonomous iterations."),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: text or jsonl."),
    ] = "text",
    show_help: Annotated[  # noqa: FBT002
        bool,
        typer.Option("-h", "--help", is_flag=True, help="Show this message and exit."),
    ] = False,
) -> None:
    """Run autonomous agent loop for complex tasks.

    Autopilot mode executes tasks autonomously without requiring user interaction.
    The agent will plan, execute, and iterate on the task until completion or
    reaching the maximum iteration limit.

    This mode is ideal for:
    - Long-running tasks that don't need user input
    - Background execution of complex workflows
    - Batch processing or research tasks
    - Automated testing and validation

    The agent operates in headless mode (no TUI) and outputs progress to stdout.
    Use --format jsonl for machine-readable output suitable for logging or piping.

    Examples:
        # Basic autonomous execution
        soothe autopilot "Research AI safety and summarize findings"

        # Limit iterations for complex tasks
        soothe autopilot "Build a web scraper" --max-iterations 10

        # Use custom config with JSON output
        soothe autopilot "Analyze codebase" -c config.yml --format jsonl

        # Long-running research task
        soothe autopilot "Investigate performance bottlenecks" --max-iterations 20
    """
    # Handle -h/--help flag
    if show_help:
        typer.echo(ctx.get_help())
        raise typer.Exit

    # Validate prompt is provided when not showing help
    if prompt is None:
        typer.echo("Error: Missing argument 'PROMPT'.", err=True)
        typer.echo(f"Try '{ctx.info_name} --help' for help.")
        raise typer.Exit(1)

    from soothe.ux.cli.commands.autopilot_cmd import autopilot as _autopilot

    _autopilot(
        prompt=prompt,
        config=config,
        max_iterations=max_iterations,
        output_format=output_format,
    )


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

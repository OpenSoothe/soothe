"""Daemon CLI entry point - manage Soothe daemon server."""

from typing import Annotated

import typer

app = typer.Typer(
    name="soothe-daemon",
    help="Soothe daemon server - agent runtime with WebSocket/HTTP transport",
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Soothe daemon server - agent runtime with WebSocket/HTTP transport."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command("start")
def daemon_start(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to daemon configuration file."),
    ] = None,
    foreground: Annotated[
        bool,
        typer.Option("--foreground", help="Run in foreground (don't daemonize)."),
    ] = False,
) -> None:
    """Start the Soothe daemon server."""
    # TODO: Import from soothe_daemon.daemon.commands.daemon_cmd
    typer.echo("Starting daemon... (placeholder)")


@app.command("stop")
def daemon_stop() -> None:
    """Stop the running Soothe daemon."""
    typer.echo("Stopping daemon... (placeholder)")


@app.command("status")
def daemon_status() -> None:
    """Show Soothe daemon status."""
    typer.echo("Daemon status: (placeholder)")


@app.command("restart")
def daemon_restart(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to daemon configuration file."),
    ] = None,
) -> None:
    """Restart the Soothe daemon."""
    typer.echo("Restarting daemon... (placeholder)")


@app.command("doctor")
def doctor() -> None:
    """Run comprehensive health checks."""
    typer.echo("Running health checks... (placeholder)")


@app.command("help")
def help_command(ctx: typer.Context) -> None:
    """Show help message and exit."""
    typer.echo(ctx.get_help())


if __name__ == "__main__":
    app()

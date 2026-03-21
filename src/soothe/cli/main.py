"""Main CLI entry point using Typer."""

from typing import Annotated, Literal

import typer

from soothe.cli.commands.autopilot_cmd import autopilot
from soothe.cli.commands.config_cmd import config_init, config_show, config_validate
from soothe.cli.commands.server_cmd import server_attach, server_start, server_status, server_stop
from soothe.cli.commands.status_cmd import agent_list, agent_status
from soothe.cli.commands.thread_cmd import (
    thread_archive,
    thread_continue,
    thread_delete,
    thread_export,
    thread_list,
    thread_show,
)

app = typer.Typer(
    name="soothe",
    help="Intelligent AI assistant for complex tasks",
    add_completion=False,
)

# ---------------------------------------------------------------------------
# Default Command
# ---------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    prompt: Annotated[
        str | None,
        typer.Argument(help="Prompt to send to the agent. Omit for interactive TUI."),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    no_tui: Annotated[
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
            help="Progress visibility: minimal, normal, detailed, debug.",
        ),
    ] = None,
) -> None:
    """Soothe - Intelligent AI assistant for complex tasks.

    Examples:
        soothe                           # Interactive TUI mode
        soothe "Research AI advances"    # Headless single-prompt mode
        soothe --config custom.yml       # Use custom config
    """
    if ctx.invoked_subcommand is None:
        from soothe.cli.commands.run_cmd import run_impl

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
# Configuration Commands
# ---------------------------------------------------------------------------

config_app = typer.Typer(name="config", help="Manage configuration")
app.add_typer(config_app)

config_app.command("show")(config_show)
config_app.command("init")(config_init)
config_app.command("validate")(config_validate)

# ---------------------------------------------------------------------------
# Thread Commands
# ---------------------------------------------------------------------------

thread_app = typer.Typer(name="thread", help="Manage conversation threads")
app.add_typer(thread_app)

thread_app.command("list")(thread_list)
thread_app.command("show")(thread_show)
thread_app.command("continue")(thread_continue)
thread_app.command("archive")(thread_archive)
thread_app.command("delete")(thread_delete)
thread_app.command("export")(thread_export)

# ---------------------------------------------------------------------------
# Server Commands
# ---------------------------------------------------------------------------

server_app = typer.Typer(name="server", help="Manage daemon process")
app.add_typer(server_app)

server_app.command("start")(server_start)
server_app.command("stop")(server_stop)
server_app.command("status")(server_status)
server_app.command("attach")(server_attach)

# ---------------------------------------------------------------------------
# Agent Commands
# ---------------------------------------------------------------------------

agent_app = typer.Typer(name="agent", help="List and manage agents")
app.add_typer(agent_app)

agent_app.command("list")(agent_list)
agent_app.command("status")(agent_status)

# ---------------------------------------------------------------------------
# Autopilot Command
# ---------------------------------------------------------------------------

app.command()(autopilot)


if __name__ == "__main__":
    app()

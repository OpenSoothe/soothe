"""Main CLI entry point using Typer."""

import typer

from soothe.cli.commands.attach_cmd import attach
from soothe.cli.commands.config_cmd import config
from soothe.cli.commands.init_cmd import init_soothe
from soothe.cli.commands.run_cmd import run
from soothe.cli.commands.server_cmd import server_start, server_status, server_stop
from soothe.cli.commands.status_cmd import (
    list_subagents,
    list_subagents_status,
    show_config,
)
from soothe.cli.commands.thread_cmd import (
    thread_archive,
    thread_delete,
    thread_export,
    thread_inspect,
    thread_list,
    thread_resume,
)

app = typer.Typer(
    name="soothe",
    help="Multi-agent harness built on deepagents and langchain/langgraph.",
    add_completion=False,
)

# ---------------------------------------------------------------------------
# Command Registration
# ---------------------------------------------------------------------------

app.command()(run)
app.command()(config)
app.command()(attach)
app.command("init")(init_soothe)
app.command()(list_subagents)
app.command()(list_subagents_status)
app.command("config")(show_config)

# ---------------------------------------------------------------------------
# Server Commands
# ---------------------------------------------------------------------------

server_app = typer.Typer(name="server", help="Manage the Soothe daemon process.")
app.add_typer(server_app)

server_app.command("start")(server_start)
server_app.command("stop")(server_stop)
server_app.command("status")(server_status)

# ---------------------------------------------------------------------------
# Thread Commands
# ---------------------------------------------------------------------------

thread_app = typer.Typer(name="thread", help="Thread lifecycle management.")
app.add_typer(thread_app)

thread_app.command("list")(thread_list)
thread_app.command("resume")(thread_resume)
thread_app.command("archive")(thread_archive)
thread_app.command("inspect")(thread_inspect)
thread_app.command("delete")(thread_delete)
thread_app.command("export")(thread_export)


if __name__ == "__main__":
    app()

# Implementation Guide: Polish Soothe CLI Subcommands

**RFC:** N/A (Internal refactoring)
**Status:** Implementation Guide
**Created:** 2026-03-21
**Scope:** CLI command structure redesign

## Overview

This guide provides step-by-step instructions for refactoring the Soothe CLI to create a more intuitive, discoverable command structure. This is a **breaking change** with no backward compatibility.

## Goals

- Simplify the most common operations (`soothe` for TUI, `soothe "prompt"` for headless)
- Group related commands logically (thread, config, server, agent)
- Remove redundant commands and options
- Align CLI commands with TUI slash commands

## Prerequisites

- Existing Soothe codebase
- Tests passing on current implementation
- No active development branches that depend on current CLI structure

## Implementation Steps

### Step 1: Create Feature Branch

```bash
git checkout -b feat/cli-polish
```

### Step 2: Refactor Main Entry Point

**File:** `src/soothe/cli/main.py`

#### 2.1 Remove Duplicate Registrations

Current issues in `main.py`:
- Line 35: `app.command()(config)` - registers `config` command
- Line 40: `app.command("config")(show_config)` - **DUPLICATE!**

**Action:** Delete line 40 and the import for `show_config`.

#### 2.2 Implement Default Command

Replace the entire `main.py` with:

```python
"""Main CLI entry point using Typer."""

from typing import Annotated, Literal

import typer

from soothe.cli.commands.config_cmd import config_init, config_show, config_validate
from soothe.cli.commands.run_cmd import run_impl
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

from soothe.cli.commands.autopilot_cmd import autopilot

app.command()(autopilot)


if __name__ == "__main__":
    app()
```

### Step 3: Refactor run_cmd.py

**File:** `src/soothe/cli/commands/run_cmd.py`

#### 3.1 Extract Implementation Function

Refactor the existing `run()` function:

```python
"""Run command for Soothe CLI."""

import logging
import sys
import time
from typing import Annotated, Literal

import typer

from soothe.cli.core import load_config, migrate_rocksdb_to_data_subfolder, setup_logging
from soothe.cli.execution import check_postgres_available, run_headless, run_tui

logger = logging.getLogger(__name__)


def run_impl(
    prompt: str | None,
    config: str | None,
    thread_id: str | None,
    no_tui: bool,
    autonomous: bool,
    max_iterations: int | None,
    output_format: str,
    progress_verbosity: Literal["minimal", "normal", "detailed", "debug"] | None,
) -> None:
    """Core implementation for running Soothe agent.

    Args:
        prompt: Optional prompt for headless mode
        config: Path to config file
        thread_id: Thread ID to resume
        no_tui: Force headless mode
        autonomous: Enable autonomous iteration mode
        max_iterations: Max iterations for autonomous mode
        output_format: Output format (text or jsonl)
        progress_verbosity: Progress detail level
    """
    startup_start = time.perf_counter()

    try:
        cfg = load_config(config)
        if progress_verbosity is not None:
            logging_config = cfg.logging.model_copy(update={"progress_verbosity": progress_verbosity})
            cfg = cfg.model_copy(update={"logging": logging_config})
        setup_logging(cfg)
        migrate_rocksdb_to_data_subfolder()

        # Check PostgreSQL availability if checkpointer is postgresql
        if cfg.protocols.durability.checkpointer == "postgresql" and not check_postgres_available():
            logger.warning(
                "PostgreSQL checkpointer configured but server not responding at localhost:5432. "
                "Start pgvector: docker-compose up -d"
            )

        startup_elapsed_ms = (time.perf_counter() - startup_start) * 1000
        logger.info("Startup completed in %.1fms", startup_elapsed_ms)

        if prompt or no_tui:
            run_headless(
                cfg,
                prompt or "",
                thread_id=thread_id,
                output_format=output_format,
                autonomous=autonomous,
                max_iterations=max_iterations,
            )
        else:
            run_tui(cfg, thread_id=thread_id, config_path=config)

    except KeyboardInterrupt:
        typer.echo("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        logger.exception("CLI run error")
        from soothe.utils.error_format import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        sys.exit(1)
```

**REMOVE the old `run()` function entirely.**

### Step 4: Create autopilot_cmd.py

**File:** `src/soothe/cli/commands/autopilot_cmd.py` (NEW)

```python
"""Autopilot command for autonomous execution."""

import typer
from typing import Annotated

def autopilot(
    prompt: Annotated[
        str,
        typer.Argument(help="Task for autonomous execution."),
    ],
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
) -> None:
    """Run task in autonomous mode with iterative execution.

    Examples:
        soothe autopilot "Research AI safety"
        soothe autopilot "Build a tool" --max-iterations 10
    """
    from soothe.cli.commands.run_cmd import run_impl

    run_impl(
        prompt=prompt,
        config=config,
        thread_id=None,
        no_tui=True,
        autonomous=True,
        max_iterations=max_iterations,
        output_format=output_format,
        progress_verbosity=None,
    )
```

### Step 5: Refactor thread_cmd.py

**File:** `src/soothe/cli/commands/thread_cmd.py`

#### 5.1 Rename thread_resume to thread_continue

Replace `thread_resume` function with:

```python
def thread_continue(
    thread_id: Annotated[
        str | None,
        typer.Argument(help="Thread ID to continue. Omit to continue last active thread."),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Continue a conversation thread in the TUI.

    If no thread ID is provided, continues the most recently active thread.

    Examples:
        soothe thread continue abc123
        soothe thread continue  # Continue last active thread
    """
    cfg = load_config(config)

    # If no thread_id provided, find last active thread
    if not thread_id:
        import asyncio
        from soothe.core.runner import SootheRunner

        runner = SootheRunner(cfg)

        async def get_last_thread() -> str | None:
            threads = await runner.list_threads()
            active_threads = [t for t in threads if t.get("status") == "active"]
            if not active_threads:
                typer.echo("No active threads found.", err=True)
                sys.exit(1)
            active_threads.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
            return active_threads[0].get("thread_id")

        thread_id = asyncio.run(get_last_thread())
        if thread_id:
            logger.info("Continuing thread %s", thread_id)

    run_tui(cfg, thread_id=thread_id, config_path=config)
```

**REMOVE the old `thread_resume` function.**

#### 5.2 Rename thread_inspect to thread_show

Rename the function:

```python
def thread_show(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to show.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Show thread details."""
    # ... same implementation as thread_inspect
```

**REMOVE the old `thread_inspect` function.**

### Step 6: Refactor config_cmd.py

**File:** `src/soothe/cli/commands/config_cmd.py`

#### 6.1 Rename config to config_show

```python
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
    # ... existing implementation from config()
```

**REMOVE the old `config()` function.**

#### 6.2 Add config_init

Move logic from `init_cmd.py`:

```python
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
    from pathlib import Path
    import shutil
    from importlib.resources import as_file, files

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
```

#### 6.3 Add config_validate

```python
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
```

### Step 7: Refactor status_cmd.py

**File:** `src/soothe/cli/commands/status_cmd.py`

#### 7.1 Rename list_subagents to agent_list

```python
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
```

**REMOVE the old `list_subagents` and `list_subagents_status` functions.**

#### 7.2 Rename list_subagents_status to agent_status

```python
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
```

**REMOVE the old `show_config` function (already handled in config_cmd.py).**

### Step 8: Refactor server_cmd.py

**File:** `src/soothe/cli/commands/server_cmd.py`

Add the `server_attach` function by moving code from `attach_cmd.py`:

```python
def server_attach(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    thread_id: Annotated[
        str | None,
        typer.Option("--thread-id", "-t", help="Thread ID to resume."),
    ] = None,
    progress_verbosity: Annotated[
        str | None,
        typer.Option("--progress-verbosity", help="Progress detail level."),
    ] = None,
) -> None:
    """Attach TUI to running daemon.

    Examples:
        soothe server attach
        soothe server attach --thread-id abc123
    """
    from soothe.cli.daemon import SootheDaemon

    if not SootheDaemon.is_running():
        typer.echo("Error: No daemon running. Use 'soothe server start'.", err=True)
        sys.exit(1)

    cfg = load_config(config)
    if progress_verbosity is not None:
        logging_config = cfg.logging.model_copy(update={"progress_verbosity": progress_verbosity})
        cfg = cfg.model_copy(update={"logging": logging_config})

    try:
        from soothe.cli.tui import run_textual_tui

        run_textual_tui(config=cfg, thread_id=thread_id, config_path=config)
    except ImportError:
        typer.echo("Error: Textual is required for TUI. Install: pip install 'textual>=0.40.0'", err=True)
        sys.exit(1)
```

### Step 9: Delete Obsolete Files

Remove these files entirely:

```bash
rm src/soothe/cli/commands/init_cmd.py      # Merged into config_cmd.py
rm src/soothe/cli/commands/attach_cmd.py    # Merged into server_cmd.py
```

### Step 10: Update __init__.py

**File:** `src/soothe/cli/commands/__init__.py`

Update exports:

```python
"""CLI command groups for Soothe."""

from soothe.cli.commands.autopilot_cmd import autopilot
from soothe.cli.commands.config_cmd import config_init, config_show, config_validate
from soothe.cli.commands.server_cmd import server_attach, server_start, server_status, server_stop
from soothe.cli.commands.status_cmd import agent_list, agent_status
from soothe.cli.commands.thread_cmd import (
    thread_archive,
    thread_continue,
    thread_delete,
    thread_export,
    thread_show,
    thread_list,
)

__all__ = [
    "agent_list",
    "agent_status",
    "autopilot",
    "config_init",
    "config_show",
    "config_validate",
    "server_attach",
    "server_start",
    "server_status",
    "server_stop",
    "thread_archive",
    "thread_continue",
    "thread_delete",
    "thread_export",
    "thread_list",
    "thread_show",
]
```

### Step 11: Update Documentation

#### 11.1 README.md

Update Quick Start section:

```markdown
## Quick Start

1. **Install Soothe**:
   ```bash
   pip install soothe
   ```

2. **Set your API key**:
   ```bash
   export OPENAI_API_KEY=sk-your-key-here
   ```

3. **Run Soothe**:
   ```bash
   soothe                    # Interactive TUI
   ```

   Or run a single task:
   ```bash
   soothe "Research quantum computing"
   ```
```

#### 11.2 docs/user_guide.md

Update all command examples:

**Basic Usage section:**
```markdown
### Interactive TUI Mode

Launch the interactive terminal interface:

```bash
soothe
```

### Headless Mode

Run a single prompt and exit:

```bash
soothe "Research the latest developments in quantum computing"
```

### Resume a Previous Session

Continue from where you left off:

```bash
soothe thread continue abc123
```

Or continue the last active thread:

```bash
soothe thread continue
```
```

**Update all other command examples throughout the document using the migration mapping table.**

#### 11.3 Add Migration Guide

Add new section to docs/user_guide.md:

```markdown
## CLI Changes

If you've been using older versions of Soothe, here are the command changes:

### Simplified Default Command
- Old: `soothe run` → New: `soothe`
- Old: `soothe run "prompt"` → New: `soothe "prompt"`

### Better Organization
- Old: `soothe run --thread abc` → New: `soothe thread continue abc`
- Old: `soothe run --continue` → New: `soothe thread continue`
- Old: `soothe run --list-threads` → New: `soothe thread list`
- Old: `soothe run --autonomous "task"` → New: `soothe autopilot "task"`

### Unified Config
- Old: `soothe init` → New: `soothe config init`
- Old: `soothe show_config` → New: `soothe config show`

### Better Naming
- Old: `soothe attach` → New: `soothe server attach`
- Old: `soothe list-subagents` → New: `soothe agent list`
- Old: `soothe thread resume` → New: `soothe thread continue`
```

### Step 12: Testing

#### 12.1 Test Default Command

```bash
# Should open TUI
soothe

# Should run headless
soothe "test prompt"

# Should respect options
soothe --config custom.yml
soothe --format jsonl "test"
```

#### 12.2 Test All Commands

```bash
# Config commands
soothe config init
soothe config validate
soothe config show
soothe config show --show-sensitive
soothe config show --format json

# Thread commands
soothe thread list
soothe thread continue
soothe thread show <id>
soothe thread archive <id>
soothe thread export <id>

# Server commands
soothe server start
soothe server status
soothe server attach
soothe server stop

# Agent commands
soothe agent list
soothe agent list --enabled
soothe agent status

# Autopilot
soothe autopilot "test task"
soothe autopilot "test" --max-iterations 5
```

#### 12.3 Verify Help Text

```bash
soothe --help
soothe config --help
soothe thread --help
soothe server --help
soothe agent --help
soothe autopilot --help
```

#### 12.4 Test Integration Workflows

```bash
# Full workflow test
soothe config init
soothe config validate
soothe agent list
soothe "test task"
soothe thread list
soothe thread continue
```

### Step 13: Commit Changes

```bash
git add -A
git commit -m "Refactor: Polish CLI command structure

BREAKING CHANGE: Complete CLI reorganization

- Default command: 'soothe' opens TUI, 'soothe \"prompt\"' runs headless
- Grouped commands: config, thread, server, agent
- Renamed commands for clarity: thread continue, config show, etc.
- Removed redundant commands: run, init, attach, list-subagents
- Added new commands: autopilot, config validate

Migration guide added to docs/user_guide.md"
```

### Step 14: Update Version

Update version number in `pyproject.toml` or `setup.py` to indicate breaking change.

## Rollback Plan

If issues arise:

```bash
git revert HEAD
git checkout main
git branch -D feat/cli-polish
```

## Success Criteria

- ✅ All new commands work as documented
- ✅ Help text is clear and organized
- ✅ No old commands remain in codebase
- ✅ Documentation updated and accurate
- ✅ Tests pass (update tests if needed)
- ✅ TUI slash commands align with CLI

## Post-Implementation Tasks

1. Update any CI/CD scripts that use old commands
2. Update example scripts in documentation
3. Announce breaking changes to users
4. Update any integration tests
5. Review and update API documentation if CLI is referenced

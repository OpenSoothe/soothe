"""Autopilot command for autonomous execution."""

from typing import Annotated

import typer


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
        soothe autopilot "Investage performance bottlenecks and propose solutions" --max-iterations 20
    """
    from soothe.ux.cli.commands.run_cmd import run_impl

    run_impl(
        prompt=prompt,
        config=config,
        thread_id=None,
        no_tui=True,
        autonomous=True,
        max_iterations=max_iterations,
        output_format=output_format,
        verbosity=None,
    )

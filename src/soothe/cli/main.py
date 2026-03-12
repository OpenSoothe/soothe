"""Main CLI entry point using Typer."""

import sys
from typing import Annotated, Optional

import typer

from soothe.config import SootheConfig

app = typer.Typer(
    name="soothe",
    help="Multi-agent harness built on deepagents and langchain/langgraph.",
    add_completion=False,
)


@app.command()
def run(
    prompt: Annotated[
        Optional[str],
        typer.Argument(help="Prompt to send to the agent. If not provided, interactive mode will be used."),
    ] = None,
    config: Annotated[
        Optional[str],
        typer.Option("--config", "-c", help="Path to configuration file (YAML or JSON)."),
    ] = None,
) -> None:
    """Run the Soothe agent with a prompt or in interactive mode."""
    try:
        from soothe.agent import create_soothe_agent
        from soothe.config import SootheConfig

        # Load config - either from file or environment/default
        if config:
            import json

            with open(config, "r") as f:
                if config.endswith(".json"):
                    config_data = json.load(f)
                elif config.endswith(".yaml") or config.endswith(".yml"):
                    try:
                        import yaml

                        config_data = yaml.safe_load(f)
                    except ImportError:
                        typer.echo(
                            "Error: PyYAML is required for YAML config files. Install with: pip install pyyaml",
                            err=True,
                        )
                        sys.exit(1)
                else:
                    typer.echo("Error: Unsupported config file format. Use .yaml, .yml, or .json", err=True)
                    sys.exit(1)
            cfg = SootheConfig(**config_data)
        else:
            cfg = SootheConfig()

        # Create the agent
        agent = create_soothe_agent(cfg)

        if prompt:
            # Single-shot mode
            result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
            # Extract and print the response
            for item in reversed(result.get("messages", [])):
                if item.get("role") == "assistant":
                    typer.echo(item.get("content", ""))
                    break
        else:
            # Interactive mode
            typer.echo("Soothe Agent Interactive Mode (type 'quit' or 'exit' to stop)")
            typer.echo("=" * 50)
            while True:
                try:
                    user_input = typer.prompt("You", prompt_suffix="> ", default="")
                    if user_input.lower() in ("quit", "exit"):
                        typer.echo("Goodbye!")
                        break
                    if not user_input.strip():
                        continue

                    result = agent.invoke({"messages": [{"role": "user", "content": user_input}]})

                    # Print assistant responses
                    for item in reversed(result.get("messages", [])):
                        if item.get("role") == "assistant":
                            content = item.get("content", "")
                            if content:
                                typer.echo(content)
                                break
                except EOFError:
                    typer.echo("\nGoodbye!")
                    break
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


@app.command()
def list_subagents() -> None:
    """List all available subagents and their status."""
    try:
        cfg = SootheConfig()

        # Get available subagent types from agent module
        from soothe.agent import _SUBAGENT_FACTORIES

        typer.echo("\nAvailable Subagents:")
        typer.echo("-" * 50)

        # Show configured subagents
        for name, sub_cfg in cfg.subagents.items():
            status = "✓ enabled" if sub_cfg.enabled else "✗ disabled"
            model = sub_cfg.model or cfg.resolve_model_string()
            typer.echo(f"  {name}: {status}")
            typer.echo(f"    Model: {model}")

        typer.echo("-" * 50)
        typer.echo(f"\nTotal configured: {len([s for s in cfg.subagents.values() if s.enabled])} active")
        typer.echo(f"Total available: {len(_SUBAGENT_FACTORIES)}")

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


@app.command()
def config(
    show_sensitive: Annotated[
        bool,
        typer.Option("--show-sensitive", "-s", help="Show sensitive values like API keys."),
    ] = False,
) -> None:
    """Display current configuration."""
    try:
        cfg = SootheConfig()

        typer.echo("\nSoothe Configuration:")
        typer.echo("=" * 50)

        # Core settings
        typer.echo("\n[Core Settings]")
        typer.echo(f"  model: {cfg.model or '(not set)'}")
        typer.echo(f"  llm_provider: {cfg.llm_provider}")
        typer.echo(f"  llm_chat_model: {cfg.llm_chat_model}")
        typer.echo(f"  debug: {cfg.debug}")

        if show_sensitive:
            typer.echo(f"  llm_api_key: {'***SET***' if cfg.llm_api_key else '(not set)'}")
            if cfg.llm_base_url:
                typer.echo(f"  llm_base_url: {cfg.llm_base_url}")
        else:
            typer.echo(f"  llm_api_key: {'[REDACTED]' if cfg.llm_api_key else '(not set)'}")

        # Tools
        typer.echo(f"\n[Tools]")
        if cfg.tools:
            for tool in cfg.tools:
                typer.echo(f"  ✓ {tool}")
        else:
            typer.echo("  (none)")

        # Subagents
        typer.echo(f"\n[Subagents]")
        for name, sub_cfg in cfg.subagents.items():
            status = "enabled" if sub_cfg.enabled else "disabled"
            typer.echo(f"  {name}: {status}")

        # MCP servers
        typer.echo(f"\n[MCP Servers]")
        if cfg.mcp_servers:
            for i, server in enumerate(cfg.mcp_servers, 1):
                if server.command:
                    typer.echo(f"  {i}. {server.command} {' '.join(server.args)}")
                elif server.url:
                    typer.echo(f"  {i}. HTTP: {server.url}")
        else:
            typer.echo("  (none)")

        # Skills & Memory
        typer.echo(f"\n[Skills]")
        if cfg.skills:
            for skill in cfg.skills:
                typer.echo(f"  {skill}")
        else:
            typer.echo("  (none)")

        typer.echo(f"\n[Memory]")
        if cfg.memory:
            for mem in cfg.memory:
                typer.echo(f"  {mem}")
        else:
            typer.echo("  (none)")

        # Workspace
        typer.echo(f"\n[Workspace]")
        typer.echo(f"  workspace_dir: {cfg.workspace_dir or '(ephemeral)'}")

        typer.echo("\n" + "=" * 50)

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    app()

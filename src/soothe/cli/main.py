"""Main CLI entry point using Typer."""

import sys
from typing import Annotated

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
        str | None,
        typer.Argument(help="Prompt to send to the agent. If not provided, interactive mode will be used."),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file (YAML or JSON)."),
    ] = None,
) -> None:
    """Run the Soothe agent with a prompt or in interactive mode."""
    try:
        from soothe.agent import create_soothe_agent
        from soothe.config import SootheConfig

        if config:
            import json

            with open(config) as f:
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

        agent = create_soothe_agent(cfg)

        if prompt:
            result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
            for item in reversed(result.get("messages", [])):
                if item.get("role") == "assistant":
                    typer.echo(item.get("content", ""))
                    break
        else:
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

        from soothe.agent import _SUBAGENT_FACTORIES

        typer.echo("\nAvailable Subagents:")
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

        typer.echo("\n[Model Router]")
        typer.echo(f"  default: {cfg.router.default}")
        for role in ("think", "fast", "image", "embedding", "web_search"):
            value = getattr(cfg.router, role, None)
            if value:
                typer.echo(f"  {role}: {value}")

        typer.echo("\n[Providers]")
        if cfg.providers:
            for p in cfg.providers:
                key_display = "[REDACTED]" if p.api_key and not show_sensitive else (p.api_key or "(not set)")
                typer.echo(
                    f"  {p.name}: type={p.provider_type}, url={p.api_base_url or '(default)'}, key={key_display}"
                )
        else:
            typer.echo("  (none)")

        typer.echo(f"  debug: {cfg.debug}")

        typer.echo("\n[Tools]")
        if cfg.tools:
            for tool in cfg.tools:
                typer.echo(f"  - {tool}")
        else:
            typer.echo("  (none)")

        typer.echo("\n[Subagents]")
        for name, sub_cfg in cfg.subagents.items():
            status = "enabled" if sub_cfg.enabled else "disabled"
            typer.echo(f"  {name}: {status}")

        typer.echo("\n[MCP Servers]")
        if cfg.mcp_servers:
            for i, server in enumerate(cfg.mcp_servers, 1):
                if server.command:
                    typer.echo(f"  {i}. {server.command} {' '.join(server.args)}")
                elif server.url:
                    typer.echo(f"  {i}. HTTP: {server.url}")
        else:
            typer.echo("  (none)")

        typer.echo("\n[Protocols]")
        typer.echo(f"  context_backend: {cfg.context_backend}")
        typer.echo(f"  memory_backend: {cfg.memory_backend}")
        typer.echo(f"  planner_routing: {cfg.planner_routing}")
        typer.echo(f"  vector_store_provider: {cfg.vector_store_provider}")

        typer.echo("\n" + "=" * 50)

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
